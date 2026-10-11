"""CPU objective checks: python -m unittest task3_grpo.test_grpo."""
import unittest

import torch

from task3_grpo.grpo import (
    group_relative_advantages, grpo_policy_loss, mask_truncated_sequences,
)
from task3_grpo.analyze_group_size import regroup_equal_generation_budget, summarize_groups


class GRPOTests(unittest.TestCase):
    def test_equal_generation_partition(self):
        cache = {'a': [{'generation_index': i, 'reward': float(i % 2)} for i in range(8)],
                 'b': [{'generation_index': i, 'reward': 1.} for i in range(8)]}
        for k in (2, 4, 8):
            groups = regroup_equal_generation_budget(cache, k)
            self.assertEqual(len(groups), 16 // k)
            self.assertTrue(all(len(rows) == k for _, rows in groups))
            metrics = summarize_groups(groups)
            self.assertEqual(metrics['generations'], 16)
            self.assertEqual(metrics['informative_group_rate'], 0.5)

    def test_serial_accumulation_matches_batch_gradient(self):
        mask = torch.tensor([[1., 0., 0.], [1., 1., 1.], [0., 0., 0.]])
        adv = torch.tensor([1., -0.5, 0.])
        for mode in ('grpo', 'dr_grpo'):
            batch = torch.full((3, 3), -0.2, requires_grad=True)
            reference = torch.full_like(batch, -0.4)
            old = torch.full_like(batch, -0.3)
            loss, _ = grpo_policy_loss(batch, old, adv, mask, reference, 0.2, 0.1, mode, 3)
            loss.backward()
            serial = batch.detach().clone().requires_grad_()
            for i in range(3):
                weight = 3 * float(mask[i].sum()) / float(mask.sum())
                term, _ = grpo_policy_loss(serial[i:i+1], old[i:i+1], adv[i:i+1],
                    mask[i:i+1], reference[i:i+1], 0.2, 0.1 * weight, mode, 3)
                (term / 3).backward()
            torch.testing.assert_close(serial.grad, batch.grad)

    def test_interleaved_prompts_have_independent_baselines(self):
        rewards = torch.tensor([1., 100., 3., 104.])
        ids = torch.tensor([7, 42, 7, 42])
        actual = group_relative_advantages(rewards, ids, eps=0.1)
        expected = torch.tensor([-1 / 1.1, -2 / 2.1, 1 / 1.1, 2 / 2.1])
        torch.testing.assert_close(actual, expected)

    def test_constant_and_singleton_groups_have_no_signal(self):
        actual = group_relative_advantages(
            torch.tensor([5., 5., 100.]), torch.tensor([0, 0, 1]))
        torch.testing.assert_close(actual, torch.zeros(3))

    def test_other_prompt_cannot_change_advantages(self):
        ids = torch.tensor([0, 0, 1, 1])
        first = group_relative_advantages(torch.tensor([1., 3., 4., 8.]), ids)
        second = group_relative_advantages(torch.tensor([1., 3., 400., 800.]), ids)
        torch.testing.assert_close(first[:2], second[:2])

    def test_normalization_changes_gradient_allocation(self):
        mask = torch.tensor([[1., 0., 0., 0.], [1., 1., 1., 1.]])
        for mode, expected in [("grpo", torch.tensor([-0.5, -0.5])),
                               ("dr_grpo", torch.tensor([-0.125, -0.5]))]:
            logp = torch.zeros(2, 4, requires_grad=True)
            loss, metrics = grpo_policy_loss(
                logp, torch.zeros_like(logp), torch.ones(2), mask,
                torch.zeros_like(logp), 0.2, 0.1, mode, 4)
            loss.backward()
            torch.testing.assert_close(logp.grad.sum(-1), expected)
            self.assertEqual(float(metrics["sampled_kl"]), 0.)

    def test_truncated_completion_has_zero_gradient(self):
        logp = torch.zeros(2, 3, requires_grad=True)
        mask = mask_truncated_sequences(torch.ones_like(logp), [False, True])
        loss, _ = grpo_policy_loss(logp, torch.zeros_like(logp), torch.ones(2),
                                   mask, torch.zeros_like(logp), 0.2, 0.1)
        loss.backward()
        torch.testing.assert_close(logp.grad[1], torch.zeros(3))

    def test_clipped_positive_and_negative_advantages(self):
        logp = torch.tensor([[1.5], [0.5]]).log().requires_grad_()
        loss, _ = grpo_policy_loss(logp, torch.zeros_like(logp),
                                   torch.tensor([1., -1.]), torch.ones_like(logp),
                                   logp.detach(), 0.2, 0.)
        self.assertAlmostEqual(float(loss.detach()), -0.2, places=6)
        loss.backward()
        torch.testing.assert_close(logp.grad, torch.zeros_like(logp))


if __name__ == "__main__":
    unittest.main()
