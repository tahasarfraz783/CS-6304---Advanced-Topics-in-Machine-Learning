"""Export measured diagnostics and qualitative examples for the GRPO report."""
import argparse
from common.data import load_yaml, repo_path, read_jsonl
from common.logging_utils import load_json


def report(config_path='configs/grpo.yaml', prefix='normalization', run_name='standard', output_name='all_results.md'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory = repo_path(load_yaml(config_path)['results_dir'])
    lines = ['# Task 3: GRPO results', '']
    training_path = directory / f'{run_name}_train.jsonl'
    if training_path.exists():
        rows = read_jsonl(training_path)
        summary = load_json(directory / f'{run_name}_summary.json')
        lines += [f"Standard continuation: {summary['updates']} updates; {summary['generated_tokens']} generated tokens; "
                  f"{summary['wall_seconds']:.1f} seconds including loading; peak allocated VRAM "
                  f"{summary['peak_vram_bytes'] / 2**30:.2f} GiB; {summary['skipped_optimizer_steps']} skipped steps.", '',
                  'Entropy is sampled negative raw log probability, not exact distribution entropy. KL is the nonnegative k3 estimator used in the training objective, recorded on replayed tokens during each optimizer epoch.', '']
        keys = ['reward', 'kl', 'within_group_reward_std', 'uninformative_group_fraction',
                'policy_loss', 'gradient_norm', 'entropy', 'response_length']
        fig, axes = plt.subplots(4, 2, figsize=(11, 12))
        for ax, key in zip(axes.flat, keys):
            ax.plot([r['update'] for r in rows], [r[key] for r in rows], marker='.')
            ax.set(title=key.replace('_', ' '), xlabel='Update')
            ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(directory / f'{run_name}_diagnostics.png', dpi=160)
        plt.close(fig)
        lines += [f'![Continuation diagnostics]({run_name}_diagnostics.png)', '']
        eval_path = directory / f'{run_name}_evaluation.json'
        if eval_path.exists():
            evaluation = load_json(eval_path)
            lines += [f"Held-out reward: {evaluation['learned_reward']:.4f}; sampled KL: {evaluation['kl']:.4f}; "
                      f"mean length: {evaluation['response_length']:.1f} tokens; examples: {evaluation['examples']}.", '']
    group_path = directory / 'group_size_comparison.json'
    if group_path.exists():
        result = load_json(group_path)
        lines += ['## Equal-generation group-size study', '', result['partition_rule'], '',
                  result['difficulty_rule'], '', result['signal_caveat'], '',
                  '| K | Bin | Generations | Informative rate | Reward std | Advantage variance |',
                  '|---|---|---:|---:|---:|---:|']
        for c in result['conditions']:
            for label, metrics in [('all', c), *c['difficulty_bins'].items()]:
                values = [str(metrics['generations'])] + [f'{metrics[key]:.4f}' if metrics[key] is not None else 'N/A'
                    for key in ('informative_group_rate', 'mean_reward_std', 'relative_signal_variance')]
                lines.append(f"| {c['k']} | {label} | " + ' | '.join(values) + ' |')
        lines += ['']
        for example in result['qualitative_examples']:
            lines += [f"Cache prompt {example['source_index']}: rewards {example['rewards']}", '',
                      *[f'Completion excerpt: {text[:450]}' for text in example['completions']], '']
    comparison_path = directory / f'{prefix}_comparison.json'
    if comparison_path.exists():
        result = load_json(comparison_path)
        lines += ['## Normalization comparison', '', result['design'], '', result['length_bin_rule'], '',
                  result['gradient_statistic'], '', '| Condition | Held-out reward | Held-out KL | Held-out length | Training tokens generated |',
                  '|---|---:|---:|---:|---:|']
        for mode, condition in result['conditions'].items():
            e, t = condition['held_out'], condition['training']
            lines += [f"| {mode} | {e['learned_reward']:.4f} | {e['kl']:.4f} | {e['response_length']:.1f} | {t['generated_tokens']} |"]
        lines += ['', '| Condition | Length bin | Count | Mean logp gradient L1 | Mean policy normalization weight |',
                  '|---|---|---:|---:|---:|']
        for mode, condition in result['conditions'].items():
            for label, b in condition['length_bins'].items():
                lines += [f"| {mode} | {label} | {b['count']} | {b['logp_gradient_l1']} | {b['policy_gradient_weight']} |"]
        lines += ['', 'Held-out KL is a sampled log-probability difference and can be negative. Training KL uses the k3 estimator; compare held-out KL across conditions using the same estimator.', '']
        branch_rows = {mode: read_jsonl(directory / f'{prefix}_{mode}_eval.jsonl')
                       for mode in result['conditions']}
        for canonical, dr in list(zip(branch_rows['grpo'], branch_rows['dr_grpo']))[:2]:
            lines += [f"Prompt: {canonical['prompt']}", '', f"Canonical (reward {canonical['learned_reward']:.3f}): {canonical['response'][:700]}", '',
                      f"Dr. GRPO (reward {dr['learned_reward']:.3f}): {dr['response'][:700]}", '']
    lines += ['## Interpretation to complete', '',
              'Use these measurements to discuss which difficulty bins benefit from larger groups, whether normalization reallocates gradient magnitude and changes held-out length/quality, and whether low reward variation, truncated completions, noisy rewards, or numerical instability dominates the standard run.', '']
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / output_name
    destination.write_text('\n'.join(lines), encoding='utf-8')
    print(destination)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/grpo.yaml')
    ap.add_argument('--prefix', default='normalization')
    ap.add_argument('--run-name', default='standard')
    ap.add_argument('--output-name', default='all_results.md')
    args = ap.parse_args()
    report(args.config, args.prefix, args.run_name, args.output_name)


if __name__ == '__main__':
    main()
