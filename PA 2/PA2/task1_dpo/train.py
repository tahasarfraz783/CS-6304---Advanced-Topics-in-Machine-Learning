from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from common.data import (
    encode_prompt_response,
    load_yaml,
    pad_batch,
    preference_responses,
    prompt_messages_from_preference,
    read_jsonl,
    repo_path,
)
from common.logging_utils import set_seed
from common.logging_utils import append_jsonl, save_json, wall_timer
from common.generation import response_sequence_logprobs
from common.models import reference_mode
from common.models import load_policy, load_tokenizer, trainable_parameters
from task1_dpo.dpo import dpo_loss


def make_collate(tokenizer, max_length):
    def collate(rows):
        chosen, rejected = [], []
        for row in rows:
            prompt = prompt_messages_from_preference(row)
            yc, yr = preference_responses(row)
            chosen.append(encode_prompt_response(tokenizer, prompt, yc, max_length))
            rejected.append(encode_prompt_response(tokenizer, prompt, yr, max_length))
        return pad_batch(tokenizer, chosen), pad_batch(tokenizer, rejected)
    return collate


def optimizer_update(optimizer, params, scaler, max_grad_norm):
    """Let GradScaler skip overflowing FP16 updates without corrupting parameters."""
    scaler.unscale_(optimizer)
    finite = all(bool(torch.isfinite(p.grad).all()) for p in params if p.grad is not None)
    if finite:
        torch.nn.utils.clip_grad_norm_(params, max_grad_norm, error_if_nonfinite=True)
    elif not scaler.is_enabled():
        raise FloatingPointError("Non-finite gradients without an enabled loss scaler")
    # unscale_ recorded overflow; step skips AdamW and update lowers the scale.
    scaler.step(optimizer)
    scaler.update()
    optimizer.zero_grad(set_to_none=True)
    return finite


def prepare_dpo_run(config_path: str, dataset_path: str | None = None, beta: float | None = None, max_examples: int | None = None):
    cfg = load_yaml(config_path)
    set_seed(int(cfg["seed"]))
    path = dataset_path or cfg["paths"]["dpo_standard_train"]
    rows = read_jsonl(path)
    if max_examples is not None:
        rows = rows[: int(max_examples)]

    tokenizer = load_tokenizer(cfg["base_model"])
    model = load_policy(cfg, trainable=True, fresh_lora=True)
    loader = DataLoader(
        rows,
        batch_size=int(cfg["batch_size"]),
        shuffle=True,
        collate_fn=make_collate(tokenizer, int(cfg["max_sequence_length"])),
    )
    optimizer = AdamW(
        trainable_parameters(model),
        lr=float(cfg["learning_rate"]),
        weight_decay=float(cfg.get("weight_decay", 0.0)),
    )
    return {
        "cfg": cfg,
        "rows": rows,
        "tokenizer": tokenizer,
        "model": model,
        "loader": loader,
        "optimizer": optimizer,
        "beta": float(cfg["beta"] if beta is None else beta),
    }


