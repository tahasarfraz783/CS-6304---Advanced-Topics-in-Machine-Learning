import importlib.util
import tempfile
import unittest
from pathlib import Path

AVAILABLE = all(importlib.util.find_spec(m) is not None for m in ['torch', 'transformers', 'peft', 'numpy'])
if AVAILABLE:
    import torch
    import torch.nn.functional as F
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from task2.model import VLM


class TinyTokenizer:
    pad_token_id = 0
    def encode(self, text, add_special_tokens=False):
        return [3+ord(c)%24 for c in text]
    def batch_decode(self, output, skip_special_tokens=True):
        return [' '.join(map(str, r.tolist())) for r in output]


def tiny():
    torch.manual_seed(6304)
    m = VLM.__new__(VLM)
    torch.nn.Module.__init__(m)
    m.cfg = dict(question_cap=80, caption_cap=64, answer_cap=16)
    m.lm = Qwen3ForCausalLM(Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=64,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=8,
        attention_dropout=0., pad_token_id=0, eos_token_id=2, bos_token_id=1))
    m.lm.requires_grad_(False)
    m.connector = torch.nn.Sequential(torch.nn.Linear(768, 32), torch.nn.GELU(), torch.nn.Linear(32, 32))
    m.register_buffer('visual_scale', torch.tensor(1.))
    m.has_lora = False
    m.end_id = 2
    m.tokenizer = TinyTokenizer()
    m.prompt = lambda question: ([1, 4], [5, 6]+([7] if len(question) > 2 else []))
    return m


