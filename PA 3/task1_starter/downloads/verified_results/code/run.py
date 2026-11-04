"""One entry point. Start with `python run.py --mode plan` (no ML install needed)."""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import hashlib
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

from task1.common import METHODS, fingerprint, read_json, stages, validate_config, write_json

HERE = Path(__file__).resolve().parent
ACTIVE_ROOT = None
IS_WORKER = False


def configuration(args):
    c = read_json(HERE / args.config)
    c["qualitative_file"] = str((HERE / c["qualitative_file"]).resolve())
    if args.mode == "smoke":
        c.update(examples=128, warmup_updates=1, plot_every=1, output="outputs/smoke")
    elif args.mode == "timing":
        c.update(examples=640, plot_every=5, output="outputs/timing")
    c["output"] = str((HERE / (args.output or c["output"])).resolve())
    validate_config(c)
    return c


def show_plan(c):
    updates = c["examples"] // (c["microbatch"] * c["accumulation"])
    print(f"Model: {c['model']} | seed {c['seed']} | thinking disabled")
    print(f"Each run: {c['examples']:,} examples, one epoch, {updates:,} update attempts")
    print(f"Effective batch: {c['microbatch']} x {c['accumulation']} = {c['microbatch'] * c['accumulation']}")
    print("Methods:", ", ".join(c["methods"]))
    print("Recovery updates:", stages(c))
    print(f"Evaluations: baseline; Full FT at {updates//2}; all five at {updates}.")
    print("Logs update every step; plots refresh every", c["plot_every"], "steps and at evaluation stages.")
    print("Outputs:", c["output"])
    print("Qualitative source:", c["qualitative_file"])
    print("Course YAML and normalized qualitative.json are included; python prepare_prompts.py regenerates/validates them.")


def check(c, require_prompts=True):
    packages = {"torch": "torch", "transformers": "transformers", "datasets": "datasets",
                "lm_eval": "lm_eval", "numpy": "numpy", "yaml": "PyYAML", "accelerate": "accelerate"}
    missing = []
    versions = {}
    for module, package in packages.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)
        else:
            versions[package] = importlib.metadata.version(package)
    if missing:
        raise RuntimeError("Install ML dependencies first. Missing: " + ", ".join(missing))
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA-enabled PyTorch and an NVIDIA GPU are required for the prescribed FP16 run.")
    free, total = torch.cuda.mem_get_info()
    print(f"GPU: {torch.cuda.get_device_name()} | free {free/2**30:.1f}/{total/2**30:.1f} GiB")
    if total < 12 * 2**30:
        print("WARNING: Full FT is expected to exceed this GPU's memory. Use a larger GPU for all five runs.")
    if require_prompts:
        from task1.data import qualitative_inputs
        qualitative_inputs(c)
    return {"versions": versions, "python": sys.version, "gpu": torch.cuda.get_device_name(),
            "gpu_total_bytes": total, "cuda": torch.version.cuda, "platform": sys.platform}


def worker(c, args):
    from task1.progress import LiveProgress
    condition = f"{args.method}_{args.stop or 0:04d}" if args.worker in {"train", "evaluate", "diagnose", "verify_evaluation"} else "shared"
    with LiveProgress(c["output"], args.worker, condition) as progress:
        worker_body(c, args, progress)


def worker_body(c, args, progress):
    if args.worker == "prepare":
        from task1.data import prepare
        prepare(c, c["output"], progress=progress)
    elif args.worker == "prepare_diagnostics":
        from task1.diagnostics import prepare_diagnostics
        prepare_diagnostics(c, c["output"], progress=progress)
    elif args.worker == "train":
        from task1.training import train
        train(c, c["output"], args.method, args.stop, progress=progress)
    elif args.worker == "evaluate":
        from task1.evaluation import evaluate
        evaluate(c, c["output"], args.method, args.stop, smoke=args.smoke_worker, progress=progress)
    elif args.worker == "diagnose":
        from task1.diagnostics import measure
        cp = Path(c["output"]) / "runs" / args.method / "checkpoints" / f"update_{args.stop:04d}.pt"
        measure(c, c["output"], args.method, args.stop, cp, progress=progress)
    elif args.worker == "verify_evaluation":
        from task1.evaluation import verify_evaluation
        verify_evaluation(c, c["output"], progress)


