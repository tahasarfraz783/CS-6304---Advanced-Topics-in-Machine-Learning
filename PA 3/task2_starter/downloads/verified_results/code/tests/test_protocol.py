import copy
import random
import tempfile
import unittest
from pathlib import Path
from task2.common import rows, jsonl, repair_jsonl, write, read
from task2.data import Sampler, ground_pair, mismatches, pick_natural, audit
from task2.scoring import normalize, vqa_score


def fixture():
    pool = [dict(category_id=1, name='person', positive=[1, 2], negative=[3, 4], bins={'1':[1], '2':[2], '3':[], '4':[]})]
    caps = [dict(id=f'c{i}', image_id=i, split='train2014', target='caption', kind='caption') for i in range(18)]
    nat = [ground_pair(pool, 'presence', random.Random(1), 'train2014', 1)]
    return dict(train=dict(captions=caps, pools=pool, natural=nat))


class ProtocolTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize('The TWO cats!'), '2 cats')
        self.assertEqual(normalize('1,000'), '1000')
        self.assertEqual(normalize('3.14'), '3.14')
        self.assertEqual(normalize('dont'), "don't")
        self.assertEqual(normalize(''), '')

    def test_soft_consensus_not_capped_count(self):
        self.assertAlmostEqual(vqa_score('yes', ['yes']*3+['no']*7), .9)
        self.assertEqual(vqa_score('', ['yes']*10), 0)
        self.assertEqual(vqa_score('two', ['2']*10), 1)

    def test_stage1_exactly_two_passes(self):
        m = fixture()
        s = Sampler(m, 6304)
        ids = [r['id'] for _ in range(2) for r in s.batch(1, 18)[0]]
        self.assertEqual(sorted(ids[:18]), sorted(ids[18:]))
        self.assertEqual(len(set(ids[:18])), 18)

    def test_sampler_exact_recovery_across_stages(self):
        m = fixture()
        a = Sampler(m, 6304)
        a.batch(1)
        a.batch(2)
        state = a.state_dict()
        expected = [a.batch(stage) for stage in [2, 2, 3, 3]]
        b = Sampler(m, 0)
        b.load_state_dict(state)
        self.assertEqual(expected, [b.batch(stage) for stage in [2, 2, 3, 3]])

    def test_pair_draws_stay_adjacent(self):
        s = Sampler(fixture(), 6304)
        for stage in [2, 3]:
            batch, counts = s.batch(stage)
            self.assertEqual(sum(counts.values()), 16)
            for a, b in zip(batch[::2], batch[1::2]):
                if a['kind'] != 'caption':
                    self.assertEqual(a['pair_id'], b['pair_id'])
                    self.assertNotEqual(a['target'], b['target'])

    def test_mismatch_excludes_both_images(self):
        pool = fixture()['train']['pools']
        pairs = [ground_pair(pool, 'presence', random.Random(i), 'val2014', i) for i in range(30)]
        # Deliberately use completely separate images to make exclusion check unambiguous.
        for i, p in enumerate(pairs):
            for j, r in enumerate(p):
                r['image_id'] = i*2+j
        mapping = mismatches(pairs, random.Random(6304))
        for p in pairs:
            for r in p:
                self.assertNotIn(mapping[r['id']], {x['image_id'] for x in p})

    def test_partial_jsonl_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'data.jsonl'
            jsonl(p, {'i':1})
            with open(p, 'a') as f:
                f.write('{"i":')
            repair_jsonl(p)
            jsonl(p, {'i':2})
            self.assertEqual(rows(p), [{'i':1}, {'i':2}])

    def test_split_audit_rejects_leak(self):
        r = dict(image_id=1, split='val2014')
        m = {k:dict(captions=[r] if k != 'train' else [], natural=[], grounding=[]) for k in ['train', 'dev', 'test']}
        with self.assertRaises(AssertionError):
            audit(m)

    def test_confidence_intervals_and_paired_differences(self):
        try:
            import numpy
        except ImportError:
            self.skipTest('numpy needed')
        from task2.scoring import summarize
        examples = []
        for pair in range(4):
            for c in ['correct', 'swap', 'mismatched', 'none']:
                for j in range(2):
                    ok = c == 'correct'
                    examples.append(dict(suite='grounding', kind='presence', pair_id=str(pair), condition=c,
                        prediction='yes' if j else 'no', score=float(ok), exact=ok, nll=1. if ok else 2.,
                        generation_seconds=.1, partner_match=not ok))
        summary = summarize(examples, 4000)
        diff = next(r for r in summary if r['kind'] == 'all' and r['condition'] == 'correct_advantage_over_swap')
        self.assertEqual(diff['accuracy'], 1)
        self.assertEqual(diff['accuracy_lo'], 1)
        self.assertEqual(diff['nll'], 1)

    def test_bundled_official_selection_quotas_hash_and_mismatches(self):
        from collections import Counter
        from task2.common import digest
        path = Path(__file__).resolve().parents[1]/'inputs'/'selected_manifest.json'
        if not path.exists():
            self.skipTest('Bundled data selection not present')
        m = read(path)
        self.assertEqual(digest({k:v for k,v in m.items() if k != 'selection_hash'}), m['selection_hash'])
        self.assertEqual(len(m['train']['captions']), 18000)
        self.assertEqual(set(Counter(r['image_id'] for r in m['train']['captions']).values()), {3})
        for partition, expected in [('train', [640,256,640]), ('dev', [12,8,12]), ('test', [36,24,36])]:
            counts = Counter(p[0]['kind'] for p in m[partition]['natural'])
            self.assertEqual([counts[k] for k in ['yes/no','number','other']], expected)
        self.assertEqual(audit(m), {'train':8876, 'dev':208, 'test':320})
        train_ids = {r['image_id'] for r in m['train']['captions']} | {r['image_id'] for p in m['train']['natural'] for r in p}
        for pool in m['train']['pools']:
            self.assertTrue(set(pool['positive']) <= train_ids)
            self.assertTrue(set(pool['negative']) <= train_ids)
            self.assertFalse(set(pool['positive']) & set(pool['negative']))
        for suite in ['grounding', 'natural']:
            allowed = {r['image_id'] for p in m['test'][suite] for r in p}
            for pair in m['test'][suite]:
                banned = {r['image_id'] for r in pair}
                for row in pair:
                    mismatch = m['mismatches'][suite][row['id']]
                    self.assertIn(mismatch, allowed)
                    self.assertNotIn(mismatch, banned)

    def test_default_preparation_reuses_bundle_without_annotation_download(self):
        from task2.data import prepare
        from unittest.mock import patch
        base = Path(__file__).resolve().parents[1]
        if not (base/'inputs'/'selected_manifest.json').exists():
            self.skipTest('Bundled selection absent')
        class Progress:
            def emit(self, *args, **kwargs):
                pass
        with tempfile.TemporaryDirectory() as d, patch('task2.data.annotations', side_effect=AssertionError('Unexpected download')):
            m = prepare(Path(d), read(base/'config.json'), Progress())
            self.assertEqual(len(m['train']['captions']), 18000)
            self.assertTrue((Path(d)/'prepared'/'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
