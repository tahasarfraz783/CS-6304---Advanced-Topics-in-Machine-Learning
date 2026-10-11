"""CPU objective checks: python -m unittest task2_ppo.test_ppo."""
import unittest

import torch

from task2_ppo.ppo import compute_gae, ppo_policy_loss, shaped_rewards


class PPOTests(unittest.TestCase):
    def test_clipping_geometry_and_gradients(self):
        # Positive advantages saturate above the upper bound; negative ones
        # saturate below the lower bound. Moves in the harmful direction do not.
        logp = torch.tensor([[1.5, 0.5, 1.5, 0.5]]).log().requires_grad_()
        advantage = torch.tensor([[2., 2., -2., -2.]])
        loss, ratio, fraction = ppo_policy_loss(
            logp, torch.zeros_like(logp), advantage, torch.ones_like(logp), eps=0.2
        )
        self.assertAlmostEqual(float(loss.detach()), 0.3, places=6)
        self.assertEqual(float(fraction), 1.)
        loss.backward()
        torch.testing.assert_close(logp.grad, torch.tensor([[0., -0.25, 0.75, 0.]]))

    def test_padding_does_not_affect_objective(self):
        loss, _, fraction = ppo_policy_loss(
            torch.tensor([[1., 5.]]).log(), torch.zeros(1, 2),
            torch.tensor([[2., 100.]]), torch.tensor([[1., 0.]])
        )
        self.assertEqual(float(loss), -2.)
        self.assertEqual(float(fraction), 0.)

    def test_terminal_reward_and_gae(self):
        mask = torch.tensor([[1., 1., 0.]])
        rewards = shaped_rewards(torch.tensor([3.]), torch.tensor([[1., 2., 99.]]),
                                 torch.zeros(1, 3), mask, beta_kl=0.1)
        torch.testing.assert_close(rewards, torch.tensor([[-0.1, 2.8, 0.]]))
        advantages, returns = compute_gae(rewards, torch.tensor([[0.5, 1., 0.]]),
                                          mask, gamma=1., lam=1.)
        torch.testing.assert_close(advantages, torch.tensor([[2.2, 1.8, 0.]]))
        torch.testing.assert_close(returns, torch.tensor([[2.7, 2.8, 0.]]))


if __name__ == "__main__":
    unittest.main()
