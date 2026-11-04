"""Refresh evidence without extra plotting dependencies. SVG opens in any browser."""
import csv
import html
import math
from pathlib import Path

from .common import METHODS, read_json, read_jsonl, write_json

COLORS = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#0891b2", "#64748b"]
PRIMARY = {"gsm8k_cot": "exact_match,flexible-extract", "hellaswag": "acc_norm,none",
           "boolq": "acc,none", "arc_easy": "acc_norm,none"}


def csv_rows(path):
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_table(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def chart(path, title, series, xlabel, ylabel, categories=None):
    """Small line/scatter chart; leave missing measurements absent, never invent values."""
    series = {name: [(float(x), float(y)) for x, y in points if math.isfinite(float(y))]
              for name, points in series.items()}
    series = {name: values for name, values in series.items() if values}
    points = [p for values in series.values() for p in values]
    if not points:
        return
    xs, ys = zip(*points)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(0, min(ys)), max(ys)
    if xmax == xmin:
        xmax = xmin + 1
    if ymax == ymin:
        ymax = ymin + 1
    ymin -= (ymax - ymin) * 0.04
    ymax += (ymax - ymin) * 0.08
    width, height = 1100, 660
    left, top, right, bottom = 100, 75, 1060, 445
    def X(x):
        return left + (x - xmin) / (xmax - xmin) * (right - left)
    def Y(y):
        return bottom - (y - ymin) / (ymax - ymin) * (bottom - top)
    escape = html.escape
    content = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
               '<rect width="100%" height="100%" fill="white"/>',
               '<style>text{font-family:Arial,sans-serif;fill:#1e293b;font-size:13px}</style>',
               f'<text x="{left}" y="32" style="font-size:21px;font-weight:bold">{escape(title)}</text>']
    for i in range(6):
        value = ymin + (ymax - ymin) * i / 5
        y = Y(value)
        content.extend([f'<line x1="{left}" x2="{right}" y1="{y}" y2="{y}" stroke="#e2e8f0"/>',
                        f'<text x="{left-12}" y="{y+4}" text-anchor="end">{value:.3g}</text>'])
    ticks = list(enumerate(categories)) if categories else [(xmin + (xmax-xmin)*i/5, f"{xmin+(xmax-xmin)*i/5:.0f}") for i in range(6)]
    for x, label in ticks:
        content.append(f'<text transform="translate({X(x)},{bottom+18}) rotate(25)" text-anchor="start">{escape(str(label))}</text>')
    content.extend([f'<text x="{(left+right)/2}" y="530" text-anchor="middle">{escape(xlabel)}</text>',
                    f'<text transform="translate(23,{(top+bottom)/2}) rotate(-90)" text-anchor="middle">{escape(ylabel)}</text>'])
    for index, (name, values) in enumerate(series.items()):
        color = COLORS[index % len(COLORS)]
        coords = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in values)
        if categories is None:
            content.append(f'<polyline points="{coords}" stroke="{color}" stroke-width="2" fill="none"/>')
        for x, y in values:
            content.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="3" fill="{color}"/>')
        lx, ly = left + (index % 3) * 320, 570 + (index // 3) * 25
        content.extend([f'<rect x="{lx}" y="{ly-10}" width="14" height="4" fill="{color}"/>',
                        f'<text x="{lx+20}" y="{ly-3}">{escape(name)}</text>'])
    content.append('</svg>')
    Path(path).write_text("\n".join(content), encoding="utf-8")


def refresh(root):
    root = Path(root)
    folder = root / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    histories = {m: csv_rows(root / "runs" / m / "training.csv") for m in METHODS}
    chart(folder / "sft_loss.svg", "Supervised response-token loss", {
        m: [(r["update"], r["sft_loss"]) for r in rows] for m, rows in histories.items()
    }, "Optimizer update (attempt)", "SFT cross-entropy / response token")
    chart(folder / "learning_rate.svg", "Learning-rate schedules", {
        m: [(r["update"], r["lr"]) for r in rows] for m, rows in histories.items()
    }, "Optimizer update (attempt)", "Learning rate")
    chart(folder / "l2sp_objective.svg", "L2-SP objective components", {
        key: [(r["update"], r[key]) for r in histories["l2sp"]]
        for key in ("sft_loss", "weighted_penalty", "total_loss")
    }, "Optimizer update (attempt)", "Loss / weighted penalty")
    chart(folder / "l2sp_omega.svg", "Unweighted starting-point penalty", {
        "omega": [(r["update"], r["omega"]) for r in histories["l2sp"]]
    }, "Optimizer update (attempt)", "Omega = 0.5 * squared displacement")

    evaluations = sorted((root / "evaluations").glob("*/scores.json"))
    records = [read_json(p) for p in evaluations]
    baseline = next((r for r in records if r["method"] == "baseline"), None)
    benchmark_rows = []
    for record in records:
        row = {"condition": f'{record["method"]}_{record["update"]:04d}', "smoke_only": record["smoke_only"]}
        for task, key in PRIMARY.items():
            scores = record["results"][task]
            if key not in scores:
                raise ValueError(f"Missing prescribed metric {task}/{key}; inspect harness output.")
            row[task + "_percent"] = 100 * scores[key]
            row[task + "_delta_pp"] = 100 * (scores[key] - baseline["results"][task][key]) if baseline else ""
            row[task + "_raw_acc_percent"] = 100 * scores["acc,none"] if "acc,none" in scores else ""
        benchmark_rows.append(row)
    save_table(folder / "benchmarks.csv", benchmark_rows)
    labels = [r["condition"] for r in benchmark_rows]
    prefix = "SMOKE ONLY: " if any(r["smoke_only"] for r in records) else ""
    chart(folder / "benchmarks.svg", prefix + "Benchmark performance", {
        task: [(i, row[task + "_percent"]) for i, row in enumerate(benchmark_rows)] for task in PRIMARY
    }, "Evaluation condition", "Primary score (%)", labels)
    if baseline:
        chart(folder / "benchmark_changes.svg", prefix + "Change from unchanged baseline", {
            task: [(i, row[task + "_delta_pp"]) for i, row in enumerate(benchmark_rows)] for task in PRIMARY
        }, "Evaluation condition", "Change (percentage points)", labels)

    resources = [read_json(p) for p in sorted((root / "runs").glob("*/resources.json"))]
    save_table(folder / "resources.csv", resources)
    displacements = [{"method": p.parent.name, "update": int(p.stem.split("_")[-1]),
                      **read_json(p)} for p in sorted((root / "runs").glob("*/displacement_*.json"))]
    save_table(folder / "displacements.csv", displacements)
    displacement_labels = [f'{r["method"]}_{r["update"]:04d}' for r in displacements]
    chart(folder / "displacements.svg", "Full-model displacement from starting weights", {
        "L2 displacement": [(i, r["l2_displacement"]) for i, r in enumerate(displacements)]
    }, "Checkpoint", "Full-model L2 norm", displacement_labels)
    for key, scale, unit in [("trainable_parameters", 1e6, "Million parameters"),
                             ("training_seconds", 3600, "Training hours"),
                             ("peak_gpu_bytes", 2**30, "Peak allocated GPU GiB"),
                             ("last_checkpoint_bytes", 2**30, "Recovery checkpoint GiB")]:
        chart(folder / f"{key}.svg", key.replace("_", " ").capitalize(), {
            key: [(i, row[key] / scale) for i, row in enumerate(resources)]
        }, "Training method", unit, [r["method"] for r in resources])

    weights = [row for p in sorted((root / "evaluations").glob("*/weights.csv")) for row in csv_rows(p)]
    acts = [row for p in sorted((root / "evaluations").glob("*/activations.csv")) for row in csv_rows(p)]
    save_table(folder / "weight_diagnostics.csv", weights)
    save_table(folder / "activation_diagnostics.csv", acts)
    conditions = sorted({f'{r["method"]}_{int(r["update"]):04d}' for r in weights})
    modules = sorted({r["module"] for r in weights})
    for key in ("rho", "eta"):
        chart(folder / f"{key}.svg", {"rho": "Protected output-subspace interference", "eta": "Relative update magnitude"}[key], {
            module: [(conditions.index(f'{r["method"]}_{int(r["update"]):04d}'), r[key])
                     for r in weights if r["module"] == module and r[key] != ""] for module in modules
        }, "Checkpoint", key, conditions)
    means = []
    for condition in conditions:
        for module in modules:
            for domain in ("math", "non_math"):
                values = [float(r["R"]) for r in acts if r["module"] == module and r["domain"] == domain
                          and f'{r["method"]}_{int(r["update"]):04d}' == condition]
                if values:
                    means.append({"condition": condition, "module": module, "domain": domain,
                                  "mean_R": sum(values) / len(values), "n": len(values)})
    save_table(folder / "activation_means.csv", means)
    for module in modules:
        chart(folder / (module + "_activation.svg"), "Local correction: " + module, {
            domain: [(conditions.index(r["condition"]), r["mean_R"]) for r in means
                     if r["module"] == module and r["domain"] == domain] for domain in ("math", "non_math")
        }, "Checkpoint", "Mean R(z)", conditions)

    qualitative = [r for p in sorted((root / "evaluations").glob("*/qualitative.jsonl")) for r in read_jsonl(p)]
    if qualitative:
        from .common import write_jsonl
        qualitative.sort(key=lambda r: (str(r["question_id"]), r["format"], r["condition"]))
        write_jsonl(folder / "qualitative_grouped.jsonl", qualitative)
        annotation_rows = [{"question_id": r["question_id"], "format": r["format"], "condition": r["condition"],
                            "prompt": r["prompt"], "response": r["response"], "truncated": r["truncated"],
                            "format_compliance": "", "coherence_relevance": "", "repetition": "",
                            "unnecessary_math": "", "inappropriate_content": "", "excerpt_and_notes": ""}
                           for r in qualitative if r["annotate"]]
        # Preserve your manual annotations on refresh. Rebuild only the separate source template.
        save_table(folder / "annotation_template.csv", annotation_rows)
        grouped = []
        for r in qualitative:
            grouped.append(f'Question {r["question_id"]} | {r["format"]} | {r["condition"]}\n'
                           f'PROMPT: {r["prompt"]}\nRESPONSE: {r["response"]}\nTRUNCATED: {r["truncated"]}\n')
        (folder / "responses_by_question.txt").write_text("\n".join(grouped), encoding="utf-8")
    write_json(folder / "status.json", {
        "completed_benchmark_conditions": len(records), "expected_conditions": 7,
        "saved_qualitative_responses": len(qualitative), "expected_responses": 168,
        "annotation_template_rows": sum(r["annotate"] for r in qualitative), "expected_annotation_rows": 42,
        "manual_work": "Copy annotation_template.csv to annotations.csv; annotate and interpret results yourself.",
    })
    # A simple local evidence index, updated as measurements arrive.
    links = "\n".join(f'<li><a href="{p.name}">{html.escape(p.name)}</a></li>'
                      for p in sorted(folder.iterdir()) if p.suffix in {".svg", ".csv", ".json", ".txt", ".jsonl"})
    (folder / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>PA3 Task 1 evidence</title>'
        '<style>body{font:16px system-ui;max-width:960px;margin:40px auto;line-height:1.6}</style>'
        f'<h1>{prefix}PA3 Task 1 evidence</h1><p>Only measured results appear. Refreshed after logging/checkpoints.</p><ul>{links}</ul>',
        encoding="utf-8")