def run_training(config_path: str, run_name: str, dataset_path: str | None = None, output_path: str | None = None, beta: float | None = None, max_examples: int | None = None):
    bundle = prepare_dpo_run(config_path, dataset_path, beta, max_examples)
    cfg = bundle["cfg"]
    output = repo_path(output_path or cfg["standard_output"])
    output.parent.mkdir(parents=True, exist_ok=True)

    model, loader, optimizer = bundle["model"], bundle["loader"], bundle["optimizer"]
    if not bundle["rows"]:
        raise ValueError("Training dataset is empty")
    device = next(model.parameters()).device
    params = trainable_parameters(model)
    accum = int(cfg["grad_accum_steps"])
    if accum < 1:
        raise ValueError("grad_accum_steps must be positive")
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda", init_scale=256.0)
    timer = wall_timer()
    log_path = repo_path(cfg["results_dir"]) / f"{run_name}_train.jsonl"
    if log_path.exists() or output.exists():
        raise FileExistsError("Run output already exists; choose a new run name/output")
    optimizer.zero_grad(set_to_none=True)
    updates = 0
    skipped_updates = 0
    for epoch in range(int(cfg["epochs"])):
        for index, (chosen, rejected) in enumerate(loader):
            chosen = {k: v.to(device) for k, v in chosen.items()}
            rejected = {k: v.to(device) for k, v in rejected.items()}
            # The frozen base weights are the reference; disable adapters and dropout.
            with torch.no_grad(), reference_mode(model):
                ref_c = response_sequence_logprobs(model, chosen)[0]
                ref_r = response_sequence_logprobs(model, rejected)[0]
            # Weight by examples, including an incomplete final accumulation window.
            window_start = (index // accum) * accum
            window_end = min(window_start + accum, len(loader))
            window_examples = min(window_end * int(cfg["batch_size"]), len(bundle["rows"])) - window_start * int(cfg["batch_size"])
            batch_examples = chosen["input_ids"].shape[0]
            # Backpropagate each response separately to avoid keeping two graphs in VRAM.
            with torch.no_grad():
                rng_cpu = torch.get_rng_state()
                rng_cuda = torch.cuda.get_rng_state_all() if device.type == "cuda" else None
                pol_c = response_sequence_logprobs(model, chosen)[0]
                rng_after_c = torch.get_rng_state()
                cuda_after_c = torch.cuda.get_rng_state_all() if device.type == "cuda" else None
                pol_r = response_sequence_logprobs(model, rejected)[0]
            loss, diagnostics = dpo_loss(pol_c, pol_r, ref_c, ref_r, bundle["beta"])
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite DPO loss; this is not a recoverable gradient overflow")
            logits = bundle["beta"] * (pol_c - pol_r - ref_c + ref_r)
            derivative = -bundle["beta"] * torch.sigmoid(-logits) / batch_examples
            weight = batch_examples / window_examples
            torch.set_rng_state(rng_cpu)
            if rng_cuda is not None:
                torch.cuda.set_rng_state_all(rng_cuda)
            c = response_sequence_logprobs(model, chosen)[0]
            scaler.scale((c * derivative * weight).sum()).backward()
            torch.set_rng_state(rng_after_c)
            if cuda_after_c is not None:
                torch.cuda.set_rng_state_all(cuda_after_c)
            r = response_sequence_logprobs(model, rejected)[0]
            scaler.scale((-r * derivative * weight).sum()).backward()
            boundary = index + 1 == window_end
            if boundary:
                applied = optimizer_update(optimizer, params, scaler, float(cfg["max_grad_norm"]))
                updates += int(applied)
                skipped_updates += int(not applied)
            record = {"epoch": epoch + 1, "batch": index + 1, "updates": updates,
                      "loss": float(loss), "beta": bundle["beta"],
                      "skipped_updates": skipped_updates, "loss_scale": scaler.get_scale(),
                      **{k: float(v) for k, v in diagnostics.items()}}
            append_jsonl(log_path, record)
            if boundary:
                print(f"epoch={epoch + 1} update={updates} loss={float(loss):.4f} "
                      f"skipped={skipped_updates} scale={scaler.get_scale():g}", flush=True)
    model.save_pretrained(output)
    bundle["tokenizer"].save_pretrained(output)
    save_json(output / "run_metadata.json", {"config": cfg, "run_name": run_name,
              "beta": bundle["beta"], "examples": len(bundle["rows"]),
              "dataset": dataset_path or cfg["paths"]["dpo_standard_train"],
              "updates": updates, "skipped_updates": skipped_updates,
              "initial_loss_scale": 256.0, "wall_seconds": timer()})
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dpo.yaml")
    ap.add_argument("--run-name", default="standard")
    ap.add_argument("--dataset")
    ap.add_argument("--output")
    ap.add_argument("--beta", type=float)
    ap.add_argument("--max-examples", type=int)
    args = ap.parse_args()
    run_training(args.config, args.run_name, args.dataset, args.output, args.beta, args.max_examples)


if __name__ == "__main__":
    main()
