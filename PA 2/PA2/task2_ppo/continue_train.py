from __future__ import annotations

import argparse
from pathlib import Path
import random
import time
import torch

from torch.optim import AdamW

from common.data import load_yaml, prompt_messages, read_jsonl, repo_path
from common.logging_utils import set_seed
from common.logging_utils import append_jsonl, save_json
from common.generation import score_reward_pairs
from common.models import reference_mode
from common.metrics import masked_mean
from task2_ppo.ppo import compute_gae, shaped_rewards, normalize_advantages, ppo_policy_loss, value_mse_loss
from task2_ppo.runtime import generate, logprobs, values, optimizer_step, critic_diagnostics
from common.models import (
    load_policy,
    load_reward_model,
    load_tokenizer,
    load_value_model,
    trainable_parameters,
    value_parameter_groups,
)


def prepare_ppo_continuation(config_path: str):
    cfg = load_yaml(config_path)
    set_seed(int(cfg["seed"]))

    tokenizer = load_tokenizer(cfg["base_model"])
    policy = load_policy(
        cfg,
        adapter_path=cfg["paths"]["ppo_midpoint_policy"],
        trainable=True,
    )
    value_model = load_value_model(
        cfg,
        cfg["paths"]["ppo_midpoint_value"],
        train_mode=cfg.get("value_train_mode", "head_only"),
    )
    reward_model, reward_tokenizer = load_reward_model(cfg)
    prompts = read_jsonl(cfg["paths"]["rl_prompt_train"])

    # PEFT promotes LoRA weights but can leave modules_to_save (the critic
    # score head) in FP16. GradScaler requires FP32 trainable parameters.
    for model in (policy, value_model):
        for parameter in trainable_parameters(model):
            parameter.data = parameter.data.float()

    policy_optimizer = AdamW(
        trainable_parameters(policy),
        lr=float(cfg["policy_learning_rate"]),
    )
    value_optimizer = AdamW(
        value_parameter_groups(
            value_model,
            lora_lr=float(cfg["value_lora_learning_rate"]),
            head_lr=float(cfg["value_head_learning_rate"]),
        ),
        weight_decay=0.0,
    )

    return {
        "cfg": cfg,
        "tokenizer": tokenizer,
        "policy": policy,
        "value_model": value_model,
        "reward_model": reward_model,
        "reward_tokenizer": reward_tokenizer,
        "prompt_rows": prompts,
        "policy_optimizer": policy_optimizer,
        "value_optimizer": value_optimizer,
    }


