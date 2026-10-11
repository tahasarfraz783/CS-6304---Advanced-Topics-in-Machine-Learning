"""Small local models test PPO plumbing without downloads or experiment runs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from transformers import Qwen2Config, Qwen2ForCausalLM, Qwen2ForSequenceClassification
from peft import get_peft_model, LoraConfig
from common.models import trainable_parameters
from task2_ppo.runtime import logprobs, values, optimizer_step
from task2_ppo.continue_train import run_ppo
from task2_ppo.evaluate import run_evaluation


def tiny_models():
    cfg = Qwen2Config(vocab_size=32, hidden_size=16, intermediate_size=32,
                     num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
                     num_labels=1, pad_token_id=0)
    policy = get_peft_model(Qwen2ForCausalLM(cfg), LoraConfig(
        r=2, lora_alpha=4, target_modules=['q_proj', 'v_proj'], task_type='CAUSAL_LM'))
    critic = get_peft_model(Qwen2ForSequenceClassification(cfg), LoraConfig(
        r=2, lora_alpha=4, target_modules=['q_proj', 'v_proj'],
        task_type='SEQ_CLS', modules_to_save=['score']))
    return policy, critic


def rollout():
    seq = torch.tensor([[1, 2, 3, 4]])
    return {'sequences': seq, 'attention_mask': torch.ones_like(seq), 'prompt_width': 2,
            'response_ids': seq[:, 2:], 'response_mask': torch.ones(1, 2),
            'responses': ['test'], 'terminated_with_eos': [True], 'response_lengths': [2], 'truncated': [False]}


class RuntimeTests(unittest.TestCase):
    def test_logprob_and_critic_alignment(self):
        policy, critic = tiny_models()
        policy.eval()
        critic.eval()
        r = rollout()
        expected = policy(input_ids=r['sequences']).logits[:, 1:3].float().log_softmax(-1)
        expected = expected.gather(-1, r['response_ids'].unsqueeze(-1)).squeeze(-1)
        torch.testing.assert_close(logprobs(policy, r), expected)
        v = values(critic, r)
        self.assertEqual(tuple(v.shape), (1, 2))
        v.sum().backward()
        self.assertTrue(any(p.grad is not None for p in trainable_parameters(critic)))

    def test_nonfinite_loss_rejected(self):
        p = torch.nn.Parameter(torch.tensor([1.]))
        optimizer = torch.optim.AdamW([p])
        with self.assertRaises(FloatingPointError):
            optimizer_step(p.sum() * float('nan'), optimizer, [p],
                           torch.amp.GradScaler('cuda', enabled=False), 1.)

    def test_half_backbone_float_critic_head(self):
        _, critic = tiny_models()
        critic.half()
        for p in trainable_parameters(critic):
            p.data = p.data.float()
        prediction = values(critic, rollout())
        self.assertEqual(prediction.dtype, torch.float32)
        prediction.sum().backward()

    def test_two_update_loop_saves_logs_and_checkpoints(self):
        policy, critic = tiny_models()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'seed': 6304, 'output': str(Path(tmp) / 'adapter'),
                   'results_dir': str(Path(tmp) / 'results'), 'updates': 2,
                   'prompts_per_update': 1, 'ppo_epochs': 2, 'missing_eos_penalty': 1.,
                   'reward_max_length': 64, 'gamma': 1., 'gae_lambda': .95,
                   'clip_epsilon': .2, 'kl_beta': .1, 'max_grad_norm': 1., 'value_coef': .5}
            class Tokenizer:
                def save_pretrained(self, destination):
                    pass
            bundle = {'cfg': cfg, 'policy': policy, 'value_model': critic,
                      'tokenizer': Tokenizer(), 'reward_model': None, 'reward_tokenizer': None,
                      'prompt_rows': [{'prompt': 'hello', 'prompt_id': 'test'}],
                      'policy_optimizer': torch.optim.AdamW(trainable_parameters(policy), lr=.001),
                      'value_optimizer': torch.optim.AdamW(trainable_parameters(critic), lr=.001)}
            with patch('task2_ppo.continue_train.load_yaml', return_value=cfg), \
                 patch('task2_ppo.continue_train.prepare_ppo_continuation', return_value=bundle), \
                 patch('task2_ppo.continue_train.generate', side_effect=lambda *a: rollout()), \
                 patch('task2_ppo.continue_train.score_reward_pairs', return_value=torch.tensor([1.])):
                summary = run_ppo('unused')
                self.assertEqual(summary['updates'], 2)
                self.assertEqual(summary['generated_tokens'], 4)
                self.assertEqual(summary['skipped_optimizer_steps'], 0)
                self.assertTrue((Path(cfg['output']) / 'adapter_model.safetensors').exists())
                self.assertTrue((Path(cfg['output']) / 'value_model' / 'adapter_model.safetensors').exists())
                self.assertEqual(len((Path(cfg['results_dir']) / 'standard_train.jsonl').read_text().splitlines()), 2)
                with self.assertRaises(FileExistsError):
                    run_ppo('unused')

    def test_evaluation_writes_metrics_and_examples(self):
        policy, _ = tiny_models()
        policy.eval()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'seed': 6304, 'results_dir': tmp, 'generation': {'do_sample': True},
                   'eval_max_response_length': 768, 'reward_max_length': 64,
                   'missing_eos_penalty': 1.}
            bundle = {'cfg': cfg, 'policy': policy, 'tokenizer': None,
                      'reward': (None, None), 'rows': [{'prompt': 'hello', 'prompt_id': 'test'}]}
            with patch('task2_ppo.evaluate.load_yaml', return_value=cfg), \
                 patch('task2_ppo.evaluate.load_evaluation_bundle', return_value=bundle), \
                 patch('task2_ppo.evaluate.generate', side_effect=lambda *a, **kw: rollout()), \
                 patch('task2_ppo.evaluate.score_reward_pairs', return_value=torch.tensor([2.])):
                summary = run_evaluation('unused', 'unused', 'test')
                self.assertEqual(summary['learned_reward'], 2.)
                self.assertEqual(summary['response_length'], 2.)
                self.assertTrue((Path(tmp) / 'test_evaluation.json').exists())
                self.assertTrue((Path(tmp) / 'test_eval.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
