from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter

import numpy as np
import torch
from common.data import load_yaml, read_jsonl, repo_path, prompt_messages, write_jsonl
from common.models import load_policy, load_tokenizer, reference_mode
from common.generation import response_sequence_logprobs, batch_generate
from common.logging_utils import set_seed, load_json, save_json
from common.metrics import parse_word_limit, word_count
from task1_dpo.train import make_collate
from task1_dpo.dpo import dpo_loss
from task1_dpo.evaluate import run_worker

STRATA = ("preferred_longer", "length_matched", "rejected_longer")


def compliance(prompt, response):
    limit = parse_word_limit(prompt)
    if limit is None:
        raise ValueError(f"No word limit recognized: {prompt}")
    count = word_count(response)
    strict = bool(re.search(r"\bunder\s+\d+\s+words?", prompt.lower()))
    return limit, count, count < limit if strict else count <= limit


def summarize(pairs, generations):
    strata = {}
    for stratum in STRATA:
        selected = [r for r in pairs if r["length_stratum"] == stratum]
        if not selected:
            raise ValueError(f"Missing held-out stratum: {stratum}")
        strata[stratum] = {"examples": len(selected), **{
            key: float(np.mean([r[key] for r in selected])) for key in
            ("loss", "preference_accuracy", "implicit_reward_accuracy")}}
    return {"strata": strata, "word_limit_prompts": len(generations),
            "generated_tokens_mean": float(np.mean([r["tokens"] for r in generations])),
            "generated_tokens_median": float(np.median([r["tokens"] for r in generations])),
            "generated_tokens_std": float(np.std([r["tokens"] for r in generations])),
            "generated_words_mean": float(np.mean([r["words"] for r in generations])),
            "word_limit_compliance": float(np.mean([r["compliant"] for r in generations])),
            "truncation_rate": float(np.mean([r["truncated"] for r in generations]))}


def atomic_save(path, payload):
    temporary = path.with_suffix(".tmp.json")
    save_json(temporary, payload)
    temporary.replace(path)