def run_ppo(config_path: str, output: str | None = None, updates: int | None = None, clip_epsilon: float | None = None, kl_beta: float | None = None, run_name: str = "standard"):
    initial_cfg = load_yaml(config_path)
    out = repo_path(output or initial_cfg['output'])
    result_dir = repo_path(initial_cfg['results_dir'])
    log_path = result_dir / f'{run_name}_train.jsonl'
    if out.exists() or log_path.exists():
        raise FileExistsError('Output already exists; choose a new --output and --run-name')
    if updates is not None and updates < 1:
        raise ValueError('updates must be positive')
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    bundle = prepare_ppo_continuation(config_path)
    cfg = bundle["cfg"]
    if updates is not None:
        cfg["updates"] = int(updates)
    if clip_epsilon is not None:
        cfg["clip_epsilon"] = float(clip_epsilon)
    if kl_beta is not None:
        cfg["kl_beta"] = float(kl_beta)
    out = repo_path(output or cfg["output"])
    out.parent.mkdir(parents=True, exist_ok=True)

    policy, critic = bundle['policy'], bundle['value_model']
    # Eval mode disables dropout while still allowing gradient-based updates.
    policy.eval()
    critic.eval()
    policy_params, critic_params = trainable_parameters(policy), trainable_parameters(critic)
    device = next(policy.parameters()).device
    enabled = device.type == 'cuda'
    ps = torch.amp.GradScaler('cuda', enabled=enabled, init_scale=256.)
    vs = torch.amp.GradScaler('cuda', enabled=enabled, init_scale=256.)
    rows = bundle['prompt_rows']
    if not rows:
        raise ValueError('Empty prompt pool')
    order = list(range(len(rows)))
    random.Random(int(cfg['seed'])).shuffle(order)
    out.mkdir(parents=True)
    save_json(out / 'run_config.json', cfg)
    history = []
    training_started = time.perf_counter()
    for update in range(int(cfg['updates'])):
        # Per-update seed makes prompt/sampling random streams independent of
        # preceding branch lengths. EOS may still change actual token counts.
        set_seed(int(cfg['seed']) + update)
        indices = [order[(update * int(cfg['prompts_per_update']) + j) % len(order)]
                   for j in range(int(cfg['prompts_per_update']))]
        prompts = [prompt_messages(rows[i]) for i in indices]
        rollout = generate(policy, bundle['tokenizer'], prompts, cfg)
        # Generation uses inference_mode: clone before gradient-bearing forwards.
        for key in ('sequences', 'attention_mask', 'response_ids', 'response_mask'):
            rollout[key] = rollout[key].clone()
        mask = rollout['response_mask']
        with torch.no_grad():
            old = logprobs(policy, rollout)
            with reference_mode(policy):
                ref = logprobs(policy, rollout)
            old_values = values(critic, rollout)
            raw = score_reward_pairs(bundle['reward_model'], bundle['reward_tokenizer'], prompts,
                                     rollout['responses'], int(cfg['reward_max_length'])).to(device)
            effective = raw - float(cfg['missing_eos_penalty']) * torch.tensor(
                [not x for x in rollout['terminated_with_eos']], device=device)
            rewards = shaped_rewards(effective, old, ref, mask, cfg['kl_beta'])
            advantages, returns = compute_gae(rewards, old_values, mask, cfg['gamma'], cfg['gae_lambda'])
            advantages = normalize_advantages(advantages, mask)
        epoch_stats = []
        for epoch in range(int(cfg['ppo_epochs'])):
            new = logprobs(policy, rollout)
            ploss, ratio, fraction = ppo_policy_loss(new, old, advantages, mask, cfg['clip_epsilon'])
            pnorm, pskip = optimizer_step(ploss, bundle['policy_optimizer'], policy_params, ps, cfg['max_grad_norm'])
            del new
            predicted = values(critic, rollout)
            vloss = value_mse_loss(predicted, returns, mask)
            vnorm, vskip = optimizer_step(float(cfg['value_coef']) * vloss,
                bundle['value_optimizer'], critic_params, vs, cfg['max_grad_norm'])
            epoch_stats.append({'policy_loss': float(ploss.detach()), 'value_loss': float(vloss.detach()),
                                'clip_fraction': float(fraction), 'policy_grad_norm': pnorm,
                                'value_grad_norm': vnorm, 'policy_skipped': pskip, 'value_skipped': vskip})
            del ploss, vloss, predicted
        with torch.no_grad():
            post = logprobs(policy, rollout)
            _, ratio, fraction = ppo_policy_loss(post, old, advantages, mask, cfg['clip_epsilon'])
        record = {'update': update + 1, 'source_indices': indices,
                  'prompt_ids': [rows[i].get('prompt_id', rows[i].get('id', i)) for i in indices],
                  'learned_reward': float(raw.mean()), 'effective_reward': float(effective.mean()),
                  'kl': float(masked_mean(old - ref, mask)),
                  'post_update_rollout_kl': float(masked_mean(post - ref, mask)),
                  'entropy': float(-masked_mean(old, mask)),
                  'entropy_estimator': 'sampled negative raw log-probability',
                  'response_length': float(mask.sum(-1).mean()), 'generated_tokens': int(mask.sum()),
                  'clip_fraction': float(fraction), 'epochs': epoch_stats,
                  'policy_loss': sum(s['policy_loss'] for s in epoch_stats) / len(epoch_stats),
                  'value_loss': sum(s['value_loss'] for s in epoch_stats) / len(epoch_stats),
                  'policy_grad_norm': max((s['policy_grad_norm'] for s in epoch_stats if s['policy_grad_norm'] is not None), default=None),
                  'value_grad_norm': max((s['value_grad_norm'] for s in epoch_stats if s['value_grad_norm'] is not None), default=None),
                  'eos_rate': sum(rollout['terminated_with_eos']) / len(prompts),
                  'wall_seconds': time.perf_counter() - training_started,
                  **critic_diagnostics(old_values, returns, mask)}
        history.append(record)
        append_jsonl(log_path, record)
        append_jsonl(result_dir / f'{run_name}_rollouts.jsonl', {
            'update': update + 1, 'source_indices': indices, 'responses': rollout['responses'],
            'learned_rewards': raw.tolist()})
        print(f"{run_name} update {update + 1}/{cfg['updates']}: reward={record['learned_reward']:.3f} KL={record['kl']:.4f}", flush=True)
        del rollout, old, ref, old_values, rewards, advantages, returns, post
    policy.save_pretrained(out)
    bundle['tokenizer'].save_pretrained(out)
    critic.save_pretrained(out / 'value_model')
    torch.save({'policy_optimizer': bundle['policy_optimizer'].state_dict(),
                'value_optimizer': bundle['value_optimizer'].state_dict(),
                'policy_scaler': ps.state_dict(), 'value_scaler': vs.state_dict()}, out / 'optimizer.pt')
    summary = {'run_name': run_name, 'adapter': str(out), 'config': cfg,
               'updates': len(history), 'generated_tokens': sum(r['generated_tokens'] for r in history),
               'wall_seconds': time.perf_counter() - started,
               'training_wall_seconds': time.perf_counter() - training_started,
               'peak_vram_bytes': torch.cuda.max_memory_allocated() if enabled else 0,
               'peak_reserved_vram_bytes': torch.cuda.max_memory_reserved() if enabled else 0,
               'skipped_optimizer_steps': sum(s['policy_skipped'] + s['value_skipped'] for r in history for s in r['epochs']),
               'stability_statistic': 'maximum pre-clipping policy gradient L2 norm',
               'max_policy_grad_norm': max((r['policy_grad_norm'] for r in history if r['policy_grad_norm'] is not None), default=None)}
    save_json(result_dir / f'{run_name}_summary.json', summary)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/ppo.yaml")
    ap.add_argument("--output")
    ap.add_argument("--updates", type=int)
    ap.add_argument("--clip-epsilon", type=float)
    ap.add_argument("--kl-beta", type=float)
    ap.add_argument("--run-name", default="standard")
    args = ap.parse_args()
    run_ppo(args.config, args.output, args.updates, args.clip_epsilon, args.kl_beta, args.run_name)


if __name__ == "__main__":
    main()