@unittest.skipUnless(AVAILABLE, 'Install numeric dependencies')
class NumericTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.m = tiny()
        self.examples = [dict(question='a', target='one', kind='presence'), dict(question='long', target='a longer caption', kind='caption')]
        self.features = torch.randn(2, 196, 768)

    def test_selected_logits_equal_full_projection_and_gradients(self):
        self.m.eval()
        inputs, labels = self.m.pack(self.examples, self.features)
        full = self.m.lm(**inputs, use_cache=False).logits[:, :-1].float()
        y = labels[:, 1:]
        token = F.cross_entropy(full.reshape(-1, 32), y.reshape(-1), ignore_index=-100, reduction='none').reshape_as(y)
        expected = token.sum(1)/(y != -100).sum(1)
        actual = self.m.losses(self.examples, self.features)
        torch.testing.assert_close(actual, expected)
        grad1 = torch.autograd.grad(expected.mean(), list(self.m.connector.parameters()), retain_graph=True)
        grad2 = torch.autograd.grad(actual.mean(), list(self.m.connector.parameters()))
        for a, b in zip(grad1, grad2):
            torch.testing.assert_close(a, b, rtol=2e-5, atol=1e-6)
        self.assertTrue(any(g.abs().sum() > 0 for g in grad2))
        self.assertTrue(all(p.grad is None for p in self.m.lm.parameters()))

    def test_no_image_masks_positions_and_termination(self):
        visual, labels = self.m.pack(self.examples, self.features)
        plain, no_labels = self.m.pack(self.examples, None, 'none')
        self.assertEqual(visual['inputs_embeds'].shape[1]-plain['inputs_embeds'].shape[1], 196)
        for i in range(2):
            pos = plain['position_ids'][i][plain['attention_mask'][i].bool()]
            torch.testing.assert_close(pos, torch.arange(len(pos)))
        self.assertTrue(all((r == 2).sum() == 1 for r in no_labels))
        _, without = self.m.pack(self.examples, self.features, include_end=False)
        self.assertEqual((labels != -100).sum().item()-(without != -100).sum().item(), 2)

    def test_cached_greedy_generation_batched_and_no_image(self):
        self.m.eval()
        with torch.inference_mode():
            a = self.m.generate(self.examples, self.features)
            b = self.m.generate(self.examples, None, 'none')
        self.assertEqual(len(a), 2)
        self.assertEqual(len(b), 2)
        self.assertTrue(all(len(s.split()) <= 16 for s in a+b))

    def test_lora_and_checkpointing_still_train_connector(self):
        self.m.enable_lora()
        self.m.lm.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        self.m.train()
        loss = self.m.losses(self.examples, self.features).mean()
        loss.backward()
        self.assertGreater(sum(p.grad.abs().sum() for p in self.m.connector.parameters()), 0)
        for n, p in self.m.lm.named_parameters():
            if 'lora_' not in n:
                self.assertFalse(p.requires_grad)
                self.assertIsNone(p.grad)
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum() > 0 for n, p in self.m.lm.named_parameters() if 'lora_' in n))

    def test_schedule_endpoints(self):
        from task2.training import lr_factor
        self.assertAlmostEqual(lr_factor(2250, 2250), .1)
        self.assertAlmostEqual(lr_factor(112, 2250), 1.)

    def test_checkpoint_restores_optimizer_sampler_and_dropout_rng(self):
        from task2.training import save_checkpoint, restore_rng
        from task2.data import Sampler
        from test_protocol import fixture
        manifest = fixture()
        for r in manifest['train']['captions']:
            r['question'] = 'Describe image'
        self.m.enable_lora()
        optimizer = torch.optim.AdamW([p for p in self.m.parameters() if p.requires_grad], lr=.001)
        scaler = torch.amp.GradScaler('cuda', enabled=False)
        sampler = Sampler(manifest, 6304)
        def step(model, opt, smp):
            examples, _ = smp.batch(2, 2)
            features = torch.randn(2, 196, 768)
            model.train()
            opt.zero_grad()
            loss = model.losses(examples, features).mean()
            loss.backward()
            opt.step()
            return loss.detach()
        step(self.m, optimizer, sampler)
        cfg = dict(stage_updates=[2, 2, 2], warmup_fraction=.05, lr_floor=.1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'checkpoint.pt'
            save_checkpoint(path, self.m, optimizer, scaler, sampler, 2, 1, 3, cfg, {})
            expected_loss = step(self.m, optimizer, sampler)
            expected = self.m.trainable_state()
            saved = torch.load(path, weights_only=False)
            recovered = tiny()
            recovered.enable_lora()
            recovered.load_trainable(saved['weights'])
            recovered.visual_scale.copy_(saved['visual_scale'])
            opt = torch.optim.AdamW([p for p in recovered.parameters() if p.requires_grad], lr=.001)
            opt.load_state_dict(saved['optimizer'])
            smp = Sampler(manifest, 1)
            smp.load_state_dict(saved['sampler'])
            restore_rng(saved['rng'])
            actual_loss = step(recovered, opt, smp)
            torch.testing.assert_close(actual_loss, expected_loss, rtol=0, atol=0)
            for k, v in recovered.trainable_state().items():
                torch.testing.assert_close(v, expected[k], rtol=0, atol=0)

    def test_siglip_processor_shape_and_single_final_normalization(self):
        from transformers import SiglipImageProcessor, SiglipVisionConfig, SiglipVisionModel
        from PIL import Image
        processor = SiglipImageProcessor(size={'height':32, 'width':32})
        pixels = processor(images=Image.new('RGB', (50, 40)), return_tensors='pt')['pixel_values']
        self.assertEqual(tuple(pixels.shape), (1,3,32,32))
        vision = SiglipVisionModel(SiglipVisionConfig(hidden_size=32, intermediate_size=64,
            num_hidden_layers=2, num_attention_heads=4, image_size=32, patch_size=16)).eval()
        calls = []
        hook = vision.vision_model.post_layernorm.register_forward_hook(lambda *a:calls.append(1))
        with torch.inference_mode():
            features = vision(pixel_values=pixels).last_hidden_state
        hook.remove()
        self.assertEqual(tuple(features.shape), (1,4,32))
        self.assertEqual(len(calls), 1)
        self.assertTrue(torch.isfinite(features).all())


if __name__ == '__main__':
    unittest.main()
