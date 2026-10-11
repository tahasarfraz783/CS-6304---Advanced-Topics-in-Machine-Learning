from __future__ import annotations

import argparse
import torch

from common.data import load_yaml, repo_path, read_jsonl, prompt_messages
from common.models import load_policy, load_tokenizer
from common.logging_utils import save_json, set_seed
from common.metrics import masked_mean
from task2_ppo.ppo import shaped_rewards, compute_gae, normalize_advantages, ppo_policy_loss
from task2_ppo.runtime import logprobs, release_memory
from task2_ppo.studies import run_forks


def load_cached_rollouts(path):
    rows = torch.load(repo_path(path), map_location="cpu", weights_only=False)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a non-empty list in the supplied PPO rollout cache")

    # Instructor iterations used two equivalent names for these fields. Normalize once here so
    # the student analysis code sees one stable interface.
    normalized = []
    for row in rows:
        row = dict(row)
        if "old_logprobs" not in row and "old_policy_logprobs" in row:
            row["old_logprobs"] = row["old_policy_logprobs"]
        if "ref_logprobs" not in row and "reference_logprobs" in row:
            row["ref_logprobs"] = row["reference_logprobs"]
        normalized.append(row)

    required = {"source_index", "response", "old_logprobs", "ref_logprobs"}
    if not required.issubset(normalized[0]):
        raise ValueError(f"Unexpected PPO cache schema; need at least {sorted(required)}")
    return normalized


def analyze_cached(config_path):
    cfg = load_yaml(config_path)
    set_seed(int(cfg['seed']))
    rows = load_cached_rollouts(cfg['cached_rollouts'])
    prompt_rows = read_jsonl(cfg['paths']['rl_prompt_train']) + read_jsonl(cfg['paths']['rl_prompt_eval'])
    prompts = {row['prompt_id']: row for row in prompt_rows}
    tokenizer = load_tokenizer(cfg['base_model'])
    policy = load_policy(cfg, cfg['paths']['ppo_midpoint_policy'], trainable=False)
    device = next(policy.parameters()).device
    batches = []
    for row in rows:
        # Cache source_index belongs to the original source dataset, not a
        # position in the released prompt pool. Resolve by stable prompt ID.
        messages = prompt_messages(prompts[row['prompt_id']])
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        prompt_ids = tokenizer(rendered, truncation=True, max_length=int(cfg['max_prompt_length']))['input_ids']
        response_ids = tokenizer(row['response'], add_special_tokens=False)['input_ids']
        if row.get('terminated_with_eos'):
            response_ids.append(tokenizer.eos_token_id)
        expected = len(row['old_logprobs'])
        if len(response_ids) != expected:
            raise ValueError(f"Cached response {row['source_index']} retokenized to {len(response_ids)} tokens; expected {expected}. Exact rollout token IDs are required; refusing misaligned analysis.")
        seq = torch.tensor([prompt_ids + response_ids], device=device)
        rollout = {'sequences': seq, 'attention_mask': torch.ones_like(seq),
                   'prompt_width': len(prompt_ids), 'response_ids': torch.tensor([response_ids], device=device)}
        with torch.no_grad():
            new = logprobs(policy, rollout).cpu()
        old = torch.as_tensor(row['old_logprobs']).float().reshape(1, -1)
        ref = torch.as_tensor(row['ref_logprobs']).float().reshape(1, -1)
        value = torch.as_tensor(row['values']).float().reshape(1, -1)
        mask = torch.ones_like(old)
        terminal = torch.tensor([float(row['effective_terminal_reward'])])
        rewards = shaped_rewards(terminal, old, ref, mask, cfg['kl_beta'])
        advantage, _ = compute_gae(rewards, value, mask, cfg['gamma'], cfg['gae_lambda'])
        batches.append((new, old, advantage))
    # Whiten over the entire fixed batch, rather than separately per response.
    new, old, adv = (torch.cat([b[i].flatten() for b in batches]).reshape(1, -1) for i in range(3))
    mask = torch.ones_like(old)
    adv = normalize_advantages(adv, mask)
    results = []
    for epsilon in cfg['clip_values']:
        loss, ratio, fraction = ppo_policy_loss(new, old, adv, mask, epsilon)
        s1 = ratio * adv
        s2 = ratio.clamp(1 - epsilon, 1 + epsilon) * adv
        results.append({'epsilon': epsilon, 'clipped_surrogate': -float(loss),
                        'unclipped_surrogate': float(masked_mean(s1, mask)),
                        'outside_ratio_bounds_fraction': float(fraction),
                        'affected_token_fraction': float(masked_mean((s2 < s1).float(), mask)),
                        'tokens': old.numel(), 'responses': len(rows)})
    save_json(repo_path(cfg['results_dir']) / 'cached_clipping.json', {
        'new_policy': cfg['paths']['ppo_midpoint_policy'],
        'old_policy': 'log-probabilities stored in supplied rollout cache',
        'advantage_normalization': 'all valid cached tokens', 'results': results})
    print(results, flush=True)
    del policy
    release_memory()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/ppo.yaml")
    ap.add_argument('--cached-only', action='store_true')
    ap.add_argument('--forks-only', action='store_true')
    args = ap.parse_args()
    if args.cached_only and args.forks_only:
        ap.error('Choose at most one of --cached-only and --forks-only')
    if not args.forks_only:
        analyze_cached(args.config)
    if not args.cached_only:
        run_forks(args.config, 'clip')


if __name__ == "__main__":
    main()
