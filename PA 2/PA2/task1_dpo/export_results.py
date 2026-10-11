"""Export all existing Task 1 results; does not run models."""
import csv
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from common.data import repo_path, read_jsonl
from common.logging_utils import load_json


def table(records):
    keys = list(records[0])
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(keys) + " |", "| " + " | ".join(["---"]*len(keys)) + " |"] +
                     ["| " + " | ".join(cell(r[k]) for k in keys) + " |" for r in records])


def main():
    root = repo_path("results/task1_dpo")
    overview = load_json(root / "beta_comparison.json")
    runs = [("standard", "standard_retry"), ("beta_0.03", "beta_0.03"),
            ("beta_0.10", "beta_0.10"), ("beta_0.30", "beta_0.30"), ("length_balanced", "length_balanced")]
    budget = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for name, log_name in runs:
        meta = load_json(repo_path(f"outputs/task1_dpo/{name}/run_metadata.json"))
        budget.append({"Run": name, "Beta": meta["beta"], "Training pairs": meta["examples"],
                       "Updates": meta["updates"], "Skipped": meta["skipped_updates"],
                       "Training minutes": round(meta["wall_seconds"]/60, 2)})
        logs = read_jsonl(root / f"{log_name}_train.jsonl")
        accum = int(meta["config"]["grad_accum_steps"])
        windows = sorted({(r["batch"]-1)//accum+1 for r in logs})
        means = [np.mean([r["loss"] for r in logs if (r["batch"]-1)//accum+1 == window]) for window in windows]
        ax = axes[0] if name in ("standard", "length_balanced") else axes[1]
        smooth = np.convolve(means, np.ones(10)/10, mode="valid")
        ax.plot(windows[9:], smooth, label=name)
    for ax in axes:
        ax.axhline(np.log(2), color="gray", linestyle="--", linewidth=1, label="ln(2)")
        ax.set(xlabel="Accumulation window", ylabel="DPO loss (10-window moving mean)")
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    axes[0].set_title("One-epoch runs: 1,500 training pairs")
    axes[1].set_title("Short runs: 600 pairs; loss scale depends on beta")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(root / "figures" / f"all_training_curves.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    report = ["# Task 1: complete saved results", "Generated from saved artifacts; no model reruns.",
              "## Training budgets", table(budget), "## Standard and beta summary", table(overview),
              "Raw accuracy compares chosen/rejected sequence likelihood. Reference-adjusted accuracy compares DPO implicit rewards. "
              "Sequence likelihoods are sums, so raw accuracy is length-sensitive. KL is vocabulary KL averaged over generated prefixes. "
              "Beta-specific DPO losses have different scales. Standard versus beta runs have different training budgets."]
    for filename, title in (("length_strata_comparison.csv", "Length-stratified results"),
                            ("word_limit_comparison.csv", "Word-limit summary")):
        with (root / filename).open(encoding="utf-8") as handle:
            report += [f"## {title}", table(list(csv.DictReader(handle)))]
    word_pairs = read_jsonl(root / "word_limit_paired_examples.jsonl")
    report += ["## Every word-limit prompt", table([
        {"ID": r["prompt_id"], "Prompt": r["prompt"], "Standard words": r["standard"]["words"],
         "Standard compliant": r["standard"]["compliant"], "Balanced words": r["length_balanced"]["words"],
         "Balanced compliant": r["length_balanced"]["compliant"]} for r in word_pairs])]
    report += ["## Graphs"]
    for name in ("standard_overview", "beta_comparison", "length_comparison", "all_training_curves"):
        report.append(f"![{name}]({(root / 'figures' / (name + '.png')).as_posix()})")
    report += ["## Limits of the evidence", "Single seed; only ten word-limit prompts. Main generation evaluation hits the "
               "256-token cap frequently. The balanced model was evaluated on the stratified pairs and word-limit prompts; "
               "it has no separate reward/KL evaluation on the standard 300-pair set. No frozen-reference generated-answer "
               "baseline was collected. Selected qualitative examples are documented separately; they do not estimate an aggregate error rate."]
    qualitative = root / "qualitative_evidence.md"
    if qualitative.exists():
        report.append(f"[Qualitative evidence and Research Question 3]({qualitative.as_posix()})")
    appendix = ["# Task 1: every saved evaluated example", "Full prompts, generated responses, metrics, and pair diagnostics."]
    for name in ("standard", "beta_0.03", "beta_0.10", "beta_0.30"):
        pairs = read_jsonl(root / f"{name}_pairs.jsonl")
        generations = read_jsonl(root / f"{name}_generations.jsonl")
        assert len(pairs) == len(generations) == 300
        combined = []
        appendix.append(f"## {name}: 300 held-out pairs and generated responses")
        for pair, generation in zip(pairs, generations):
            assert pair["prompt_id"] == generation["prompt_id"]
            prompt = "\n".join(f"{m['role']}: {m['content']}" for m in generation["messages"])
            record = {**pair, **{k: v for k, v in generation.items() if k != "messages"}, "prompt": prompt}
            combined.append(record)
            appendix += [f"### Prompt {pair['prompt_id']}", prompt,
                         "**Generated response:**", generation["response"],
                         "**Metrics:**", "```json\n" + json.dumps({k: v for k, v in record.items() if k not in ("prompt", "response")}, indent=2) + "\n```"]
        export = root / f"{name}_all_examples.csv"
        with export.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(combined[0]))
            writer.writeheader()
            writer.writerows(combined)
        report.append(f"[{name}: all 300 generated responses and pair metrics]({export.as_posix()})")
    for name in ("standard", "length_balanced"):
        appendix += [f"## {name}: 246 length-stratified pair diagnostics",
                     table(read_jsonl(root / f"{name}_length_pairs.jsonl"))]
    appendix += ["## All 20 word-limit responses"]
    for record in word_pairs:
        appendix += [f"### {record['prompt_id']}", record["prompt"]]
        for name in ("standard", "length_balanced"):
            r = record[name]
            appendix += [f"**{name}: {r['words']} words, compliant={r['compliant']}**", r["response"]]
    appendix_path = root / "all_evaluated_examples.md"
    appendix_path.write_text("\n\n".join(appendix), encoding="utf-8")
    report += [f"[Full appendix: 1,200 generated answers, 492 stratified pair diagnostics, and 20 word-limit answers]({appendix_path.as_posix()})",
               "## Raw artifact inventory", "Includes training logs, checkpoint metadata separately under outputs/task1_dpo, and interrupted-run logs."]
    for path in sorted(root.glob("*.json*")):
        report.append(f"[{path.name}]({path.as_posix()})")
    target = root / "all_results.md"
    target.write_text("\n\n".join(report), encoding="utf-8")
    print(target)
    print(appendix_path)


if __name__ == "__main__":
    main()
