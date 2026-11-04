"""VQA punctuation/digit/article policy; contraction table from official VQA API.

We normalize every reference and prediction, including unanimous references, as
required by this assignment (the historic evaluator conditionally normalized).
"""
import re
from .common import read
from pathlib import Path

NUMBERS = dict(zip('none zero one two three four five six seven eight nine ten'.split(),
                   '0 0 1 2 3 4 5 6 7 8 9 10'.split()))
PUNCT = [';', '/', '[', ']', '"', '{', '}', '(', ')', '=', '+', '\\', '_', '-',
         '>', '<', '@', '`', ',', '?', '!']
PERIOD = re.compile(r'(?!<=\d)(\.)(?!\d)')
COMMA = re.compile(r'(\d)(,)(\d)')
CONTRACTIONS = read(Path(__file__).with_name('contractions.json'))


def normalize(text):
    text = text.replace('\n', ' ').replace('\t', ' ').strip()
    out = text
    for p in PUNCT:
        out = out.replace(p, '' if p+' ' in text or ' '+p in text or COMMA.search(text) else ' ')
    out = PERIOD.sub('', out)
    words = [NUMBERS.get(w, w) for w in out.lower().split()]
    return ' '.join(CONTRACTIONS.get(w, w) for w in words if w not in {'a', 'an', 'the'})


def vqa_score(prediction, answers):
    if len(answers) != 10:
        raise ValueError('VQA requires all ten human answers')
    p = normalize(prediction)
    a = [normalize(x) for x in answers]
    return sum(min(1., sum(p == v for j, v in enumerate(a) if j != i)/3.)
               for i in range(10))/10.


def summarize(examples, resamples=4000, seed=6304):
    """Matched complete-pair percentile bootstrap, separately per suite/type."""
    import numpy as np
    output = []
    for suite in sorted({x['suite'] for x in examples}):
        sr = [x for x in examples if x['suite'] == suite]
        for kind in ['all'] + sorted({x['kind'] for x in sr}):
            subset = [x for x in sr if kind == 'all' or x['kind'] == kind]
            ids = sorted({x['pair_id'] for x in subset})
            rng = np.random.default_rng(seed)
            indices = rng.integers(0, len(ids), (resamples, len(ids)))
            matrices = {}
            for condition in ['correct', 'swap', 'mismatched', 'none']:
                pairs = [[r for r in subset if r['pair_id'] == pid and r['condition'] == condition] for pid in ids]
                if any(len(p) != 2 for p in pairs):
                    raise ValueError('Incomplete final evaluation; cannot bootstrap')
                metrics = {
                    'accuracy': [sum(r['score'] for r in p)/2 for p in pairs],
                    'pair_accuracy': [float(all(r['exact'] for r in p)) for p in pairs],
                    'identical_rate': [float(normalize(p[0]['prediction']) == normalize(p[1]['prediction'])) for p in pairs],
                    'empty_rate': [sum(not normalize(r['prediction']) for r in p)/2 for p in pairs],
                    'nll': [sum(r['nll'] for r in p)/2 for p in pairs],
                    'seconds_per_answer': [sum(r['generation_seconds'] for r in p)/2 for p in pairs],
                    'partner_follow_rate': [sum(r['partner_match'] for r in p)/2 for p in pairs],
                    'unsupported_rate': [sum(not r['exact'] and not r['partner_match'] for r in p)/2 for p in pairs]
                }
                matrices[condition] = {k: np.asarray(v, dtype=float) for k, v in metrics.items()}
                row = dict(suite=suite, kind=kind, condition=condition, pairs=len(ids))
                for metric, values in matrices[condition].items():
                    lo, hi = np.quantile(values[indices].mean(1), [.025, .975])
                    row.update({metric: float(values.mean()), metric+'_lo': float(lo), metric+'_hi': float(hi)})
                output.append(row)
            diff = dict(suite=suite, kind=kind, condition='correct_advantage_over_swap', pairs=len(ids))
            for name, values in {
                'accuracy': matrices['correct']['accuracy']-matrices['swap']['accuracy'],
                'nll': matrices['swap']['nll']-matrices['correct']['nll']
            }.items():
                lo, hi = np.quantile(values[indices].mean(1), [.025, .975])
                diff.update({name: float(values.mean()), name+'_lo': float(lo), name+'_hi': float(hi)})
            output.append(diff)
    return output
