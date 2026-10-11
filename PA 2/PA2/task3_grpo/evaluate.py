from __future__ import annotations

import argparse
import torch

from common.data import load_yaml, read_jsonl, prompt_messages, repo_path
from common.models import load_policy, load_reward_model, load_tokenizer
from common.models import reference_mode
from common.logging_utils import set_seed, append_jsonl, save_json
from common.generation import score_reward_pairs
from common.metrics import masked_mean
from task2_ppo.runtime import logprobs
from common.generation import batch_generate


def load_evaluation_bundle(config_path: str, adapter: str):
    if not (repo_path(adapter) / 'adapter_config.json').is_file():
        raise FileNotFoundError(f'No saved policy adapter at {repo_path(adapter)}. Complete training successfully before evaluation.')
    cfg = load_yaml(config_path)
    return {
        "cfg": cfg,
        "rows": read_jsonl(cfg["paths"]["rl_prompt_eval"]),
        "tokenizer": load_tokenizer(cfg["base_model"]),
        "policy": load_policy(cfg, adapter_path=adapter, trainable=False),
        "reward": load_reward_model(cfg),
    }


def run_evaluation(config_path, adapter, name='standard', max_examples=None):
    cfg = load_yaml(config_path)
    directory = repo_path(cfg['results_dir'])
    destination = directory / f'{name}_eval.jsonl'
    if destination.exists():
        raise FileExistsError(f'Evaluation exists: {destination}')
    bundle = load_evaluation_bundle(config_path, adapter)
    policy, tokenizer = bundle['policy'], bundle['tokenizer']
    rm, rm_tokenizer = bundle['reward']
    rows = bundle['rows'] if max_examples is None else bundle['rows'][:max_examples]
    if not rows:
        raise ValueError('Empty evaluation set')
    results = []
    for index, row in enumerate(rows):
        set_seed(int(cfg['seed']) + index)
        prompt = prompt_messages(row)
        rollout = batch_generate(policy, tokenizer, [prompt], int(cfg['max_prompt_length']), int(cfg.get('eval_max_completion_length', cfg['max_completion_length'])), **cfg['generation'])
        with torch.no_grad():
            lp = logprobs(policy, rollout)
            with reference_mode(policy):
                ref = logprobs(policy, rollout)
            reward = float(score_reward_pairs(rm, rm_tokenizer, [prompt], rollout['responses'],
                                             int(cfg.get('reward_max_length', 1024)))[0])
        mask = rollout['response_mask']
        result = {'source_index': index, 'prompt_id': row.get('prompt_id', row.get('id', index)),
                  'prompt': prompt, 'response': rollout['responses'][0], 'learned_reward': reward,
                  'effective_reward': reward - (0 if rollout['terminated_with_eos'][0] else 0.0),
                  'kl': float(masked_mean(lp - ref, mask)),
                  'entropy': float(-masked_mean(lp, mask)),
                  'response_length': rollout['response_lengths'][0],
                  'terminated_with_eos': rollout['terminated_with_eos'][0], 'truncated': rollout['truncated'][0]}
        append_jsonl(destination, result)
        results.append(result)
        print(f'{name}: evaluated {index + 1}/{len(rows)}', flush=True)
    summary = {'name': name, 'adapter': str(repo_path(adapter)), 'examples': len(results),
               'seed': cfg['seed'], 'generation': cfg['generation'],
               'max_response_length': cfg.get('eval_max_completion_length', cfg['max_completion_length']),
               'entropy_estimator': 'sampled negative raw log-probability',
               'kl_estimator': 'sampled token log-probability difference; may be negative',
               'aggregation': 'equal weight per prompt',
               **{key: sum(r[key] for r in results) / len(results) for key in
                  ('learned_reward', 'effective_reward', 'kl', 'entropy', 'response_length', 'truncated', 'terminated_with_eos')}}
    save_json(directory / f'{name}_evaluation.json', summary)
    del bundle, policy, rm
    from task2_ppo.runtime import release_memory
    release_memory()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/grpo.yaml")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--name", default="standard")
    ap.add_argument('--max-examples', type=int, help='Smoke-test subset; omit for final evaluation')
    args = ap.parse_args()
    run_evaluation(args.config, args.adapter, args.name, args.max_examples)


if __name__ == "__main__":
    main()
