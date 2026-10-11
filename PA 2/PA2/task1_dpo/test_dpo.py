"""Small CPU checks: python -m unittest task1_dpo.test_dpo."""
import unittest
from types import SimpleNamespace
import torch
from task1_dpo.dpo import dpo_loss
from common.generation import response_sequence_logprobs
from task1_dpo.train import optimizer_update


class DPOTests(unittest.TestCase):
    @unittest.skipUnless(torch.cuda.is_available(), "CUDA required for FP16 scaler regression")
    def test_overflow_skips_and_recovers(self):
        p = torch.nn.Parameter(torch.tensor([1.], device="cuda"))
        optimizer = torch.optim.AdamW([p], lr=0.01)
        scaler = torch.amp.GradScaler("cuda", init_scale=256.)
        scaler.scale(p.sum() * float("inf")).backward()
        self.assertFalse(optimizer_update(optimizer, [p], scaler, 1.))
        self.assertEqual(float(p), 1.)
        self.assertEqual(scaler.get_scale(), 128.)
        self.assertEqual(len(optimizer.state), 0)
        scaler.scale(p.sum()).backward()
        self.assertTrue(optimizer_update(optimizer, [p], scaler, 1.))
        self.assertLess(float(p), 1.)

    def test_equal_policy_reference(self):
        chosen, rejected = torch.tensor([2., -3.]), torch.tensor([-1., -2.])
        loss, _ = dpo_loss(chosen, rejected, chosen, rejected, 0.1)
        self.assertAlmostEqual(float(loss), 0.69314718, places=6)

    def test_preference_gradient(self):
        chosen = torch.tensor([0.], requires_grad=True)
        rejected = torch.tensor([0.], requires_grad=True)
        loss, _ = dpo_loss(chosen, rejected, torch.zeros(1), torch.zeros(1), 0.1)
        loss.backward()
        self.assertLess(float(chosen.grad), 0)
        self.assertGreater(float(rejected.grad), 0)

    def test_shift_and_response_mask(self):
        logits = torch.tensor([[[0., 0., 0.], [0., 2., 0.], [0., 0., 3.], [0., 0., 0.]]])
        class Model:
            def __call__(self, **kwargs):
                return SimpleNamespace(logits=logits)
        batch = {"input_ids": torch.tensor([[0, 0, 1, 2]]),
                 "attention_mask": torch.tensor([[0, 1, 1, 1]]),
                 "response_mask": torch.tensor([[0., 0., 1., 1.]])}
        actual, _, _ = response_sequence_logprobs(Model(), batch)
        expected = logits[0, 1].log_softmax(-1)[1] + logits[0, 2].log_softmax(-1)[2]
        torch.testing.assert_close(actual[0], expected)


if __name__ == "__main__":
    unittest.main()
