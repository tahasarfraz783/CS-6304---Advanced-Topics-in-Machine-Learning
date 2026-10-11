from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from common.data import repo_path
from task5_feedback.rlvr import exact_reward, extract_designated_final

POLICIES = ('sft', 'rlvr', 'rlaif')
FINAL_LINE = re.compile(r'####\s*[-+]?\d[\d,]*(?:\.\d+)?\s*')


def output_dir(cfg):
    p = repo_path(cfg.get('results_dir', 'results')) / 'task5_feedback'
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_json(path, value):
    path = repo_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rates(labels):
    counts = Counter(labels)
    n = len(labels)
    return {'n': n, 'better_rate': counts['A'] / n if n else None,
            'tie_rate': counts['TIE'] / n if n else None,
            'wrong_rate': counts['B'] / n if n else None,
            'counts': {k: counts[k] for k in ('A', 'TIE', 'B')}}


def verifier_preference(a, b):
    return 'A' if a > b else 'B' if b > a else 'TIE'


def response_metrics(text, gold, tokens, truncated=False):
    correct = exact_reward(text, gold)
    compliant = bool(FINAL_LINE.fullmatch(text.strip().splitlines()[-1])) if text.strip() else False
    compliant = compliant and text.count('####') == 1
    failure = 'correct' if correct else 'missing_final' if extract_designated_final(text) is None else 'wrong_final'
    return {'exact_reward': correct, 'format_compliant': compliant, 'response_tokens': tokens,
            'response_words': len(text.split()), 'truncated': bool(truncated), 'failure_type': failure}


def summarize_math(responses, pairs):
    out = {}
    for policy in POLICIES:
        rows = [r for r in responses if r['policy'] == policy]
        n = len(rows)
        if not n:
            raise ValueError(f'No responses for {policy}')
        result = {'n': n, 'accuracy': sum(r['exact_reward'] for r in rows) / n,
                  'format_compliance': sum(r['format_compliant'] for r in rows) / n,
                  'mean_response_tokens': sum(r['response_tokens'] for r in rows) / n,
                  'mean_response_words': sum(r['response_words'] for r in rows) / n,
                  'truncation_rate': sum(r['truncated'] for r in rows) / n,
                  'failure_counts': dict(Counter(r['failure_type'] for r in rows))}
        comparisons = [p for p in pairs if p['policy'] == policy]
        if comparisons:
            result['vs_sft'] = rates([p['judge_preference'] for p in comparisons])
            result['vs_sft']['win_rate_with_half_ties'] = (sum(p['judge_preference'] == 'A' for p in comparisons) + .5 * sum(p['judge_preference'] == 'TIE' for p in comparisons)) / len(comparisons)
            result['verifier_judge_agreement'] = sum(p['judge_preference'] == p['verifier_preference'] for p in comparisons) / len(comparisons)
            unequal = [p for p in comparisons if p['verifier_preference'] != 'TIE']
            result['agreement_on_unequal_outcomes'] = sum(p['judge_preference'] == p['verifier_preference'] for p in unequal) / len(unequal) if unequal else None
            result['unequal_outcome_pairs'] = len(unequal)
            result['judge_distinction_on_verifier_ties'] = sum(p['judge_preference'] != 'TIE' for p in comparisons if p['verifier_preference'] == 'TIE')
        else:
            result['vs_sft'] = {'n': n, 'better_rate': 0., 'tie_rate': 1., 'wrong_rate': 0., 'win_rate_with_half_ties': .5, 'self_comparison': True}
        out[policy] = result
    return out


def save_table(path, rows):
    if rows:
        with path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
