"""Visible, persistent progress. Heartbeats indicate liveness, not completed work."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

from .common import write_json


class LiveProgress:
    def __init__(self, root, stage, condition="shared", heartbeat_seconds=15):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.interval = heartbeat_seconds
        self.phase_started = time.monotonic()
        self.state = {"stage": stage, "condition": condition, "phase": "starting",
                      "state": "running", "completed": 0, "total": None, "unit": "items"}
        self.last_advance = time.monotonic()

    def __enter__(self):
        self.emit("START")
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def _heartbeat(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.emit("HEARTBEAT")
            except OSError as error:
                # Do not silently lose the monitoring thread to a transient I/O error.
                print(f"[MONITOR WARNING] Could not update progress files: {error}; retrying next heartbeat", flush=True)

    def phase(self, name, total=None, unit="items"):
        with self.lock:
            self.phase_started = self.last_advance = time.monotonic()
            # Remove per-phase details so an old question is not shown during loading.
            self.state = {k: self.state[k] for k in ("stage", "condition", "state")}
            self.state.update(phase=name, total=total, completed=0, unit=unit)
            self.emit("PHASE")

    def detail(self, **values):
        # Cheap in-memory update; safe to call after every generation forward step.
        with self.lock:
            self.state.update(values)
            self.last_advance = time.monotonic()

    def advance(self, completed, **values):
        with self.lock:
            self.state.update(completed=completed, **values)
            self.last_advance = time.monotonic()
            self.emit("PROGRESS")

    def emit(self, event):
        with self.lock:
            now = time.monotonic()
            snapshot = {**self.state, "event": event,
                        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "phase_elapsed_seconds": round(now-self.phase_started, 1),
                        "seconds_since_measured_activity": round(now-self.last_advance, 1)}
            write_json(self.root / "progress.json", snapshot)
            count = "" if snapshot["total"] is None else f" {snapshot['completed']}/{snapshot['total']} {snapshot['unit']}"
            detail = ""
            if "current_doc_id" in snapshot:
                detail += f" | question ID {snapshot['current_doc_id']}"
            if "current_generation_steps" in snapshot:
                label = "current batch" if len(snapshot.get("current_doc_ids", [])) > 1 else "current answer"
                detail += f" | {label}: {snapshot['current_generation_steps']} decode steps"
            if snapshot.get("remaining_seconds_estimate") is not None:
                detail += f" | approx phase remaining {snapshot['remaining_seconds_estimate']/60:.1f} min (measured estimate)"
            line = (f"[{event}] {snapshot['condition']} | {snapshot['phase']}{count}"
                    f" | elapsed {snapshot['phase_elapsed_seconds']:.0f}s{detail}")
            if event == "HEARTBEAT":
                line += f" | activity age {snapshot['seconds_since_measured_activity']:.0f}s (heartbeat is NOT proof of progress)"
            (self.root / "progress.txt").write_text(line + "\n", encoding="utf-8")
            print(line, flush=True)
            with (self.root / "progress_events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(snapshot) + "\n")

    def __exit__(self, exc_type, exc, traceback):
        self.stop_event.set()
        self.thread.join(timeout=2)
        with self.lock:
            self.state["state"] = "failed" if exc_type else "completed"
            if exc:
                self.state["error"] = str(exc)
            self.emit("FAILED" if exc_type else "DONE")


def show_status(root):
    root = Path(root)
    pipeline = root / "pipeline_status.json"
    if pipeline.exists():
        pipeline_state = json.loads(pipeline.read_text(encoding="utf-8"))
        print(f"PIPELINE: {pipeline_state.get('state', '?').upper()} | stage: {pipeline_state.get('stage', '?')} | method: {pipeline_state.get('method', 'shared')}")
        if pipeline_state.get("message"):
            print(pipeline_state["message"])
    current = root / "progress.json"
    if not current.exists():
        print("No worker progress recorded yet.")
        return
    state = json.loads(current.read_text(encoding="utf-8"))
    stamp = datetime.fromisoformat(state["updated_at_utc"])
    age = (datetime.now(timezone.utc)-stamp).total_seconds()
    print(f"MODEL: {state['condition']} | WORKER: {state['state'].upper()}")
    print("NOW:", state["phase"])
    if state.get("total") is not None:
        print(f"COMPLETED: {state['completed']}/{state['total']} {state['unit']}")
    if len(state.get("current_doc_ids", [])) > 1:
        print(f"CURRENT BATCH: {state['current_doc_ids']} | batch decode steps: {state.get('current_generation_steps', 0)}")
    elif "current_doc_id" in state:
        print(f"CURRENT QUESTION: {state['current_doc_id']} | decode steps: {state.get('current_generation_steps', 0)}")
    if state.get("batch_size"):
        print(f"EVALUATION BATCH SIZE: {state['batch_size']}")
    if state.get("remaining_seconds_estimate") is not None:
        print(f"ESTIMATED REMAINING IN THIS PHASE: {state['remaining_seconds_estimate']/60:.1f} min (measured estimate, not whole-run ETA)")
    if "sft_loss" in state:
        print(f"SFT LOSS: {state['sft_loss']:.4f} | SECONDS/UPDATE: {state['seconds_per_update']:.2f}")
    print(f"PHASE ELAPSED: {state['phase_elapsed_seconds']:.0f}s | SNAPSHOT AGE: {age:.0f}s")
    print(f"ACTIVITY AGE AT SNAPSHOT: {state['seconds_since_measured_activity']:.0f}s")
    if state.get("error"):
        print("ERROR:", state["error"])
    print("Status files:", root / "progress.txt", "and progress.json")
    if age > 45 and state["state"] == "running":
        print("WARNING: no recent heartbeat; the process may be stopped, failed, or blocked.")
