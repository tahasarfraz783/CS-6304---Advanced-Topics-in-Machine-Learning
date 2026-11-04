"""LoRA written out explicitly so A, B, projections, and merging are visible."""
import math
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers import AutoModelForCausalLM, AutoTokenizer

from .common import TARGETS


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_base(c, root, dtype=torch.float16, device="cuda"):
    # Preparation freezes the exact downloaded model in a local snapshot.
    return AutoModelForCausalLM.from_pretrained(
        Path(root) / "prepared/base", torch_dtype=dtype,
        attn_implementation="sdpa",
    ).to(device)


def load_tokenizer(root):
    tokenizer = AutoTokenizer.from_pretrained(Path(root) / "prepared/base")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def weight_modules(model):
    return [(name, module) for name, module in model.named_modules()
            if isinstance(module, nn.Linear) and name.split(".")[-1] in TARGETS]


def basis_path(root, name):
    return Path(root) / "prepared/bases" / (name + ".pt")


class LowRankLinear(nn.Module):
    def __init__(self, base, rank, alpha, dropout, bases=None):
        super().__init__()
        self.base = base
        self.base.requires_grad_(False)
        self.scale = alpha / rank
        self.dropout = nn.Dropout(dropout)
        # FP32 trainable parameters; autocast handles FP16 matrix multiplications.
        self.A = nn.Parameter(torch.empty(rank, base.in_features, device=base.weight.device, dtype=torch.float32))
        self.B = nn.Parameter(torch.zeros(base.out_features, rank, device=base.weight.device, dtype=torch.float32))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))
        self.register_buffer("U", None if bases is None else bases["U"].to(base.weight.device))
        self.register_buffer("V", None if bases is None else bases["V"].to(base.weight.device))

    def factors(self):
        # Orthogonal projection is evaluated in FP32, without dense I-UU^T matrices.
        with torch.autocast("cuda", enabled=False):
            A, B = self.A, self.B
            if self.U is not None:
                B = B - self.U @ (self.U.T @ B)
                A = A - (A @ self.V) @ self.V.T
        return A, B

    def forward(self, x):
        A, B = self.factors()
        correction = nn.functional.linear(nn.functional.linear(self.dropout(x), A), B)
        return self.base(x) + (self.scale * correction).to(x.dtype)


def attach_adapters(model, method, c, root):
    model.requires_grad_(False)
    rank = 4 if method == "lora4" else 16
    for name, base in weight_modules(model):
        bases = torch.load(basis_path(root, name), weights_only=True) if method == "oplora16" else None
        parent_name, child = name.rsplit(".", 1)
        parent = model.get_submodule(parent_name)
        setattr(parent, child, LowRankLinear(base, rank, 2 * rank, c["adapter_dropout"], bases))
    # Needed for gradient checkpointing when the embedding weights are frozen.
    model.enable_input_require_grads()
    return model


def trainable_state(model):
    return {name: p.detach().cpu().clone() for name, p in model.named_parameters() if p.requires_grad}


def restore_trainable(model, state):
    with torch.no_grad():
        parameters = dict(model.named_parameters())
        for name, value in state.items():
            parameters[name].copy_(value.to(parameters[name].device))


def adapter_exports(model):
    result = {}
    for name, module in model.named_modules():
        if isinstance(module, LowRankLinear):
            A, B = module.factors()
            result[name] = {"A": A.detach().cpu(), "B": B.detach().cpu(), "scale": module.scale}
    return result


def merge_into_fresh(model, exports):
    # Fresh backbone copy: the original snapshot itself is never overwritten.
    with torch.no_grad():
        for name, adapter in exports.items():
            weight = model.get_submodule(name).weight
            delta = adapter["scale"] * (adapter["B"].float() @ adapter["A"].float())
            weight.copy_((weight.float() + delta.to(weight.device)).to(weight.dtype))
    return model
