from __future__ import annotations

import argparse
import sys
import statistics
import json
from common.data import load_yaml, repo_path, read_jsonl
from task3_grpo.process_utils import run_stage


def load_json(path):
    return json.loads(repo_path(path).read_text(encoding='utf-8'))


def save_json(path, value):
    path = repo_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def build_plan(config_path, updates, plan_path):
    import torch
    from common.logging_utils import set_seed
    from task3_grpo.continue_train import prepare_grpo_continuation, collect_rollouts, prompt_indices
    cfg = load_yaml(config_path)
    bundle = prepare_grpo_continuation(config_path)
    plan = []
    for update in range(updates):
        set_seed(int(cfg['seed']) + update)
        plan.append(collect_rollouts(bundle, prompt_indices(cfg, len(bundle['prompt_rows']), update)))
        print(f'Collected shared midpoint batch {update + 1}/{updates}', flush=True)
    plan_path = repo_path(plan_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(plan, plan_path)
    lengths = [s['rollout']['response_lengths'][0] for batch in plan for s in batch]
    eligible_lengths = [s['rollout']['response_lengths'][0] for batch in plan for s in batch
                        if not cfg['mask_truncated_completions'] or not s['rollout']['truncated'][0]]
    save_json(plan_path.with_suffix('.json'), {'median_length': float(statistics.median(eligible_lengths or lengths)),
                                             'unmasked_completions': len(eligible_lengths),
                                             'generated_tokens': sum(lengths), 'updates': updates})


def run_comparison(config_path, updates=None, max_eval_examples=None, prefix='normalization'):
    cfg = load_yaml(config_path)
    updates = int(updates if updates is not None else cfg['fork_updates'])
    if updates < 1:
        raise ValueError('updates must be positive')
    directory = repo_path(cfg['results_dir'])
    plan_path = directory / f'{prefix}_midpoint_rollouts.pt'
    branches = {mode: (f'{prefix}_{mode}', repo_path(f'outputs/task3_grpo/{prefix}_{mode}'))
                for mode in ('grpo', 'dr_grpo')}
    for name, output in branches.values():
        if output.exists() or (directory / f'{name}_train.jsonl').exists() or (directory / f'{name}_eval.jsonl').exists():
            raise FileExistsError(f'Branch output exists: {name}; choose another --prefix')
    if plan_path.exists():
        raise FileExistsError(f'Plan exists: {plan_path}; choose another --prefix')
    # A separate collector process releases its CUDA context before training;
    # an idle parent CUDA context would consume scarce memory on the 6 GB GPU.
    run_stage([sys.executable, '-m', 'task3_grpo.compare_normalization', '--config', str(repo_path(config_path)),
        '--updates', str(updates), '--build-plan', '--plan-path', str(plan_path)], cwd=repo_path('.'),
        log_path=directory / f'{prefix}_console.log')
    threshold = load_json(plan_path.with_suffix('.json'))['median_length']
    conditions = {}
    for mode, (name, output) in branches.items():
        run_stage([sys.executable, '-m', 'task3_grpo.continue_train', '--config', str(repo_path(config_path)),
            '--output', str(output), '--updates', str(updates), '--loss-type', mode,
            '--run-name', name, '--rollout-plan', str(plan_path)], cwd=repo_path('.'),
            log_path=directory / f'{prefix}_console.log')
        command = [sys.executable, '-m', 'task3_grpo.evaluate', '--config', str(repo_path(config_path)),
                   '--adapter', str(output), '--name', name]
        if max_eval_examples is not None:
            command.extend(['--max-examples', str(max_eval_examples)])
        run_stage(command, cwd=repo_path('.'), log_path=directory / f'{prefix}_console.log')
        records = read_jsonl(directory / f'{name}_train.jsonl')
        stats = [s for r in records for s in r['length_statistics'] if not s['masked']]
        bins = {}
        for label, short in [('short', True), ('long', False)]:
            rows = [s for s in stats if (s['response_length'] <= threshold) == short]
            bins[label] = {'count': len(rows), **{key: statistics.mean(s[key] for s in rows) if rows else None
                for key in ('response_length', 'logp_gradient_l1', 'policy_gradient_weight', 'reward')}}
        conditions[mode] = {'training': load_json(directory / f'{name}_summary.json'),
                            'held_out': load_json(directory / f'{name}_evaluation.json'),
                            'length_bins': bins}
    if len({c['training']['generated_tokens'] for c in conditions.values()}) != 1:
        raise RuntimeError('Normalization branch token budgets differ')
    if len({c['training']['training_tokens'] for c in conditions.values()}) != 1:
        raise RuntimeError('Normalization branch unmasked token budgets differ')
    result = {'design': 'Controlled fixed midpoint rollout replay; both branches start from the same adapter and use identical completions, rewards, old log probabilities, reference, prompts, token budget, and optimizer settings. Later updates are off-policy with respect to the fixed generator; held-out evaluation generates fresh responses.',
              'length_bin_rule': f'Unmasked responses <= median length of unmasked shared rollouts ({threshold}) are short; greater are long. If all responses are masked, both bins are empty.',
              'gradient_statistic': 'L1 derivative of full loss with respect to sampled token log probabilities; policy_gradient_weight also isolates normalization independently of reward and KL.',
              'conditions': conditions}
    save_json(directory / f'{prefix}_comparison.json', result)
    print(f'Saved comparison: {directory / (prefix + "_comparison.json")}', flush=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/grpo.yaml")
    ap.add_argument('--updates', type=int)
    ap.add_argument('--max-eval-examples', type=int)
    ap.add_argument('--prefix', default='normalization')
    ap.add_argument('--build-plan', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--plan-path', help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.build_plan:
        if not args.plan_path or not args.updates:
            ap.error('--build-plan requires --updates and --plan-path')
        build_plan(args.config, args.updates, args.plan_path)
    else:
        run_comparison(args.config, args.updates, args.max_eval_examples, args.prefix)


if __name__ == "__main__":
    main()
