from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import yaml
from common.data import load_yaml, read_jsonl, repo_path
from common.logging_utils import load_json, save_json


def conditions(cfg):
    for beta in cfg["betas"]:
        name = f"beta_{float(beta):.2f}"
        yield name, dict(cfg, beta=float(beta)), f"outputs/task1_dpo/{name}"


def write_comparison(cfg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    root = repo_path(cfg["results_dir"])
    records = []
    names = [("standard", cfg["standard_output"])] + [(n, a) for n, _, a in conditions(cfg)]
    keys = ("held_out_dpo_loss", "preference_accuracy", "implicit_reward_accuracy",
            "kl_reference_per_token", "reward_score_mean", "generated_tokens_mean",
            "generated_tokens_median", "generated_tokens_std", "generated_words_mean", "truncation_rate")
    for name, adapter in names:
        summary = load_json(root / f"{name}_summary.json")
        metadata = load_json(repo_path(adapter) / "run_metadata.json")
        records.append({"condition": name, "budget": "standard one epoch" if name == "standard" else "short one epoch",
                        "beta": metadata["beta"], "training_examples": metadata["examples"],
                        "updates": metadata["updates"], "skipped_updates": metadata["skipped_updates"],
                        **{k: summary[k] for k in keys}})
    with (root / "beta_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    save_json(root / "beta_comparison.json", records)
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    panels = [("held_out_dpo_loss", "Held-out DPO loss"),
              ("implicit_reward_accuracy", "Reference-adjusted accuracy"),
              ("preference_accuracy", "Raw likelihood accuracy"),
              ("kl_reference_per_token", "Reference KL per token"),
              ("reward_score_mean", "Mean reward-model score"),
              ("generated_tokens_mean", "Mean generated tokens")]
    for ax, (key, label) in zip(axes.flat, panels):
        ax.plot([r["beta"] for r in records[1:]], [r[key] for r in records[1:]], "o-", color="#2563eb")
        ax.set(xlabel="Beta", ylabel=label)
        ax.set_xticks([r["beta"] for r in records[1:]])
        ax.grid(alpha=.2)
    fig.suptitle(f"DPO beta study: {cfg['short_ablation_examples']} training examples per condition\n"
                 "DPO loss uses each run's beta; absolute loss scales differ")
    fig.tight_layout()
    figures = root / "figures"
    figures.mkdir(exist_ok=True)
    for extension in ("png", "pdf"):
        fig.savefig(figures / f"beta_comparison.{extension}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Comparison saved: {root / 'beta_comparison.csv'}", flush=True)


def run_study(config_path, dry_run=False, report_only=False):
    cfg = load_yaml(config_path)
    if report_only:
        write_comparison(cfg)
        return
    count = int(cfg["short_ablation_examples"])
    rows = read_jsonl(cfg["paths"]["dpo_standard_train"])
    if len(rows) < count:
        raise ValueError(f"Need {count} training examples, found {len(rows)}")
    digest = hashlib.sha256(json.dumps(rows[:count], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    root = repo_path(cfg["results_dir"])
    windows = math.ceil(math.ceil(count / cfg["batch_size"]) / cfg["grad_accum_steps"])
    print(f"Each beta: {count} examples, {windows} update windows/epoch, seed={cfg['seed']}; fresh initialization.", flush=True)
    for name, condition, adapter in conditions(cfg):
        snapshot = root / "configs" / f"{name}.yaml"
        commands = [
            [sys.executable, "-m", "task1_dpo.train", "--config", str(snapshot),
             "--run-name", name, "--output", adapter, "--max-examples", str(count)],
            [sys.executable, "-m", "task1_dpo.evaluate", "--config", str(snapshot),
             "--adapter", adapter, "--name", name]]
        if dry_run:
            for command in commands:
                print(subprocess.list2cmdline(command))
            continue
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if snapshot.exists() and load_yaml(snapshot) != condition:
            raise ValueError(f"Existing configuration differs: {snapshot}")
        snapshot.write_text(yaml.safe_dump(condition, sort_keys=False), encoding="utf-8")
        metadata_path = repo_path(adapter) / "run_metadata.json"
        if metadata_path.exists():
            metadata = load_json(metadata_path)
            if metadata["config"] != condition or metadata["examples"] != count or metadata["beta"] != condition["beta"]:
                raise ValueError(f"Existing checkpoint does not match condition: {adapter}")
            print(f"Reusing completed training: {name}", flush=True)
        else:
            print(f"Training {name}", flush=True)
            subprocess.run(commands[0], cwd=repo_path("."), check=True)
        summary_path = root / f"{name}_summary.json"
        if summary_path.exists():
            summary = load_json(summary_path)
            if summary["config"] != condition or summary["adapter"] != adapter:
                raise ValueError(f"Existing evaluation does not match condition: {name}")
            print(f"Reusing completed evaluation: {name}", flush=True)
        else:
            print(f"Evaluating {name}", flush=True)
            subprocess.run(commands[1], cwd=repo_path("."), check=True)
    if not dry_run:
        save_json(root / "beta_study_manifest.json", {
            "training_subset_sha256": digest, "subset_selection": "first fixed rows; no resampling",
            "training_examples": count, "betas": cfg["betas"], "seed": cfg["seed"],
            "evaluation_prompt_ids": [r.get("prompt_id") for r in read_jsonl(cfg["paths"]["dpo_standard_eval"])],
            "generation": cfg["generation"], "max_generation_tokens": cfg["max_generation_tokens"]})
        write_comparison(cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dpo.yaml")
    ap.add_argument("--dry-run", action="store_true", help="Print commands without loading models or writing outputs")
    ap.add_argument("--report-only", action="store_true", help="Rebuild comparison tables/graphs from saved results")
    args = ap.parse_args()
    run_study(args.config, args.dry_run, args.report_only)


if __name__ == "__main__":
    main()
