from __future__ import annotations

import argparse
import subprocess
import sys
import torch
from torch.utils.data import DataLoader

from common.data import load_yaml, read_jsonl, prompt_messages_from_preference, write_jsonl, repo_path
from common.models import load_policy, load_reward_model, load_tokenizer, reference_mode
from common.generation import response_sequence_logprobs, batch_generate, response_token_logprobs, score_reward_pairs
from common.logging_utils import set_seed, save_json, load_json
from common.metrics import word_count
from task1_dpo.train import make_collate
from task1_dpo.dpo import dpo_loss


def run_worker(command, attempts=3, stage="Evaluation"):
    """Retry only Windows native access violations, keeping experiment settings fixed."""
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(command, cwd=repo_path("."), check=True)
            return
        except subprocess.CalledProcessError as error:
            if (error.returncode & 0xFFFFFFFF) != 0xC0000005 or attempt == attempts:
                raise
            print(f"{stage} worker access violation; restarting fresh process ({attempt + 1}/{attempts}). "
                  "Saved checkpoints and evaluation caches are preserved.", flush=True)


def run_reward_worker(command, attempts=3):
    run_worker(command, attempts=attempts, stage="Reward")


def load_evaluation_bundle(config_path: str, adapter: str):
    cfg = load_yaml(config_path)
    metadata = repo_path(adapter) / "run_metadata.json"
    if metadata.exists():
        cfg["beta"] = float(load_json(metadata)["beta"])
    return {
        "cfg": cfg,
        "rows": read_jsonl(cfg["paths"]["dpo_standard_eval"]),
        "tokenizer": load_tokenizer(cfg["base_model"]),
        "policy": load_policy(cfg, adapter_path=adapter, trainable=False),
    }


@torch.no_grad()
def generate_phase(config_path: str, adapter: str, name: str):
    print(f"Loading policy for {name}", flush=True)
    bundle = load_evaluation_bundle(config_path, adapter)
    cfg, rows, tokenizer, model = (bundle[k] for k in ("cfg", "rows", "tokenizer", "policy"))
    if not rows:
        raise ValueError("Evaluation dataset is empty")
    set_seed(int(cfg["seed"]))
    device = next(model.parameters()).device
    # Batch size one keeps generation/evaluation feasible on small GPUs.
    loader = DataLoader(rows, batch_size=1, shuffle=False,
                        collate_fn=make_collate(tokenizer, int(cfg["max_sequence_length"])))
    pairs, generations = [], []
    for row, (chosen, rejected) in zip(rows, loader):
        chosen = {k: v.to(device) for k, v in chosen.items()}
        rejected = {k: v.to(device) for k, v in rejected.items()}
        pc = response_sequence_logprobs(model, chosen)[0]
        pr = response_sequence_logprobs(model, rejected)[0]
        with reference_mode(model):
            rc = response_sequence_logprobs(model, chosen)[0]
            rr = response_sequence_logprobs(model, rejected)[0]
        loss, diagnostics = dpo_loss(pc, pr, rc, rr, float(cfg["beta"]))
        pairs.append({"prompt_id": row.get("prompt_id"), "loss": float(loss),
                      **{k: float(v) for k, v in diagnostics.items()}})
        prompt = prompt_messages_from_preference(row)
        out = batch_generate(model, tokenizer, [prompt], int(cfg["max_sequence_length"]),
                             int(cfg["max_generation_tokens"]), **cfg["generation"])
        p, policy_logits = response_token_logprobs(model, out["sequences"], out["attention_mask"],
                                      out["prompt_width"], out["response_ids"])
        with reference_mode(model):
            r, ref_logits = response_token_logprobs(model, out["sequences"], out["attention_mask"],
                                          out["prompt_width"], out["response_ids"])
        # Monte Carlo log-ratio on policy-generated tokens. With temperature/top-p,
        # this is a decoding-distribution estimate, not exact policy KL.
        mask = out["response_mask"]
        # Exact categorical KL at each generated prefix, averaged over sampled prefixes.
        kl_sum = 0.0
        for t in range(int(mask.sum())):
            lp = policy_logits[0, t].float().log_softmax(-1)
            lr = ref_logits[0, t].float().log_softmax(-1)
            kl_sum += float((lp.exp() * (lp - lr)).sum())
        generations.append({"prompt_id": row.get("prompt_id"), "messages": prompt,
                            "response": out["responses"][0],
                            "tokens": out["response_lengths"][0],
                            "words": word_count(out["responses"][0]),
                            "truncated": out["truncated"][0],
                            "conditional_kl_sum": kl_sum,
                            "sampled_log_ratio_sum": float(((p - r) * mask).sum())})
        del policy_logits, ref_logits
        if len(pairs) % 10 == 0:
            print(f"Evaluated {len(pairs)}/{len(rows)} pairs", flush=True)
    cache = repo_path(cfg["results_dir"]) / f"{name}_evaluation_cache.json"
    save_json(cache, {"adapter": adapter, "config": cfg, "pairs": pairs, "generations": generations})
    print(f"Saved all policy evaluation results: {cache}", flush=True)
    # Exit this worker before loading the quantized reward model in another process.


