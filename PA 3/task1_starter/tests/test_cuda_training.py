"""Tiny, offline CUDA checks of the real training loop; no assignment data/results."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
READY = all(importlib.util.find_spec(n) is not None for n in ("torch", "transformers", "datasets"))
if READY:
    import torch
    READY = torch.cuda.is_available()
if READY:
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from task1.common import METHODS, write_jsonl
    from task1.model import basis_path, weight_modules
    from task1.training import train, latest_checkpoint, save_checkpoint
    from task1.progress import LiveProgress


@unittest.skipUnless(READY, "Requires CUDA and the ML dependencies; uses only a tiny random model")
class CudaTrainingChecks(unittest.TestCase):
    def prepare_tiny(self, root):
        torch.manual_seed(12)
        config = Qwen3Config(vocab_size=32, hidden_size=16, intermediate_size=32,
                             num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                             head_dim=8, max_position_embeddings=64,
                             bos_token_id=1, eos_token_id=2, pad_token_id=0, tie_word_embeddings=True)
        model = Qwen3ForCausalLM(config)
        model.save_pretrained(root / "prepared/base")
        for name, module in weight_modules(model):
            U, _, Vh = torch.linalg.svd(module.weight.detach().float(), full_matrices=False)
            path = basis_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"U": U[:, :2].contiguous(), "V": Vh[:2].T.contiguous()}, path)
        rows = [{"input_ids": [1, 3, 4, 5, 2], "labels": [-100, -100, 4, 5, 2]}
                for _ in range(4)]
        write_jsonl(root / "prepared/training.jsonl", rows)
        return {"seed": 6304, "examples": 4, "microbatch": 1, "accumulation": 2,
                "warmup_updates": 1, "weight_decay": 0.01, "lambda_sp": 0.001,
                "adapter_dropout": 0.05, "plot_every": 99}

    def test_all_five_train_with_fp32_optimizer_states_and_resume_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c = self.prepare_tiny(root)
            with patch("task1.training.load_tokenizer", return_value=SimpleNamespace(pad_token_id=0)):
                for method in METHODS:
                    with LiveProgress(root, "train", method) as progress:
                        train(c, root, method, 2, progress=progress)
                    path = root / "runs" / method / "checkpoints/update_0002.pt"
                    saved = torch.load(path, map_location="cpu", weights_only=False)
                    self.assertEqual(saved["update"], 2)
                    self.assertEqual(saved["totals"]["skipped_updates"], 0)
                    for state in saved["optimizer"]["state"].values():
                        self.assertEqual(state["exp_avg"].dtype, torch.float32)
                        self.assertEqual(state["exp_avg_sq"].dtype, torch.float32)
                continuous = {n: p.clone() for n, p in saved["model"].items()}
                # Independent equivalent starting snapshot, split at midpoint.
                resumed = root / "resumed"
                self.prepare_tiny(resumed)
                train(c, resumed, "oplora16", 1)
                train(c, resumed, "oplora16", 2)
                final = torch.load(resumed / "runs/oplora16/checkpoints/update_0002.pt",
                                   map_location="cpu", weights_only=False)
                for name, value in continuous.items():
                    self.assertTrue(torch.equal(value, final["model"][name]), name)

    def test_interrupted_rolling_checkpoint_resumes_exactly_and_is_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c = self.prepare_tiny(root)
            c.update(examples=10, rolling_checkpoint_every=2)
            row = {"input_ids": [1, 3, 4, 5, 2], "labels": [-100, -100, 4, 5, 2]}
            write_jsonl(root / "prepared/training.jsonl", [row]*10)
            resumed = root / "resumed"
            self.prepare_tiny(resumed)
            write_jsonl(resumed / "prepared/training.jsonl", [row]*10)
            with patch("task1.training.load_tokenizer", return_value=SimpleNamespace(pad_token_id=0)):
                train(c, root, "lora16", 5)
                def interrupted_save(*args, **kwargs):
                    result = save_checkpoint(*args, **kwargs)
                    if args[0].name == "rolling_update_0004.pt":
                        raise RuntimeError("simulated interruption")
                    return result
                with patch("task1.training.save_checkpoint", side_effect=interrupted_save):
                    with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                        train(c, resumed, "lora16", 5)
                folder = resumed / "runs/lora16/checkpoints"
                self.assertEqual(latest_checkpoint(folder).name, "rolling_update_0004.pt")
                train(c, resumed, "lora16", 5)
            a = torch.load(root / "runs/lora16/checkpoints/update_0005.pt", weights_only=False, map_location="cpu")
            b = torch.load(folder / "update_0005.pt", weights_only=False, map_location="cpu")
            for name in a["model"]:
                self.assertTrue(torch.equal(a["model"][name], b["model"][name]), name)
            self.assertFalse(list(folder.glob("rolling_update_*.pt")))
            self.assertTrue((folder / "update_0003.pt").exists())


if __name__ == "__main__":
    unittest.main()
