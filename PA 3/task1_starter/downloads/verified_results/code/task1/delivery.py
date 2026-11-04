"""Portable downloads: small evidence archive and a separate archive of inference models."""
import hashlib
from pathlib import Path
import shutil
import zipfile

from .common import METHODS, read_json, write_json


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package(root, source_root, progress=None):
    root, source_root = Path(root), Path(source_root)
    completion = root / "pipeline_complete.json"
    if (not completion.exists() or read_json(completion).get("smoke_only", True)
            or not read_json(completion).get("automated_stages_complete", False)):
        raise ValueError("Only a completed official run can be packaged as assignment results.")
    c = read_json(root / "resolved_config.json")
    total = c["examples"] // (c["microbatch"] * c["accumulation"])
    conditions = [f"full_ft_{total//2:04d}"] + [f"{m}_{total:04d}" for m in METHODS]
    for condition in conditions:
        model = root / "models" / condition
        if not (model / "export_complete.json").exists():
            raise ValueError(f"Missing portable model {condition}; finish evaluation/export first.")
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    evidence = []
    allowed = {".json", ".jsonl", ".csv", ".svg", ".html", ".txt", ".yaml", ".yml", ".md", ".log"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if parts[0] in {"prepared", "models", "downloads"} or "checkpoints" in parts:
            continue
        if path.suffix in allowed:
            evidence.append((path, "results/" + path.relative_to(root).as_posix()))
    # Include provenance from preparation, not raw datasets or the starting weights.
    for name in ("manifest.json", "probes.jsonl", "diagnostics_ready.json"):
        p = root / "prepared" / name
        if p.exists():
            evidence.append((p, "results/prepared/" + name))
    for path in source_root.rglob("*"):
        if path.is_file() and not set(path.relative_to(source_root).parts) & {"outputs", ".venv", ".verification", "__pycache__", ".git"}:
            if path.suffix in {".py", ".md", ".json", ".txt", ".yaml", ".yml"}:
                evidence.append((path, "code/" + path.relative_to(source_root).as_posix()))
    model_files = [(p, "models/" + p.relative_to(root / "models").as_posix())
                   for condition in conditions for p in (root / "models" / condition).rglob("*") if p.is_file()]
    needed = sum(p.stat().st_size for p, _ in evidence + model_files)
    if shutil.disk_usage(root).free < needed + 2 * 1024**3:
        raise RuntimeError("Not enough free disk for download archives. Existing results/models are safe; download their folders directly.")
    metadata = []
    for filename, items, compression in [("task1_results.zip", evidence, zipfile.ZIP_DEFLATED),
                                         ("task1_models.zip", model_files, zipfile.ZIP_STORED)]:
        destination = downloads / filename
        if progress:
            progress.phase(f"building {filename}", len(items), "files")
        temporary = destination.with_suffix(".partial")
        with zipfile.ZipFile(temporary, "w", compression=compression, allowZip64=True) as archive:
            for index, (path, archive_name) in enumerate(items, 1):
                archive.write(path, archive_name)
                if progress:
                    progress.advance(index, file=archive_name)
        temporary.replace(destination)
        # Verify each archive before calling the export ready to download.
        if progress:
            progress.phase(f"checking archive integrity and SHA256: {filename}")
        with zipfile.ZipFile(destination) as archive:
            bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Archive verification failed: {bad}")
        metadata.append({"file": filename, "bytes": destination.stat().st_size,
                         "sha256": sha256(destination)})
    write_json(downloads / "SHA256.json", metadata)
    write_json(downloads / "README.json", {
        "models": conditions, "format": "Hugging Face standalone FP16 inference models + tokenizers",
        "included": "Measured results, per-example outputs, plots, provenance, code, and six inference model conditions",
        "not_included": "Recovery optimizer checkpoints, raw training data, or the original downloaded backbone cache",
        "manual_work": "Complete your 42 annotations and write your own analysis/report after download.",
        "before_destroy": "Download both ZIPs and SHA256.json; verify local hashes and extraction. Download recovery checkpoints separately if desired.",
    })
    print("Download files are ready in", downloads)


def cleanup_test_outputs(source_root):
    """Explicit opt-in cleanup; never deletes the official assignment folder."""
    source_root = Path(source_root).resolve()
    for name, examples in (("smoke", 128), ("timing", 640)):
        target = source_root / "outputs" / name
        if not target.exists():
            continue
        # Refuse redirected paths and unknown directories before recursive removal.
        if target.resolve() != target.absolute() or target.is_symlink():
            raise ValueError(f"Refusing redirected cleanup path: {target}")
        marker = target / "resolved_config.json"
        if not marker.exists() or read_json(marker).get("examples") != examples:
            raise ValueError(f"Refusing cleanup without expected test-run configuration: {target}")
        print("Removing disposable test output:", target)
        shutil.rmtree(target)
