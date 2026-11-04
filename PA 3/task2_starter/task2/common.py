import csv
import hashlib
import json
import os
import random
import threading
import time
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def jsonl(path, row):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def rows(path):
    path = Path(path)
    if not path.exists():
        return []
    # An interrupted final write may leave one partial line. Never discard earlier rows.
    result = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
    return result


def repair_jsonl(path):
    path = Path(path)
    if path.exists():
        valid = rows(path)
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in valid), encoding="utf-8")


def table(path, data):
    if not data:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in data for k in r)))
        w.writeheader()
        w.writerows(data)


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def seed_all(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class Progress:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.state = {"phase": "starting", "completed": 0, "total": 0, "status": "running"}
        self.started = time.time()
        self.phase_start = self.started
        self.last_work = self.started
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.thread.start()

    def emit(self, phase=None, completed=None, total=None, **extra):
        with self.lock:
            now = time.time()
            if phase is not None and phase != self.state["phase"]:
                self.phase_start = now
                self.state.update(phase=phase, completed=0, total=0)
            if completed is not None:
                self.state["completed"] = completed
                self.last_work = now
            if total is not None:
                self.state["total"] = total
            self.state.update(extra)
            n, t = self.state["completed"], self.state["total"]
            elapsed = now - self.phase_start
            self.state.update(timestamp=now, activity_age_seconds=now-self.last_work,
                              elapsed_seconds=now-self.started,
                              phase_eta_seconds=(elapsed*(t-n)/n if n >= 3 and t > n else None))
            write(self.root / "progress.json", self.state)
            line = f"[{self.state['status']}] {self.state['phase']} {n}/{t} | activity age {now-self.last_work:.0f}s"
            if self.state["phase_eta_seconds"] is not None:
                line += f" | phase ETA {self.state['phase_eta_seconds']/60:.1f} min"
            if extra:
                line += " | " + " ".join(f"{k}={v}" for k, v in extra.items())
            print(line, flush=True)
            jsonl(self.root / "progress_events.jsonl", dict(self.state))

    def heartbeat(self):
        while not self.stop.wait(15):
            self.emit(heartbeat=True)

    def close(self, status):
        self.stop.set()
        self.thread.join(timeout=1)
        self.emit(status=status)
