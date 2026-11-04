import importlib.util
import tempfile
import unittest
from pathlib import Path
from task2.common import write, jsonl


@unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'matplotlib needed')
class EvidenceTests(unittest.TestCase):
    def test_figures_tables_dashboard_and_live_refresh(self):
        from task2.plots import build_evidence
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root/'resolved_config.json', {'stage_updates':[2250, 1500, 750]})
            for i in range(3):
                jsonl(root/'training.jsonl', dict(update=i+1, loss=2.-i*.1, examples_per_second=20.,
                    peak_gpu_bytes=3*2**30, allocated_gpu_bytes=2*2**30, reserved_gpu_bytes=4*2**30,
                    lr_connector=.001, lr_lora=0, mixture={'caption':16}))
            dev = dict(update=0, captions_correct_nll=3.)
            for suite in ['grounding', 'natural']:
                for c in ['correct', 'swap', 'none']:
                    dev[suite+'_'+c+'_nll'] = 2.
                dev[suite+'_swap_penalty'] = 0.
            write(root/'evaluations'/'dev_0000.json', dev)
            write(root/'resources.json', {'1': {'training_seconds':1., 'peak_gpu_bytes':3*2**30, 'connector':123, 'lora':0}})
            from task2.scoring import summarize
            examples = []
            for suite in ['grounding', 'natural']:
                for c in ['correct', 'swap', 'mismatched', 'none']:
                    for p in range(2):
                        for j in range(2):
                            examples.append(dict(suite=suite, condition=c, pair_id=str(p), kind='presence' if suite == 'grounding' else 'yes/no',
                                prediction='yes', score=.9, exact=True, partner_match=False, nll=1., generation_seconds=.1))
            write(root/'evaluations'/'final_summary.json', summarize(examples, 100))
            build_evidence(root)
            build_evidence(root, live=True)
            for name in ['training_loss', 'caption_dev_loss', 'grounding_dev_nll', 'natural_dev_nll', 'swap_penalties']:
                for ext in ['png', 'svg', 'pdf']:
                    self.assertGreater((root/'evidence'/(name+'.'+ext)).stat().st_size, 100)
            self.assertTrue((root/'evidence'/'development.csv').exists())
            self.assertTrue((root/'evidence'/'final_compact_tables.csv').exists())
            self.assertTrue((root/'evidence'/'natural_final_accuracy.pdf').exists())
            self.assertIn('progress.json', (root/'evidence'/'index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
