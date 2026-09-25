"""Standard non-adaptive SAM with a single AdamW update per source batch."""
import math
from pathlib import Path

import torch
from torch import nn

from .pacs import CLASSES, split_hash
from .source_erm import CONFIG, train_pacs, training_mode


def sam_step(model, optimizer, x, y, rho=0.05):
    """Use the same augmented batch twice; restore weights before AdamW.step()."""
    if not math.isfinite(rho) or rho < 0:
        raise ValueError('rho must be finite and nonnegative.')
    training_mode(model)
    optimizer.zero_grad(set_to_none=True)
    logits = model(x)
    loss = nn.functional.cross_entropy(logits, y)
    if not torch.isfinite(loss):
        raise RuntimeError('Non-finite SAM first-pass loss.')
    loss.backward()
    parameters = [p for p in model.parameters() if p.grad is not None]
    norm = torch.stack([p.grad.detach().norm(2) for p in parameters]).norm(2)
    if not torch.isfinite(norm):
        raise RuntimeError('Non-finite SAM gradient norm.')
    originals = []
    try:
        with torch.no_grad():
            scale = rho / norm.clamp_min(1e-12)
            for parameter in parameters:
                originals.append((parameter, parameter.detach().clone()))
                parameter.add_(parameter.grad * scale)
        optimizer.zero_grad(set_to_none=True)
        training_mode(model)  # Freeze running statistics on both passes.
        perturbed_loss = nn.functional.cross_entropy(model(x), y)
        if not torch.isfinite(perturbed_loss):
            raise RuntimeError('Non-finite SAM perturbed loss.')
        perturbed_loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
            raise RuntimeError('Non-finite SAM second-pass gradient.')
    finally:
        # Copy originals exactly, avoiding roundoff from subtracting epsilon.
        with torch.no_grad():
            for parameter, original in originals:
                parameter.copy_(original)
    optimizer.step()  # AdamW uses perturbed gradients at original parameters.
    return logits.detach(), loss.detach(), perturbed_loss.detach()


def train_sam(data_root, split_path, output_dir, baseline_checkpoint, rho=0.05):
    if not math.isfinite(rho) or rho < 0:
        raise ValueError('rho must be finite and nonnegative.')
    if not Path(split_path).is_file():
        raise FileNotFoundError('Task 3 requires the existing Task 2 source split.')
    baseline = torch.load(baseline_checkpoint, map_location='cpu', weights_only=True)
    if baseline.get('method', 'source_only') != 'source_only':
        raise ValueError('Expected the source-only ERM baseline.')
    if baseline['split_sha256'] != split_hash(split_path):
        raise ValueError('Baseline and current source split differ.')
    if baseline['class_to_idx'] != {name: i for i, name in enumerate(CLASSES)}:
        raise ValueError('Baseline class mapping differs from the shared protocol.')
    cfg = dict(baseline['config'])
    if any(cfg.get(key) != value for key, value in CONFIG.items()):
        raise ValueError('Baseline configuration differs from the shared protocol.')
    cfg.update(rho=float(rho), adaptive=False, base_optimizer='AdamW',
               sam_batch='same augmented source batch for both passes',
               sam_norm='global L2 over all trainable parameters with gradients')
    del baseline  # Only metadata is reused; initialization remains ImageNet V1.
    return train_pacs(data_root, split_path, output_dir, cfg, method='sam')