@torch.no_grad()
def score_phase(config_path: str, adapter: str, name: str):
    cfg = load_yaml(config_path)
    cfg["beta"] = float(load_json(repo_path(adapter) / "run_metadata.json")["beta"])
    cache = load_json(repo_path(cfg["results_dir"]) / f"{name}_evaluation_cache.json")
    if cache["adapter"] != adapter or cache["config"] != cfg:
        raise ValueError("Cached evaluation does not match adapter/configuration")
    pairs, generations = cache["pairs"], cache["generations"]
    progress_path = repo_path(cfg["results_dir"]) / f"{name}_reward_progress.json"
    if progress_path.exists():
        progress = load_json(progress_path)
        if progress["adapter"] != adapter or progress["config"] != cfg:
            raise ValueError("Reward progress does not match this experiment")
        for index, score in enumerate(progress["scores"]):
            generations[index]["reward_score"] = score
    print("Loading reward model in a fresh process", flush=True)
    reward, reward_tok = load_reward_model(cfg)
    for index, record in enumerate(generations):
        if "reward_score" not in record:
            record["reward_score"] = float(score_reward_pairs(
                reward, reward_tok, [record["messages"]], [record["response"]])[0])
        if (index + 1) % 10 == 0:
            temporary = progress_path.with_suffix(".tmp.json")
            save_json(temporary, {"adapter": adapter, "config": cfg,
                                  "scores": [r["reward_score"] for r in generations[:index + 1]]})
            temporary.replace(progress_path)
            print(f"Reward-scored {index + 1}/{len(generations)} responses", flush=True)
    n = len(pairs)
    lengths = torch.tensor([record["tokens"] for record in generations], dtype=torch.float32)
    summary = {"name": name, "adapter": adapter, "config": cfg, "examples": n,
               "held_out_dpo_loss": sum(r["loss"] for r in pairs) / n,
               "preference_accuracy": sum(r["preference_accuracy"] for r in pairs) / n,
               "implicit_reward_accuracy": sum(r["implicit_reward_accuracy"] for r in pairs) / n,
               "reward_score_mean": sum(r["reward_score"] for r in generations) / n,
               "generated_tokens_mean": float(lengths.mean()),
               "generated_tokens_median": float(lengths.quantile(0.5)),
               "generated_tokens_std": float(lengths.std(unbiased=False)),
               "generated_words_mean": sum(r["words"] for r in generations) / n,
               "truncation_rate": sum(r["truncated"] for r in generations) / n,
               "kl_reference_per_token": sum(r["conditional_kl_sum"] for r in generations) / float(lengths.sum()),
               "sampled_reference_log_ratio_per_token": sum(r["sampled_log_ratio_sum"] for r in generations) / float(lengths.sum()),
               "kl_note": "kl_reference_per_token is exact vocabulary KL for unmodified policy/reference distributions at prefixes sampled with configured decoding. The separate sampled log-ratio is not exact KL and may be negative."}
    base = cfg["results_dir"]
    write_jsonl(f"{base}/{name}_pairs.jsonl", pairs)
    write_jsonl(f"{base}/{name}_generations.jsonl", generations)
    save_json(f"{base}/{name}_summary.json", summary)
    print(summary)
    return summary


def evaluate(config_path: str, adapter: str, name: str):
    """Run policy and reward evaluation in separate CUDA process lifetimes."""
    cfg = load_yaml(config_path)
    metadata = repo_path(adapter) / "run_metadata.json"
    if metadata.exists():
        cfg["beta"] = float(load_json(metadata)["beta"])
    cache_path = repo_path(cfg["results_dir"]) / f"{name}_evaluation_cache.json"
    command = [sys.executable, "-X", "faulthandler", "-m", "task1_dpo.evaluate", "--config", config_path,
               "--adapter", adapter, "--name", name]
    if cache_path.exists():
        cache = load_json(cache_path)
        expected_ids = [r.get("prompt_id") for r in read_jsonl(cfg["paths"]["dpo_standard_eval"])]
        if (cache["adapter"] != adapter or cache["config"] != cfg or
            [r["prompt_id"] for r in cache["pairs"]] != expected_ids or
            len(cache["generations"]) != len(expected_ids)):
            raise ValueError("Existing evaluation cache differs from this experiment")
        print("Reusing saved policy evaluation; running reward scoring only", flush=True)
    else:
        run_worker(command + ["--phase", "generate"], stage="Policy")
    run_reward_worker(command + ["--phase", "score"])
    return load_json(repo_path(cfg["results_dir"]) / f"{name}_summary.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dpo.yaml")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--name", default="standard")
    ap.add_argument("--phase", choices=["all", "generate", "score"], default="all")
    args = ap.parse_args()
    if args.phase == "generate":
        generate_phase(args.config, args.adapter, args.name)
    elif args.phase == "score":
        score_phase(args.config, args.adapter, args.name)
    else:
        evaluate(args.config, args.adapter, args.name)


if __name__ == "__main__":
    main()
