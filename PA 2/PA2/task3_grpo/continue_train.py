from __future__ import annotations

import argparse
import random
import time
import torch

from torch.optim import AdamW

from common.data import load_yaml, read_jsonl, repo_path, prompt_messages
from common.logging_utils import set_seed, save_json, append_jsonl
from common.models import load_policy, load_reward_model, load_tokenizer, trainable_parameters
from common.models import reference_mode
from common.generation import batch_generate, score_reward_pairs
from common.metrics import masked_mean
from task2_ppo.runtime import logprobs, release_memory
from task3_grpo.grpo import group_relative_advantages, grpo_policy_loss, mask_truncated_sequences


def collect_rollouts(bundle, indices):
    """Serial generation/scoring keeps four vocabulary-sized graphs off the GPU."""
    cfg, policy = bundle['cfg'], bundle['policy']
    samples = []
    for group, index in enumerate(indices):
        prompt = prompt_messages(bundle['prompt_rows'][index])
        for generation in range(int(cfg['num_generations'])):
            rollout = batch_generate(policy, bundle['tokenizer'], [prompt],
                int(cfg['max_prompt_length']), int(cfg['max_completion_length']), **cfg['generation'])
            for key in ('sequences', 'attention_mask', 'response_ids', 'response_mask'):
                rollout[key] = rollout[key].clone()
            with torch.no_grad():
                old = logprobs(policy, rollout)
                with reference_mode(policy):
                    ref = logprobs(policy, rollout)
                reward = score_reward_pairs(bundle['reward_model'], bundle['reward_tokenizer'],
                    [prompt], rollout['responses'], int(cfg.get('reward_max_length', 1024)))[0]
            samples.append({'rollout': {k: v.cpu() if torch.is_tensor(v) else v for k, v in rollout.items()},
                'old': old.cpu(), 'ref': ref.cpu(), 'reward': float(reward),
                'group_id': group, 'source_index': index, 'generation_index': generation, 'prompt': prompt})
    return samples


def prompt_indices(cfg, count, update):
    order = list(range(count))
    random.Random(int(cfg['seed'])).shuffle(order)
    return [order[(update * int(cfg['prompts_per_update']) + j) % count]
            for j in range(int(cfg['prompts_per_update']))]


def prepare_grpo_continuation(config_path: str):
    cfg = load_yaml(config_path)
    set_seed(int(cfg["seed"]))
    tokenizer = load_tokenizer(cfg["base_model"])
    policy = load_policy(
        cfg,
        adapter_path=cfg["paths"]["grpo_midpoint_policy"],
        trainable=True,
    )
    reward_model, reward_tokenizer = load_reward_model(cfg)
    prompts = read_jsonl(cfg["paths"]["rl_prompt_train"])
    if not prompts:
        raise ValueError('Empty prompt pool')
    for parameter in trainable_parameters(policy):
        parameter.data = parameter.data.float()
    # Keep training mode so the backbone uses gradient checkpointing. Zeroing
    # dropout probabilities also survives generation/reference mode switches.
    policy.train()
    for module in policy.modules():
        if isinstance(module, torch.nn.Dropout):
            module.p = 0.0
    optimizer = AdamW(trainable_parameters(policy), lr=float(cfg["learning_rate"]))
    return {
        "cfg": cfg,
        "tokenizer": tokenizer,
        "policy": policy,
        "reward_model": reward_model,
        "reward_tokenizer": reward_tokenizer,
        "prompt_rows": prompts,
        "optimizer": optimizer,
    }


