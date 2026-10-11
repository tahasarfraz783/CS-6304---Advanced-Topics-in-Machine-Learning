import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from common.data import load_yaml, read_jsonl, write_jsonl
from task5_feedback.analysis import response_metrics, summarize_math, verifier_preference
from task5_feedback.rlvr import exact_reward
from task5_feedback.score_perturbations import load_diagnostic_groups, score_groups, summarize_diagnostics

class FakeJudge:
    def compare(self, problem, a, b):
        return 'A'

class FeedbackTests(unittest.TestCase):
    def test_repack_preserves_tensor_bytes(self):
        import struct
        from task5_feedback.judge_loading import repack_checkpoint
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            source.mkdir()
            payloads = {f'tensor{i}': struct.pack('<f', float(i)) for i in range(3)}
            header = {name: {'dtype': 'F32', 'shape': [1], 'data_offsets': [i * 4, i * 4 + 4]}
                      for i, name in enumerate(payloads)}
            encoded = json.dumps(header).encode()
            (source / 'model.safetensors').write_bytes(struct.pack('<Q', len(encoded)) + encoded + b''.join(payloads.values()))
            (source / 'config.json').write_text('{}')
            dest = repack_checkpoint(source, Path(temp) / 'dest', shard_bytes=8)
            index = json.loads((dest / 'model.safetensors.index.json').read_text())
            self.assertEqual(len(set(index['weight_map'].values())), 2)
            for name, filename in index['weight_map'].items():
                data = (dest / filename).read_bytes()
                size = struct.unpack('<Q', data[:8])[0]
                info = json.loads(data[8:8 + size])[name]
                begin, end = info['data_offsets']
                self.assertEqual(data[8 + size + begin:8 + size + end], payloads[name])

    def test_report_pipeline(self):
        from task5_feedback.analysis import output_dir, fingerprint, save_json
        from task5_feedback.evaluate_math import policy_specs
        from task5_feedback.compare_feedback import main
        cfg = load_yaml('configs/feedback.yaml')
        with tempfile.TemporaryDirectory() as temp:
            cfg['results_dir'] = temp
            root = output_dir(cfg)
            for dataset in ('gsm', 'transfer'):
                source = read_jsonl(cfg['paths']['gsm_eval' if dataset == 'gsm' else 'math_transfer_eval'])
                signature = fingerprint({'rows': source, 'base': cfg['base_model'], 'policies': policy_specs(cfg),
                    'seed': cfg['seed'], 'cap': cfg['math_max_new_tokens'],
                    'prompt_cap': cfg.get('math_max_prompt_length', 1024), 'decoding': 'greedy'})
                responses = [{'policy': name, **response_metrics('#### 1', 1, 5)}
                             for name in ('sft', 'rlvr', 'rlaif') for _ in source]
                pairs = [{'policy': name, 'judge_preference': 'TIE', 'verifier_preference': 'TIE'}
                         for name in ('rlvr', 'rlaif') for _ in source]
                save_json(root / f'{dataset}_summary.json', {'config': cfg, 'signature': signature,
                    'policies': summarize_math(responses, pairs), 'judge_cost': {}})
            groups = load_diagnostic_groups(cfg['paths']['task5_diagnostics'])
            _, pairs = score_groups(groups, FakeJudge())
            write_jsonl(root / 'diagnostic_pairs.jsonl', pairs)
            save_json(root / 'diagnostic_summary.json', {**summarize_diagnostics(pairs),
                'source_fingerprint': fingerprint(list(groups.values())), 'config': cfg, 'judge_cost': {}})
            with patch('task5_feedback.compare_feedback.load_yaml', return_value=cfg), patch('sys.argv', ['compare_feedback']):
                main()
            comparison = json.loads((root / 'comparison.json').read_text())
            self.assertEqual(len(comparison['math']), 6)
            self.assertEqual(len(comparison['diagnostics']), 10)
            self.assertEqual(comparison['transfer_changes']['rlvr']['accuracy_drop'], 0)
            report = (root / 'all_results.md').read_text(encoding='utf-8')
            self.assertIn('gold_distractor_wrong_final', report)
            self.assertIn('Feedback-source discussion', report)

    def test_designated_final_and_format(self):
        self.assertEqual(exact_reward('Gold candidate 9, discarded.\n#### 8', '9'), 0)
        self.assertEqual(exact_reward('#### 9\nRevised:\n#### 8', '9'), 0)
        self.assertEqual(exact_reward('9 is the answer', '9'), 0)
        self.assertEqual(exact_reward('#### 1,000.0', '1000'), 1)
        r = response_metrics('#### 9\nextra text', 9, 12)
        self.assertEqual(r['exact_reward'], 1)
        self.assertFalse(r['format_compliant'])
        self.assertTrue(response_metrics('Reasoning\n#### 9', 9, 12)['format_compliant'])
        self.assertFalse(response_metrics('#### 8\n#### 9', 9, 12)['format_compliant'])

    def test_supplied_diagnostics(self):
        cfg = load_yaml('configs/feedback.yaml')
        groups = load_diagnostic_groups(cfg['paths']['task5_diagnostics'])
        scores, pairs = score_groups(groups, FakeJudge())
        self.assertEqual(len(scores), 100)
        self.assertEqual(sum(p['category'] == 'all_pairs' for p in pairs), 200)
        for pid in groups:
            self.assertAlmostEqual(sum(r['ai_group_win_rate'] for r in scores if str(r['problem_id']) == pid), 2.5)
        result = summarize_diagnostics(pairs)
        self.assertEqual(result['rlvr']['Sreason'], 0)
        self.assertEqual(result['rlvr']['Soutcome'], 1)
        self.assertEqual(result['rlvr']['categories']['persuasive_filler_correct']['tie_rate'], 1)
        self.assertEqual(result['rlvr']['distractor_robustness'], 1)
        self.assertEqual(result['rlvr']['categories']['clean_correct']['tie_rate'], 1)

    def test_summary_denominators(self):
        responses = [{'policy': name, **response_metrics('#### ' + str(i), 1, 10 + i)}
                     for name in ('sft', 'rlvr', 'rlaif') for i in range(2)]
        pairs = [{'policy': name, 'judge_preference': pref, 'verifier_preference': verifier_preference(i, 0)}
                 for name in ('rlvr', 'rlaif') for i, pref in enumerate(('TIE', 'A'))]
        result = summarize_math(responses, pairs)
        self.assertEqual(result['rlvr']['accuracy'], .5)
        self.assertEqual(result['rlvr']['vs_sft']['win_rate_with_half_ties'], .75)
        self.assertEqual(result['rlvr']['verifier_judge_agreement'], 1)
        self.assertEqual(result['rlvr']['agreement_on_unequal_outcomes'], 1)
        self.assertEqual(result['sft']['vs_sft']['win_rate_with_half_ties'], .5)

if __name__ == '__main__':
    unittest.main()
