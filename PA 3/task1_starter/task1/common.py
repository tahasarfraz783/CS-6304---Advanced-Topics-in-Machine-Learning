"""Small file/config helpers. This module deliberately needs no ML libraries."""
import csv
import hashlib
import json
import os
import time
from pathlib import Path

METHODS = ["full_ft", "l2sp", "lora4", "lora16", "oplora16"]
TARGETS = {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Windows readers can briefly hold the destination open while monitoring.
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_config(c):
    if c["examples"] % (c["microbatch"] * c["accumulation"]):
        raise ValueError("Examples must form complete effective batches.")
    if c["methods"] != METHODS:
        raise ValueError("This assignment runner expects the five prescribed methods in order.")


def stages(c):
    total = c["examples"] // (c["microbatch"] * c["accumulation"])
    # Exact PA3 recovery updates; reduced smoke runs keep distinct valid stages.
    return sorted({max(1, int(total * q)) for q in (0.25, 0.5, 0.75, 1.0)})
