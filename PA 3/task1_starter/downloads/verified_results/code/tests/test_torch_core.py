"""Exercise actual adapter/label code on CPU once the ML dependencies are installed."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "datasets"))
if AVAILABLE:
    import torch
    from task1.model import LowRankLinear
    from task1.data import collate


@unittest.skipUnless(AVAILABLE, "Install torch/transformers/datasets to run numeric core checks")
class NumericChecks(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(6304)

    def test_zero_initial_correction_then_real_low_rank_update(self):
        base = torch.nn.Linear(7, 5, bias=False)
        layer = LowRankLinear(base, 2, 4, 0)
        x = torch.randn(3, 7)
        self.assertTrue(torch.equal(layer(x), base(x)))
        with torch.no_grad():
            layer.B.normal_()
        self.assertLessEqual(torch.linalg.matrix_rank(layer.B @ layer.A).item(), 2)
        expected = torch.nn.functional.linear(x, base.weight + layer.scale * layer.B @ layer.A)
        self.assertTrue(torch.allclose(layer(x), expected, atol=1e-6))
        layer(x).sum().backward()
        self.assertIsNone(base.weight.grad)
        self.assertIsNotNone(layer.A.grad)
        self.assertIsNotNone(layer.B.grad)

    def test_both_orthogonal_constraints_hold_for_actual_factor_code(self):
        U = torch.linalg.qr(torch.randn(5, 2)).Q
        V = torch.linalg.qr(torch.randn(7, 2)).Q
        layer = LowRankLinear(torch.nn.Linear(7, 5, bias=False), 2, 4, 0, {"U": U, "V": V})
        with torch.no_grad():
            layer.B.normal_()
        A, B = layer.factors()
        delta = B @ A
        self.assertLess((U.T @ delta).norm().item(), 1e-5)
        self.assertLess((delta @ V).norm().item(), 1e-5)
        delta.square().sum().backward()
        self.assertIsNotNone(layer.A.grad)

    def test_prompt_padding_mask_and_token_weighting(self):
        batch = collate([
            {"input_ids": [1, 2, 3], "labels": [-100, 2, 3]},
            {"input_ids": [1, 4], "labels": [-100, 4]},
        ], pad_id=0)
        self.assertEqual(batch["labels"].tolist(), [[-100, 2, 3], [-100, 4, -100]])
        self.assertEqual(batch["attention_mask"].tolist(), [[1, 1, 1], [1, 1, 0]])
        logits = torch.randn(2, 3, 8)
        targets = batch["labels"][:, 1:]
        summed = torch.nn.functional.cross_entropy(logits[:, :-1].reshape(-1, 8), targets.reshape(-1), reduction="sum")
        actual = 0
        for i in range(2):
            count = (targets[i] != -100).sum()
            mean = torch.nn.functional.cross_entropy(logits[i, :-1], targets[i])
            actual += mean * count / 3
        self.assertTrue(torch.allclose(actual, summed / 3))


if __name__ == "__main__":
    unittest.main()
