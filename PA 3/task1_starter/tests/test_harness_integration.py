"""Real pinned HFLM + tiny random Qwen + local tokenizer. No downloads/datasets."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
READY = all(importlib.util.find_spec(n) is not None for n in ("torch", "transformers", "lm_eval", "tokenizers"))


@unittest.skipUnless(READY, "Install requirements to check the actual evaluation harness")
class HarnessIntegrationChecks(unittest.TestCase):
    def test_real_generation_forward_progress_cache_and_likelihood(self):
        import torch
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM
        from lm_eval.api.instance import Instance
        from lm_eval.models.huggingface import HFLM
        from task1.evaluation import LoggedHFLM
        from task1.progress import LiveProgress
        vocab = {"[PAD]": 0, "[BOS]": 1, "[EOS]": 2, "[UNK]": 3}
        vocab.update({f"word{i}": i for i in range(4, 32)})
        backend = Tokenizer(WordLevel(vocab, unk_token="[UNK]"))
        backend.pre_tokenizer = Whitespace()
        tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, pad_token="[PAD]",
                        bos_token="[BOS]", eos_token="[EOS]", unk_token="[UNK]")
        config = Qwen3Config(vocab_size=32, hidden_size=16, intermediate_size=32,
                            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                            head_dim=8, max_position_embeddings=64, bos_token_id=1,
                            eos_token_id=2, pad_token_id=0, tie_word_embeddings=True)
        torch.manual_seed(6304)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = Qwen3ForCausalLM(config).to(device).eval()
        wrapper = LoggedHFLM(pretrained=model, tokenizer=tokenizer, batch_size=8, max_length=64)
        requests = [Instance(request_type="generate_until", doc={}, idx=0,
                    arguments=("word4" if i == 10 else " ".join([f"word{4+i}"]*(i+1)), {"max_gen_toks": 4, "do_sample": False, "until": ["[EOS]"]}),
                    metadata=("test", i, 1)) for i in range(11)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrapper.generation_cache_path = root / "answers.jsonl"
            with LiveProgress(root, "test", heartbeat_seconds=0.2) as progress:
                wrapper.progress = progress
                actual = wrapper.generate_until(requests)
                self.assertEqual(len(actual), 11)
                self.assertEqual(len(wrapper.generation_cache_path.read_text().splitlines()), 11)
                self.assertEqual(json.loads((root / "progress.json").read_text())["completed"], 11)
                self.assertTrue(progress.thread.is_alive())
                self.assertEqual(len(model._forward_hooks), 0)
                # Exact stock-harness comparison uses identical size-eight batches
                # and prompt grouping, including unequal left-padding lengths.
                native = HFLM(pretrained=model, tokenizer=tokenizer, batch_size=8, max_length=64)
                ordered = sorted(range(len(requests)), key=lambda i: -len(wrapper.tok_encode(requests[i].args[0])))
                expected = [None]*len(requests)
                for start in range(0, len(ordered), 8):
                    indices = ordered[start:start+8]
                    values = native.generate_until([requests[i] for i in indices], disable_tqdm=True)
                    for i, value in zip(indices, values):
                        expected[i] = value
                self.assertEqual(actual, expected)
                # A cached repeat must not enter the model at all.
                def forbid(*args, **kwargs):
                    raise AssertionError("A cached response was regenerated")
                hook = model.register_forward_pre_hook(forbid)
                try:
                    self.assertEqual(wrapper.generate_until(requests), actual)
                finally:
                    hook.remove()
                wrapper.active_task = "tiny"
                likelihoods = wrapper.loglikelihood([Instance(request_type="loglikelihood", doc={}, idx=0,
                               arguments=("word4", " word5"), metadata=("test", 0, 1))])
                self.assertEqual(len(likelihoods), 1)
            self.assertEqual(json.loads((root / "progress.json").read_text())["state"], "completed")