def run_grpo(config_path: str, output: str | None = None, updates: int | None = None, loss_type: str = "grpo", run_name: str = "standard", rollout_plan=None):
    initial = load_yaml(config_path)
    out = repo_path(output or initial['output'])
    result_dir = repo_path(initial['results_dir'])
    log_path = result_dir / f'{run_name}_train.jsonl'
    if out.exists() or log_path.exists():
        raise FileExistsError('Output exists; choose a new --output and --run-name')
    if updates is not None and updates < 1:
        raise ValueError('updates must be positive')
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    bundle = prepare_grpo_continuation(config_path)
    cfg = bundle["cfg"]
    if updates is not None:
        cfg["updates"] = int(updates)
    out = repo_path(output or cfg["output"])
    out.parent.mkdir(parents=True, exist_ok=True)

    plan = torch.load(repo_path(rollout_plan), map_location='cpu', weights_only=False) if rollout_plan else None
    if plan is not None and len(plan) != int(cfg['updates']):
        raise ValueError('Rollout plan must have exactly one batch per update')
    policy, optimizer = bundle['policy'], bundle['optimizer']
    params = trainable_parameters(policy)
    device = next(policy.parameters()).device
    scaler = torch.amp.GradScaler('cuda', enabled=device.type == 'cuda', init_scale=256.)
    out.mkdir(parents=True)
    save_json(out / 'run_config.json', {**cfg, 'loss_type': loss_type, 'rollout_plan': rollout_plan})
    history = []
    for update in range(int(cfg['updates'])):
        set_seed(int(cfg['seed']) + update)
        samples = plan[update] if plan is not None else collect_rollouts(bundle,
            prompt_indices(cfg, len(bundle['prompt_rows']), update))
        rewards = torch.tensor([s['reward'] for s in samples], device=device)
        groups = torch.tensor([s['group_id'] for s in samples], device=device)
        advantages = group_relative_advantages(rewards, groups).detach()
        masks = [mask_truncated_sequences(s['rollout']['response_mask'], s['rollout']['truncated'])
                 if cfg['mask_truncated_completions'] else s['rollout']['response_mask'] for s in samples]
        total_tokens = sum(float(m.sum()) for m in masks)
        epoch_stats, length_stats = [], []
        for epoch in range(int(cfg['policy_epochs'])):
            optimizer.zero_grad(set_to_none=True)
            policy_term = kl_value = clip_value = 0.
            for i, sample in enumerate(samples):
                rollout = {k: v.to(device) if torch.is_tensor(v) else v for k, v in sample['rollout'].items()}
                mask = masks[i].to(device)
                new = logprobs(policy, rollout)
                # Single-sequence losses / B exactly reproduce the full-batch
                # policy mean and global token-weighted KL in grpo_policy_loss.
                kl_weight = len(samples) * float(mask.sum()) / max(total_tokens, 1.)
                loss, metrics = grpo_policy_loss(new, sample['old'].to(device), advantages[i:i+1],
                    mask, sample['ref'].to(device), cfg['clip_epsilon'], cfg['kl_beta'] * kl_weight,
                    loss_type, int(cfg['max_completion_length']))
                loss = loss / len(samples)
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError('Non-finite GRPO loss')
                # Derivative with respect to sampled token log probabilities
                # measures allocation directly, before parameter-space mixing.
                derivative = torch.autograd.grad(loss, new, retain_graph=True)[0]
                length_stats.append({'epoch': epoch, 'response_length': sample['rollout']['response_lengths'][0],
                    'masked': not bool(mask.sum()), 'advantage': float(advantages[i]),
                    'logp_gradient_l1': float(derivative.detach().abs().sum()),
                    'policy_gradient_weight': float(mask.sum()) / (max(float(mask.sum()), 1.)
                        if loss_type == 'grpo' else cfg['max_completion_length']) / len(samples),
                    'reward': sample['reward'], 'source_index': sample['source_index']})
                scaler.scale(loss).backward()
                policy_term += float(metrics['policy_term']) / len(samples)
                kl_value += float(metrics['sampled_kl']) * float(mask.sum()) / max(total_tokens, 1.)
                clip_value += float(metrics['clip_fraction']) * float(mask.sum()) / max(total_tokens, 1.)
                del rollout, new, loss, derivative
            scaler.unscale_(optimizer)
            finite = all(bool(torch.isfinite(p.grad).all()) for p in params if p.grad is not None)
            norm = float(torch.nn.utils.clip_grad_norm_(params, cfg['max_grad_norm'])) if finite else None
            if not finite and not scaler.is_enabled():
                raise FloatingPointError('Non-finite GRPO gradients')
            if total_tokens > 0:
                scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)
            epoch_stats.append({'policy_loss': policy_term, 'kl': kl_value, 'clip_fraction': clip_value,
                                'gradient_norm': norm, 'skipped': not finite or total_tokens == 0})
        stds = [float(rewards[groups == g].std(unbiased=False)) for g in torch.unique(groups)]
        generated = sum(s['rollout']['response_lengths'][0] for s in samples)
        record = {'update': update + 1, 'reward': float(rewards.mean()),
            'within_group_reward_std': sum(stds) / len(stds),
            'uninformative_group_fraction': sum(v <= 1e-6 for v in stds) / len(stds),
            'kl': sum(e['kl'] for e in epoch_stats) / len(epoch_stats),
            'policy_loss': sum(e['policy_loss'] for e in epoch_stats) / len(epoch_stats),
            'gradient_norm': max((e['gradient_norm'] for e in epoch_stats if e['gradient_norm'] is not None), default=None),
            'entropy': sum(float(-(s['old'] * s['rollout']['response_mask']).sum()) for s in samples) / max(generated, 1),
            'response_length': generated / len(samples), 'generated_tokens': generated,
            'training_tokens': int(total_tokens), 'truncated_fraction': sum(s['rollout']['truncated'][0] for s in samples) / len(samples),
            'epochs': epoch_stats, 'length_statistics': length_stats, 'wall_seconds': time.perf_counter() - started}
        append_jsonl(log_path, record)
        for s in samples:
            append_jsonl(result_dir / f'{run_name}_rollouts.jsonl', {'update': update + 1,
                'source_index': s['source_index'], 'generation_index': s['generation_index'],
                'prompt': s['prompt'], 'response': s['rollout']['responses'][0], 'reward': s['reward']})
        history.append(record)
        print(f"{run_name} {update + 1}/{cfg['updates']}: reward={record['reward']:.3f}, KL={record['kl']:.4f}", flush=True)
    policy.save_pretrained(out)
    bundle['tokenizer'].save_pretrained(out)
    torch.save({'optimizer': optimizer.state_dict(), 'scaler': scaler.state_dict()}, out / 'optimizer.pt')
    summary = {'adapter': str(out), 'run_name': run_name, 'loss_type': loss_type, 'updates': len(history),
        'generated_tokens': sum(r['generated_tokens'] for r in history),
        'training_tokens': sum(r['training_tokens'] for r in history), 'wall_seconds': time.perf_counter() - started,
        'peak_vram_bytes': torch.cuda.max_memory_allocated() if device.type == 'cuda' else 0,
        'skipped_optimizer_steps': sum(e['skipped'] for r in history for e in r['epochs']),
        'rollout_mode': 'fixed midpoint replay' if plan is not None else 'on-policy',
        'entropy_estimator': 'sampled negative raw log probability', 'config': cfg}
    save_json(result_dir / f'{run_name}_summary.json', summary)
    del bundle, policy, optimizer, params
    release_memory()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/grpo.yaml")
    ap.add_argument("--output")
    ap.add_argument("--updates", type=int)
    ap.add_argument("--loss-type", choices=["grpo", "dr_grpo"], default="grpo")
    ap.add_argument("--run-name", default="standard")
    ap.add_argument('--rollout-plan')
    args = ap.parse_args()
    run_grpo(args.config, args.output, args.updates, args.loss_type, args.run_name, args.rollout_plan)


if __name__ == "__main__":
    main()
