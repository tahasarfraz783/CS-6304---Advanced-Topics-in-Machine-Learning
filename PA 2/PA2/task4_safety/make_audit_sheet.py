from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from common.data import load_yaml, read_jsonl, repo_path


def fixed_audit_ids(base_rows, per_class: int, seed: int):
    rng = np.random.default_rng(seed)
    meta = pd.DataFrame(base_rows)
    if meta.xstest_id.duplicated().any():
        raise ValueError("Audit sampling requires unique prompt IDs")
    ids = []
    for label in ["SAFE", "UNSAFE"]:
        groups = [g.xstest_id.to_numpy() for _, g in meta[meta.benchmark_class == label].groupby("type", sort=True)]
        if sum(map(len, groups)) < per_class:
            raise ValueError(f"Not enough {label} rows for audit")
        pools = [list(rng.permutation(g)) for g in groups]
        selected = []
        while len(selected) < per_class:
            for pool in pools:
                if pool and len(selected) < per_class:
                    selected.append(int(pool.pop()))
        ids.extend(selected)
    return sorted(ids)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/feedback.yaml")
    args = ap.parse_args()
    cfg = load_yaml(args.config)
    outdir = repo_path(cfg["results_dir"]) / "task4_safety"
    src = outdir / "generated_sft.jsonl"
    if not src.exists():
        raise FileNotFoundError("Generate/save SFT responses first: " + str(src))
    ids = fixed_audit_ids(read_jsonl(src), int(cfg["manual_audit_per_class"]), int(cfg["seed"]))
    target = outdir / "manual_audit_ids.csv"
    if target.exists():
        ids = pd.read_csv(target).xstest_id.tolist()
    else:
        pd.DataFrame({"xstest_id": ids}).to_csv(target, index=False)
    for policy in ("sft", "dpo", "ppo", "grpo"):
        dest = outdir / f"manual_audit_{policy}.csv"
        if dest.exists():
            continue  # Never overwrite human work.
        rows = pd.DataFrame(read_jsonl(outdir / f"generated_{policy}.jsonl"))
        sheet = rows[rows.xstest_id.isin(ids)].copy()
        if len(sheet) != len(ids):
            raise ValueError("Incomplete audit responses: " + policy)
        sheet["manual_label"] = ""
        sheet["manual_notes"] = ""
        sheet.to_csv(dest, index=False)
    print("Created blind audit sheets; label all 60 prompts for each policy before viewing AI judgments.")


if __name__ == "__main__":
    main()