def identity(cfg, adapter, rows, prompts):
    data_hash = hashlib.sha256(json.dumps([rows, prompts], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"config": cfg, "adapter": adapter, "input_sha256": data_hash}


@torch.no_grad()
def evaluate_length(config_path, name):
    cfg = load_yaml(config_path)
    adapter = cfg["standard_output"] if name == "standard" else cfg["length_output"]
    metadata = load_json(repo_path(adapter) / "run_metadata.json")
    if metadata["beta"] != cfg["beta"]:
        raise ValueError("Length comparison requires matched beta")
    rows = read_jsonl(cfg["paths"]["dpo_length_eval"])
    prompts = read_jsonl(cfg["paths"]["word_limit_prompts"])
    expected = identity(cfg, adapter, rows, prompts)
    root = repo_path(cfg["results_dir"])
    progress_path = root / f"{name}_length_progress.json"
    progress = {"identity": expected, "pairs": [], "generations": []}
    if progress_path.exists():
        progress = load_json(progress_path)
        if progress["identity"] != expected:
            raise ValueError("Length-evaluation cache does not match this experiment")
    pairs, generations = progress["pairs"], progress["generations"]
    if ([r["prompt_id"] for r in pairs] != [r["prompt_id"] for r in rows[:len(pairs)]] or
        [r["prompt_id"] for r in generations] != [r["prompt_id"] for r in prompts[:len(generations)]]):
        raise ValueError("Cached progress does not match the ordered evaluation prompts")
    print(f"Loading {name}; resuming after {len(pairs)} pairs and {len(generations)} word-limit prompts", flush=True)
    tokenizer = load_tokenizer(cfg["base_model"])
    model = load_policy(cfg, adapter_path=adapter, trainable=False)
    device = next(model.parameters()).device
    collate = make_collate(tokenizer, int(cfg["max_sequence_length"]))
    for index in range(len(pairs), len(rows)):
        row = rows[index]
        chosen, rejected = collate([row])
        chosen = {k: v.to(device) for k, v in chosen.items()}
        rejected = {k: v.to(device) for k, v in rejected.items()}
        pc = response_sequence_logprobs(model, chosen)[0]
        pr = response_sequence_logprobs(model, rejected)[0]
        with reference_mode(model):
            rc = response_sequence_logprobs(model, chosen)[0]
            rr = response_sequence_logprobs(model, rejected)[0]
        loss, diagnostics = dpo_loss(pc, pr, rc, rr, float(cfg["beta"]))
        pairs.append({"prompt_id": row["prompt_id"], "length_stratum": row["length_stratum"],
                      "loss": float(loss), **{k: float(v) for k, v in diagnostics.items()}})
        if (index + 1) % 10 == 0 or index + 1 == len(rows):
            atomic_save(progress_path, progress)
            print(f"{name}: evaluated {index + 1}/{len(rows)} stratified pairs", flush=True)
    for index in range(len(generations), len(prompts)):
        row = prompts[index]
        messages = prompt_messages(row)
        prompt = "\n".join(str(m["content"]) for m in messages if m["role"] == "user")
        # Same per-prompt seed for both models; independent of earlier response lengths/resumes.
        set_seed(int(cfg["seed"]) + index)
        out = batch_generate(model, tokenizer, [messages], int(cfg["max_sequence_length"]),
                             int(cfg["max_generation_tokens"]), **cfg["generation"])
        response = out["responses"][0]
        limit, words, compliant = compliance(prompt, response)
        generations.append({"prompt_id": row["prompt_id"], "prompt": prompt, "response": response,
                            "seed": int(cfg["seed"]) + index, "word_limit": limit,
                            "words": words, "compliant": compliant,
                            "tokens": out["response_lengths"][0], "truncated": out["truncated"][0]})
        atomic_save(progress_path, progress)
        print(f"{name}: word-limit prompt {index + 1}/{len(prompts)}, words={words}, compliant={compliant}", flush=True)
    summary = {"name": name, "identity": expected, "training_examples": metadata["examples"],
               **summarize(pairs, generations)}
    write_jsonl(root / f"{name}_length_pairs.jsonl", pairs)
    write_jsonl(root / f"{name}_word_limit_generations.jsonl", generations)
    save_json(root / f"{name}_length_summary.json", summary)
    print(f"Saved {name} length diagnostics", flush=True)


def make_report(cfg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    root = repo_path(cfg["results_dir"])
    summaries = [load_json(root / f"{name}_length_summary.json") for name in ("standard", "length_balanced")]
    for filename, records in (
        ("length_strata_comparison.csv", [{"condition": s["name"], "stratum": stratum, **s["strata"][stratum]}
                                          for s in summaries for stratum in STRATA]),
        ("word_limit_comparison.csv", [{k: v for k, v in s.items() if k not in ("identity", "strata")}
                                       for s in summaries])):
        with (root / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    save_json(root / "length_comparison.json", summaries)
    standard = read_jsonl(root / "standard_word_limit_generations.jsonl")
    balanced = read_jsonl(root / "length_balanced_word_limit_generations.jsonl")
    if [r["prompt_id"] for r in standard] != [r["prompt_id"] for r in balanced]:
        raise ValueError("Word-limit comparison requires identical ordered prompt IDs")
    write_jsonl(root / "word_limit_paired_examples.jsonl", [{"prompt_id": a["prompt_id"],
                 "prompt": a["prompt"], "standard": a, "length_balanced": b} for a, b in zip(standard, balanced)])
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    positions = np.arange(3)
    for offset, s, color in zip((-.18, .18), summaries, ("#2563eb", "#0d9488")):
        axes[0].bar(positions + offset, [100*s["strata"][st]["implicit_reward_accuracy"] for st in STRATA],
                    width=.36, label=s["name"], color=color)
    axes[0].set_xticks(positions, ["Preferred\nlonger", "Length\nmatched", "Rejected\nlonger"])
    axes[0].set(ylabel="Reference-adjusted accuracy (%)", ylim=(0, 100), title="Stratified held-out preferences")
    axes[0].legend(fontsize=8)
    labels = ["Standard", "Length-balanced"]
    axes[1].bar(labels, [s["generated_words_mean"] for s in summaries], color=["#2563eb", "#0d9488"])
    axes[1].set(ylabel="Mean generated words", title="Common word-limit prompts")
    axes[2].bar(labels, [100*s["word_limit_compliance"] for s in summaries], color=["#2563eb", "#0d9488"])
    axes[2].set(ylabel="Word-limit compliance (%)", ylim=(0, 100), title="Common word-limit prompts")
    fig.suptitle("DPO length-confounding study")
    fig.tight_layout()
    figures = root / "figures"
    figures.mkdir(exist_ok=True)
    for extension in ("png", "pdf"):
        fig.savefig(figures / f"length_comparison.{extension}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Length comparison tables and plots saved in {root}", flush=True)


def run_study(config_path, dry_run=False, report_only=False):
    cfg = load_yaml(config_path)
    balanced = read_jsonl(cfg["paths"]["dpo_length_train"])
    stratified = read_jsonl(cfg["paths"]["dpo_length_eval"])
    counts = Counter(r["length_stratum"] for r in balanced)
    if set(counts) != set(STRATA) or len(set(counts.values())) != 1:
        raise ValueError("Supplied length-control training set must have equal numbers in all three strata")
    print(f"Supplied balanced train: {len(balanced)} pairs, {dict(counts)}; held-out: {len(stratified)} pairs", flush=True)
    if report_only:
        make_report(cfg)
        return
    command = [sys.executable, "-X", "faulthandler", "-m", "task1_dpo.train", "--config", config_path,
               "--run-name", "length_balanced", "--dataset", cfg["paths"]["dpo_length_train"],
               "--output", cfg["length_output"]]
    if dry_run:
        print(subprocess.list2cmdline(command))
    else:
        metadata_path = repo_path(cfg["length_output"]) / "run_metadata.json"
        if metadata_path.exists():
            metadata = load_json(metadata_path)
            if (metadata["config"] != cfg or metadata["examples"] != len(balanced) or
                metadata["dataset"] != cfg["paths"]["dpo_length_train"] or metadata["beta"] != cfg["beta"]):
                raise ValueError("Existing length-balanced checkpoint does not match this experiment")
            print("Reusing completed length-balanced training", flush=True)
        else:
            subprocess.run(command, cwd=repo_path("."), check=True)
    for name in ("standard", "length_balanced"):
        command = [sys.executable, "-X", "faulthandler", "-m", "task1_dpo.analyze_length",
                   "--config", config_path, "--worker", name]
        if dry_run:
            print(subprocess.list2cmdline(command))
            continue
        summary_path = repo_path(cfg["results_dir"]) / f"{name}_length_summary.json"
        if summary_path.exists():
            summary = load_json(summary_path)
            adapter = cfg["standard_output"] if name == "standard" else cfg["length_output"]
            expected = identity(cfg, adapter, stratified, read_jsonl(cfg["paths"]["word_limit_prompts"]))
            if summary["identity"] != expected:
                raise ValueError(f"Existing length results differ: {name}")
            print(f"Reusing completed diagnostics: {name}", flush=True)
        else:
            run_worker(command, stage=f"Length {name}")
    if not dry_run:
        save_json(repo_path(cfg["results_dir"]) / "length_dataset_diagnostics.json", {
            "training_strata": dict(counts),
            "held_out_strata": dict(Counter(r["length_stratum"] for r in stratified)),
            "standard_training_examples": len(read_jsonl(cfg["paths"]["dpo_standard_train"])),
            "word_count_definition": "Regex word tokens: \\b\\w+\\b; under N is strict, other supplied limits inclusive",
            "generation": cfg["generation"], "per_prompt_seed": "config seed + prompt index"})
        make_report(cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dpo.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--worker", choices=["standard", "length_balanced"])
    args = ap.parse_args()
    if args.worker:
        evaluate_length(args.config, args.worker)
    else:
        run_study(args.config, args.dry_run, args.report_only)


if __name__ == "__main__":
    main()
