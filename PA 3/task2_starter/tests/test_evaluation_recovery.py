import contextlib
import importlib.util
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from task2.common import rows
from task2.data import ground_pair


@unittest.skipUnless(importlib.util.find_spec('torch'), 'torch needed')
class EvaluationRecoveryTests(unittest.TestCase):
    def test_atomic_batches_reused_after_interrupt(self):
        import torch
        from task2.evaluation import evaluate_final
        pool = [dict(category_id=1, name='person', positive=[1], negative=[2], bins={})]
        manifest = {'test': {}, 'mismatches': {}}
        for suite in ['grounding', 'natural']:
            pairs = [ground_pair(pool, 'presence', random.Random(i), 'val2014', i) for i in range(4)]
            for p in pairs:
                for r in p:
                    r['suite'] = suite
                    if suite == 'natural':
                        r['answers'] *= 10
                        r['kind'] = 'yes/no'
            manifest['test'][suite] = pairs
            manifest['mismatches'][suite] = {r['id']:10 for p in pairs for r in p}
        class Model:
            def __init__(self, fail=False):
                self.calls, self.fail = 0, fail
            def eval(self):
                pass
            def generate(self, batch, features, condition):
                self.calls += 1
                if self.fail and self.calls == 3:
                    raise RuntimeError('simulated interruption')
                return [r['target'] for r in batch]
            def losses(self, batch, *args, **kwargs):
                return torch.ones(len(batch))
        class Store:
            def batch(self, *args):
                return None
        class Progress:
            def emit(self, *args, **kwargs):
                pass
        cfg = dict(generation_batch=8, bootstrap_resamples=100, seed=6304)
        with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as stack:
            for name in ['synchronize', 'reset_peak_memory_stats']:
                stack.enter_context(patch('torch.cuda.'+name, lambda:None))
            stack.enter_context(patch('torch.cuda.max_memory_allocated', lambda:123))
            stack.enter_context(patch('torch.autocast', lambda *a, **k:contextlib.nullcontext()))
            root = Path(d)
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                evaluate_final(Model(True), Store(), manifest, cfg, root, Progress())
            self.assertEqual(len(list((root/'evaluations'/'batches').glob('*.json'))), 2)
            recovered = Model()
            evaluate_final(recovered, Store(), manifest, cfg, root, Progress())
            self.assertEqual(recovered.calls, 6)
            self.assertEqual(len(rows(root/'evaluations'/'final_examples.jsonl')), 64)
            self.assertTrue((root/'evaluations'/'final_summary.json').exists())


if __name__ == '__main__':
    unittest.main()
