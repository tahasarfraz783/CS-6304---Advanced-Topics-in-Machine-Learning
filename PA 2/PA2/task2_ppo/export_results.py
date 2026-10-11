"""Create diagnostic plots, summary tables, and paired qualitative review sheets."""
import argparse
import csv
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common.data import load_yaml, repo_path, read_jsonl


def export(config_path):
    cfg = load_yaml(config_path)
    root = repo_path(cfg['results_dir'])
    root.mkdir(parents=True, exist_ok=True)
    keys = ['learned_reward', 'kl', 'policy_loss', 'value_loss', 'entropy',
            'clip_fraction', 'policy_grad_norm', 'value_grad_norm', 'response_length',
            'value_explained_variance']
    for path in sorted(root.glob('*_train.jsonl')):
        rows = read_jsonl(path)
        fig, axes = plt.subplots(5, 2, figsize=(12, 15))
        for key, ax in zip(keys, axes.flat):
            ax.plot([r['update'] for r in rows],
                    [r.get(key) if r.get(key) is not None else float('nan') for r in rows], marker='o')
            ax.set(xlabel='PPO update', ylabel=key)
            ax.grid(alpha=.25)
        fig.suptitle(path.stem.removesuffix('_train'))
        fig.tight_layout()
        fig.savefig(root / f'{path.stem}_diagnostics.png', dpi=160)
        plt.close(fig)
    summaries = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(root.glob('*_evaluation.json'))]
    if summaries:
        columns = ['name', 'examples', 'learned_reward', 'effective_reward', 'kl', 'entropy',
                   'response_length', 'truncated', 'terminated_with_eos']
        with (root / 'held_out_comparison.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(summaries)
    baseline = root / 'midpoint_eval.jsonl'
    if baseline.exists():
        initial = {str(r['prompt_id']): r for r in read_jsonl(baseline)}
        review = ['# PPO qualitative review', '',
                  'Read paired responses and judge correctness, relevance, clarity, and safety independently of reward.',
                  'Choose one case where reward and quality move together and one where they disagree. Reward differences alone do not establish quality.', '']
        for path in sorted(root.glob('*_eval.jsonl')):
            if path == baseline:
                continue
            matched = [(initial[str(r['prompt_id'])], r) for r in read_jsonl(path) if str(r['prompt_id']) in initial]
            matched.sort(key=lambda pair: abs(pair[1]['learned_reward'] - pair[0]['learned_reward']), reverse=True)
            for before, after in matched[:8]:
                review.extend([f"## {path.stem}: prompt {after['prompt_id']}", '',
                    '**Prompt**', '', json.dumps(after['prompt'], ensure_ascii=False), '',
                    f"**Midpoint reward: {before['learned_reward']:.4f}**", '', before['response'], '',
                    f"**Continuation reward: {after['learned_reward']:.4f}**", '', after['response'], '',
                    '**Your quality assessment:** Pending manual review.', ''])
        (root / 'qualitative_review.md').write_text('\n'.join(review), encoding='utf-8')
    print(f'Exported available evidence to {root}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/ppo.yaml')
    export(ap.parse_args().config)
