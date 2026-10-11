from __future__ import annotations

import argparse
from collections import defaultdict
import numpy as np

from common.data import load_yaml, read_jsonl, repo_path
from common.logging_utils import save_json


def load_k8_cache(path):
    rows = read_jsonl(path)
    by_prompt = defaultdict(list)
    for row in rows:
        by_prompt[str(row["source_index"])].append(row)
    # Instructor cache has 8 rows per prompt, one row per completion.
    bad = {pid: len(group) for pid, group in by_prompt.items() if len(group) != 8}
    if bad:
        raise ValueError(f"Expected exactly K=8 cached completions per prompt: {bad}")
    for group in by_prompt.values():
        group.sort(key=lambda x: int(x.get("generation_index", 0)))
    return by_prompt


def regroup_equal_generation_budget(by_prompt, k: int):
    """Return K-sized groups while keeping total cached completions fixed.

    Students should decide and document exactly how prompts/completions are partitioned for the
    requested equal-generation comparison.
    """
    if k not in (2, 4, 8):
        raise ValueError('K must be 2, 4, or 8')
    groups = []
    for pid, rows in by_prompt.items():
        if len(rows) != 8:
            raise ValueError('Each prompt must have exactly eight completions')
        ordered = sorted(rows, key=lambda r: int(r['generation_index']))
        if len({r['generation_index'] for r in ordered}) != 8:
            raise ValueError('Duplicate generation indices')
        groups.extend((pid, ordered[start:start+k]) for start in range(0, 8, k))
    return groups


def summarize_groups(groups, eps=1e-6):
    if not groups:
        return {'groups': 0, 'generations': 0, 'informative_group_rate': None,
                'mean_reward_std': None, 'relative_signal_variance': None}
    stds, signals = [], []
    for _, rows in groups:
        rewards = np.asarray([r['reward'] for r in rows], dtype=float)
        if not np.isfinite(rewards).all():
            raise ValueError('Cache rewards must be finite')
        std = float(rewards.std(ddof=0))
        stds.append(std)
        signals.extend(((rewards - rewards.mean()) / (std + eps)).tolist())
    return {'groups': len(groups), 'generations': len(signals),
            'informative_group_rate': float(np.mean(np.asarray(stds) > eps)),
            'mean_reward_std': float(np.mean(stds)),
            'relative_signal_variance': float(np.var(signals))}


def run_study(config_path):
    cfg = load_yaml(config_path)
    by_prompt = load_k8_cache(cfg['group_cache'])
    if not by_prompt:
        raise ValueError('Empty group cache')
    means = {pid: float(np.mean([r['reward'] for r in rows])) for pid, rows in by_prompt.items()}
    threshold = float(np.median(list(means.values())))
    bins = {pid: 'lower_reward' if mean <= threshold else 'higher_reward' for pid, mean in means.items()}
    result = {'difficulty_rule': 'Mean reward over all eight completions; <= global median is lower_reward, > median is higher_reward. Reward is a proxy for difficulty.',
        'difficulty_threshold': threshold, 'informative_rule': 'population reward std > 1e-6',
        'partition_rule': 'Sort by generation_index and split each prompt into disjoint consecutive K-sized groups; use every cached completion once per K.',
        'signal_definition': '(reward - group mean)/(population group std + 1e-6); population variance across all completion advantages',
        'signal_caveat': 'Standardization makes informative-group variance near one; this statistic largely tracks the rate of informative groups.',
        'conditions': []}
    for k in cfg['group_sizes']:
        groups = regroup_equal_generation_budget(by_prompt, k)
        condition = {'k': k, **summarize_groups(groups),
            'difficulty_bins': {label: summarize_groups([g for g in groups if bins[g[0]] == label])
                                for label in ('lower_reward', 'higher_reward')}}
        result['conditions'].append(condition)
        print(f"K={k}: generations={condition['generations']}, informative={condition['informative_group_rate']:.3f}")
    result['qualitative_examples'] = [{'source_index': pid, 'difficulty_bin': bins[pid],
        'rewards': [r['reward'] for r in rows], 'completions': [r['completion'] for r in rows[:2]]}
        for pid, rows in sorted(by_prompt.items(), key=lambda item: np.std([r['reward'] for r in item[1]]))[:2]]
    save_json(repo_path(cfg['results_dir']) / 'group_size_comparison.json', result)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/grpo.yaml")
    args = ap.parse_args()
    run_study(args.config)


if __name__ == "__main__":
    main()
