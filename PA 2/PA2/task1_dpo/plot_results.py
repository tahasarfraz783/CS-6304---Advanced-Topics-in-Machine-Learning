"""Plot saved standard DPO results without rerunning training or evaluation."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from common.data import read_jsonl, repo_path
from common.logging_utils import load_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="standard")
    parser.add_argument("--train-name", default="standard_retry")
    args = parser.parse_args()
    root = repo_path("results/task1_dpo")
    summary = load_json(root / f"{args.name}_summary.json")
    training = read_jsonl(root / f"{args.train_name}_train.jsonl")
    generations = read_jsonl(root / f"{args.name}_generations.jsonl")
    destination = root / "figures"
    destination.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 120})
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    updates, means = [], []
    for update in sorted({r["updates"] for r in training if r["updates"] > 0}):
        # Group actual microbatches by their configured accumulation window.
        accum = int(summary["config"]["grad_accum_steps"])
        records = [r for r in training if (r["batch"] - 1) // accum + 1 == update]
        if records:
            updates.append(update)
            means.append(np.mean([r["loss"] for r in records]))
    axes[0].plot(updates, means, color="#2563eb", alpha=.35, linewidth=1,
                 label="Accumulation-window mean")
    if len(means) >= 10:
        axes[0].plot(updates[9:], np.convolve(means, np.ones(10)/10, mode="valid"),
                     color="#2563eb", linewidth=2, label="10-window moving mean")
    axes[0].axhline(np.log(2), color="#666666", linestyle="--", label="Equal-policy loss: ln(2)")
    axes[0].set(xlabel="Accumulation window", ylabel="DPO loss", title="Training preference fitting")
    axes[0].legend(fontsize=8)
    finished = [r["tokens"] for r in generations if not r["truncated"]]
    capped = [r["tokens"] for r in generations if r["truncated"]]
    cap = int(summary["config"]["max_generation_tokens"])
    axes[1].hist([finished, capped], bins=np.linspace(0, cap, 17), stacked=True,
                 color=["#0d9488", "#ea580c"], label=["Finished", "Hit generation cap"])
    axes[1].set(xlabel="Generated tokens (includes EOS if present)", ylabel="Responses",
                title=f"Response length ({summary['truncation_rate']:.0%} capped)")
    axes[1].legend(fontsize=8)
    accuracies = [summary["preference_accuracy"] * 100, summary["implicit_reward_accuracy"] * 100]
    bars = axes[2].bar(["Raw sequence\nlikelihood", "Reference-adjusted\nimplicit reward"],
                       accuracies, color=["#64748b", "#7c3aed"], width=.6)
    axes[2].set(ylabel="Held-out preference accuracy (%)", ylim=(0, 100),
                title=f"Two accuracy definitions (n={summary['examples']})")
    for bar, value in zip(bars, accuracies):
        axes[2].text(bar.get_x()+bar.get_width()/2, value+2, f"{value:.1f}%", ha="center")
    fig.suptitle("Standard DPO: one epoch, beta = 0.10", fontsize=15)
    fig.tight_layout()
    for extension in ("png", "pdf"):
        path = destination / f"{args.name}_overview.{extension}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        print(path)
    plt.close(fig)


if __name__ == "__main__":
    main()