def launch(c, name, method=None, stop=None, smoke=False):
    root = Path(c["output"])
    log = root / "logs" / f"{name}_{method or 'shared'}_{stop or 0:04d}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", str(HERE / "run.py"), "--worker", name,
               "--config", str(root / "resolved_config.json")]
    if method:
        command += ["--method", method]
    if stop is not None:
        command += ["--stop", str(stop)]
    if smoke:
        command += ["--smoke-worker"]
    print(f"\n>>> {name} {method or ''} {stop or ''}", flush=True)
    # Workers exit between training and evaluation, releasing weights AND Adam GPU states.
    before = time.perf_counter()
    with log.open("a", encoding="utf-8") as f:
        with subprocess.Popen(command, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"}) as process:
            write_json(root / "pipeline_status.json", {
                "state": "running", "stage": name, "method": method or "shared",
                "update": stop or 0, "worker_pid": process.pid, "launcher_pid": os.getpid(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "log": str(log),
            })
            for line in process.stdout:
                print(line, end="", flush=True)
                f.write(line)
                f.flush()
            code = process.wait()
    from task1.common import append_csv
    append_csv(root / "stage_times.csv", {"stage": name, "method": method or "shared",
                                         "update": stop or 0, "seconds": time.perf_counter()-before,
                                         "exit_code": code})
    if code:
        write_json(root / "pipeline_status.json", {"state": "failed", "stage": name,
                   "method": method, "exit_code": code, "log": str(log)})
        raise RuntimeError(f"Stage failed. Results already saved remain available. Inspect {log}")


def main():
    global ACTIVE_ROOT, IS_WORKER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "check", "prepare", "timing", "smoke", "run", "plots", "package", "cleanup-tests", "status", "verify-eval"], default="plan")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", help="Separate output folder; never mix smoke and assignment results")
    parser.add_argument("--method", choices=METHODS + ["baseline"], default="full_ft")
    parser.add_argument("--worker", choices=["prepare", "prepare_diagnostics", "train", "evaluate", "diagnose", "verify_evaluation"], help=argparse.SUPPRESS)
    parser.add_argument("--stop", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.chdir(HERE)
    c = configuration(args)
    ACTIVE_ROOT, IS_WORKER = Path(c["output"]), bool(args.worker)
    if args.worker:
        worker(c, args)
        return
    if args.mode == "plan":
        show_plan(c)
        return
    if args.mode == "status":
        from task1.progress import show_status
        show_status(c["output"])
        return
    if args.mode == "plots":
        from task1.plots import refresh
        refresh(c["output"])
        return
    if args.mode == "package":
        from task1.delivery import package
        from task1.progress import LiveProgress
        with LiveProgress(c["output"], "package", "downloads") as progress:
            package(c["output"], HERE, progress=progress)
        return
    if args.mode == "cleanup-tests":
        from task1.delivery import cleanup_test_outputs
        cleanup_test_outputs(HERE)
        return
    if args.mode == "run":
        for name in ("smoke", "timing"):
            if any((HERE / "outputs" / name).glob("runs/*/checkpoints/*.pt")):
                raise RuntimeError("Disposable smoke/timing checkpoints still occupy disk. Save any test logs you want, then run: python run.py --mode cleanup-tests")
    environment = check(c, require_prompts=args.mode in ("check", "run", "smoke"))
    if args.mode == "check":
        print(json.dumps(environment, indent=2))
        return
    root = Path(c["output"])
    if args.mode == "verify-eval":
        if not (root / "resolved_config.json").exists() or not (root / "prepared/base/config.json").exists():
            raise RuntimeError("Preflight uses an existing prepared model. Run prepare first, or reuse the original official output folder.")
        launch(c, "verify_evaluation", "baseline", 0)
        return
    print("TASK 1 RUNNER v3: batched evaluation + live progress + answer/checkpoint recovery", flush=True)
    print("Monitor: python monitor.py | Snapshot: python run.py --mode status", flush=True)
    resolved = root / "resolved_config.json"
    if resolved.exists() and fingerprint(read_json(resolved)) != fingerprint(c):
        raise ValueError("Output folder has a different config. Choose --output with a new directory.")
    write_json(resolved, c)
    write_json(root / "environment.json", environment)
    if args.mode in ("run", "smoke"):
        source = Path(c["qualitative_file"])
        normalized = source.with_name("qualitative.json")
        prompt_folder = root / "inputs"
        prompt_folder.mkdir(parents=True, exist_ok=True)
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, normalized)}
        previous = prompt_folder / "hashes.json"
        if previous.exists() and read_json(previous) != hashes:
            raise ValueError("Qualitative prompts changed during this experiment. Use a new output folder.")
        for p in (source, normalized):
            shutil.copy2(p, prompt_folder / p.name)
        write_json(previous, hashes)
    launch(c, "prepare")
    if args.mode == "prepare":
        return
    if args.mode == "run":
        launch(c, "verify_evaluation", "baseline", 0)
    if args.mode == "timing":
        if args.method == "baseline":
            raise ValueError("Timing mode measures a training method, not baseline.")
        if args.method == "oplora16":
            launch(c, "prepare_diagnostics")
        launch(c, "train", args.method, 20)
        from task1.plots import csv_rows
        rows = csv_rows(root / "runs" / args.method / "training.csv")[5:]
        seconds = sum(float(row["seconds"]) for row in rows) / len(rows)
        result = {"method": args.method, "measured_updates_after_warmup_overhead": len(rows),
                  "mean_seconds_per_update": seconds,
                  "estimated_one_method_training_hours": seconds * 1250 / 3600,
                  "excludes": "Evaluation, SVD, loading, checkpoints; later example lengths can differ."}
        write_json(root / "timing_estimate.json", result)
        print(json.dumps(result, indent=2))
        return

    launch(c, "prepare_diagnostics")
    smoke = args.mode == "smoke"
    launch(c, "evaluate", "baseline", 0, smoke)
    total = c["examples"] // (c["microbatch"] * c["accumulation"])
    for method in c["methods"]:
        stops = [total // 2, total] if method == "full_ft" else [total]
        for stop in stops:
            launch(c, "train", method, stop)
            launch(c, "diagnose", method, stop)
            launch(c, "evaluate", method, stop, smoke)
            from task1.plots import refresh
            refresh(root)
    audit(root, total, smoke)
    if not smoke:
        from task1.delivery import package
        from task1.progress import LiveProgress
        write_json(root / "pipeline_status.json", {"state": "running", "stage": "package", "launcher_pid": os.getpid()})
        with LiveProgress(root, "package", "downloads") as progress:
            package(root, HERE, progress=progress)
    write_json(root / "pipeline_status.json", {
        "state": "completed", "smoke_only": smoke,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "message": "Automated work finished. CLOUD BILLING DOES NOT STOP AUTOMATICALLY.",
        "downloads": str(root / "downloads"),
    })
    print("Finished. Open", root / "evidence/index.html")
    print("CLOUD BILLING IS STILL RUNNING: download/verify your files, then stop the instance.", flush=True)


def audit(root, total, smoke):
    """A run is complete only if every required evaluation artifact is present."""
    from task1.common import read_jsonl
    from task1.plots import refresh
    expected = [("baseline", 0), ("full_ft", total // 2)] + [(m, total) for m in METHODS]
    for method, update in expected:
        folder = root / "evaluations" / f"{method}_{update:04d}"
        if not (folder / "complete.json").exists():
            raise RuntimeError(f"Missing evaluation: {folder}")
        if len(read_jsonl(folder / "qualitative.jsonl")) != 24:
            raise RuntimeError(f"Missing qualitative responses: {folder}")
        if method != "baseline" and not (folder / "diagnostics_done.json").exists():
            raise RuntimeError(f"Missing diagnostics: {folder}")
    refresh(root)
    write_json(root / "pipeline_complete.json", {
        "automated_stages_complete": True, "smoke_only": smoke,
        "manual_annotation_and_analysis_complete": False,
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        if ACTIVE_ROOT is not None and not IS_WORKER:
            try:
                previous = read_json(ACTIVE_ROOT / "pipeline_status.json") if (ACTIVE_ROOT / "pipeline_status.json").exists() else {}
                write_json(ACTIVE_ROOT / "pipeline_status.json", {
                    **previous, "state": "failed", "error": str(error),
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                })
            except OSError:
                pass  # Preserve the original error when the output disk itself failed.
        print(f"\nSTOPPED: {error}", file=sys.stderr)
        sys.exit(1)
