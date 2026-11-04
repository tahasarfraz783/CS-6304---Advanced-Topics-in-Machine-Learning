"""Local measurements: update direction, size, and response to fixed base activations."""
import time
from pathlib import Path

import torch

from .common import append_csv, read_jsonl, write_json
from .model import basis_path, load_base, load_tokenizer, weight_modules


def selected_names(c):
    return [f"model.layers.{layer}.mlp.down_proj" for layer in c["probe_layers"]]


def prepare_diagnostics(c, root, progress=None):
    root = Path(root)
    folder = root / "prepared"
    if (folder / "diagnostics_ready.json").exists():
        if progress:
            progress.phase("reusing prepared FP32 bases and base activations")
        return
    before = time.perf_counter()
    if progress:
        progress.phase("loading FP32 starting model for diagnostics")
    model = load_base(c, root, dtype=torch.float32)
    basis_bytes = 0
    modules = weight_modules(model)
    if progress:
        progress.phase("preparing/reusing FP32 singular bases", len(modules), "matrices")
    for index, (name, module) in enumerate(modules, 1):
        path = basis_path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Exact FP32 SVD, computed once. Can take time; never use a dense projector.
            U, _, Vh = torch.linalg.svd(module.weight.detach().float(), full_matrices=False)
            k = c["protection_rank"]
            torch.save({"U": U[:, :k].contiguous().cpu(),
                        "V": Vh[:k].T.contiguous().cpu()}, path)
            del U, Vh
        basis_bytes += path.stat().st_size
        if progress:
            progress.advance(index, module=name)
    base_weights = {n: model.get_submodule(n).weight.detach().float().cpu().clone()
                    for n in selected_names(c)}
    torch.save(base_weights, folder / "diagnostic_weights.pt")
    svd_seconds = time.perf_counter() - before
    # The assignment requests FP32 diagnostics, including the forward pass that
    # produces z. Casting an FP16 activation afterward does not recover FP32 values.
    model.eval()
    tokenizer = load_tokenizer(root)
    captured = {}
    hooks = []
    for name in selected_names(c):
        def hook(module, inputs, name=name):
            # One unpadded prompt at a time: -1 is its last non-padding prompt token.
            captured[name] = inputs[0][0, -1].detach().float().cpu()
        hooks.append(model.get_submodule(name).register_forward_pre_hook(hook))
    probes = read_jsonl(folder / "probes.jsonl")
    cache = []
    if progress:
        progress.phase("caching FP32 base activations", len(probes), "prompts")
    with torch.inference_mode():
        for index, row in enumerate(probes, 1):
            inputs = tokenizer(row["prompt"], return_tensors="pt", add_special_tokens=False).to("cuda")
            model(**inputs, use_cache=False, logits_to_keep=1)
            cache.append({**row, "z": dict(captured)})
            if progress:
                progress.advance(index)
    for handle in hooks:
        handle.remove()
    torch.save(cache, folder / "activations.pt")
    write_json(folder / "diagnostics_ready.json", {
        "basis_preprocessing_seconds": svd_seconds, "basis_storage_bytes_all_targets": basis_bytes,
        "probe_count": len(probes), "precision": "FP32 SVD, starting weights, probe forward, cached z, and local measurements",
    })


def measure(c, root, method, update, checkpoint, progress=None):
    root = Path(root)
    destination = root / "evaluations" / f"{method}_{update:04d}"
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "diagnostics_done.json").exists():
        if progress:
            progress.phase("reusing completed checkpoint diagnostics")
        return
    # Rebuild CSVs on retry, so a partial failure cannot duplicate rows.
    for name in ("weights.csv", "activations.csv"):
        path = destination / name
        if path.exists():
            path.unlink()
    originals = torch.load(root / "prepared/diagnostic_weights.pt", weights_only=True)
    probes = torch.load(root / "prepared/activations.pt", weights_only=True)
    adapter = method.startswith("lora") or method == "oplora16"
    if adapter:
        state = torch.load(root / "runs" / method / f"adapters_{update:04d}.pt", weights_only=True)
    else:
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)["model"]
    if progress:
        progress.phase("weight-space and activation diagnostics", len(selected_names(c)), "layers")
    for index, name in enumerate(selected_names(c), 1):
        W0 = originals[name].float()
        if adapter:
            item = state[name]
            delta = item["scale"] * item["B"].float() @ item["A"].float()
        else:
            delta = state[name + ".weight"].float() - W0
        bases = torch.load(basis_path(root, name), weights_only=True)
        U, V = bases["U"], bases["V"]
        norm = delta.norm()
        append_csv(destination / "weights.csv", {
            "method": method, "update": update, "module": name,
            # Undefined for a zero update, rather than a misleading rho=0.
            "rho": ((U.T @ delta).square().sum() / norm.square()).item() if norm > 0 else "",
            "eta": (norm / W0.norm()).item(),
            "input_constraint_relative": ((delta @ V).norm() / norm).item() if norm > 0 else "",
            "output_constraint_relative": ((U.T @ delta).norm() / norm).item() if norm > 0 else "",
        })
        for row in probes:
            z = row["z"][name].float()
            ratio = ((delta @ z).norm() / ((W0 @ z).norm() + 1e-8)).item()
            append_csv(destination / "activations.csv", {
                "method": method, "update": update, "module": name,
                "domain": row["domain"], "task": row["task"], "doc_id": row["doc_id"], "R": ratio,
            })
        if progress:
            progress.advance(index, module=name)
    write_json(destination / "diagnostics_done.json", {"complete": True})
