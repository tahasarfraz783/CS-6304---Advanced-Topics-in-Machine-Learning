"""Shared PPO rollout scoring and checkpoint utilities."""
from __future__ import annotations

import gc
import torch
from common.generation import batch_generate
from common.metrics import masked_mean


def generate(policy, tokenizer, prompts, cfg, evaluation=False):
    return batch_generate(policy, tokenizer, prompts, int(cfg['max_prompt_length']),
                          int(cfg['eval_max_response_length'] if evaluation else cfg['max_response_length']),
                          **cfg['generation'])


def logprobs(policy, rollout):
    """Raw policy probabilities; chunk vocabulary softmax to reduce peak memory."""
    logits = policy(input_ids=rollout['sequences'], attention_mask=rollout['attention_mask'],
                    use_cache=False, return_dict=True).logits
    width = rollout['prompt_width']
    targets = rollout['response_ids']
    pieces = []
    for start in range(0, targets.shape[1], 32):
        end = min(start + 32, targets.shape[1])
        lp = logits[:, width - 1 + start:width - 1 + end].float().log_softmax(-1)
        pieces.append(lp.gather(-1, targets[:, start:end, None]).squeeze(-1))
    return torch.cat(pieces, dim=1)


def values(critic, rollout):
    # Use the underlying sequence classifier so PEFT's base_model_prefix does
    # not accidentally select the classifier's pooled forward.
    base = critic.get_base_model() if hasattr(critic, 'get_base_model') else critic
    backbone = getattr(base, base.base_model_prefix)
    hidden = backbone(input_ids=rollout['sequences'], attention_mask=rollout['attention_mask'],
                      use_cache=False, return_dict=True).last_hidden_state
    # V(s_t) is evaluated before the sampled action, matching its log-probability.
    start = rollout['prompt_width'] - 1
    head_dtype = next((p.dtype for p in base.score.parameters() if p.requires_grad),
                      next(base.score.parameters()).dtype)
    states = hidden[:, start:start + rollout['response_ids'].shape[1]].to(head_dtype)
    return base.score(states).squeeze(-1).float()


def optimizer_step(loss, optimizer, params, scaler, max_norm):
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError('Non-finite PPO loss')
    optimizer.zero_grad(set_to_none=True)
    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)
    finite = all(bool(torch.isfinite(p.grad).all()) for p in params if p.grad is not None)
    norm = float(torch.nn.utils.clip_grad_norm_(params, max_norm)) if finite else None
    if not finite and not scaler.is_enabled():
        raise FloatingPointError('Non-finite PPO gradients')
    scaler.step(optimizer)
    scaler.update()
    optimizer.zero_grad(set_to_none=True)
    return norm, not finite


def critic_diagnostics(prediction, returns, mask):
    p, r = prediction[mask.bool()], returns[mask.bool()]
    variance = r.var(unbiased=False)
    ev = float(1 - (r - p).var(unbiased=False) / variance) if variance > 1e-8 else None
    return {'value_mean': float(p.mean()), 'return_mean': float(r.mean()),
            'value_explained_variance': ev}


def release_memory():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
