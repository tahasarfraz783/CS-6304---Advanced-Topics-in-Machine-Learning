from __future__ import annotations

import argparse
import itertools
import time
from collections import defaultdict
from common.data import load_yaml, read_jsonl, write_jsonl
from task5_feedback.analysis import output_dir, save_json, rates, verifier_preference, fingerprint
from task5_feedback.rlvr import exact_reward
from task5_feedback.rlaif import PairwiseAIJudge

EXPECTED_VARIANTS = {'clean_correct', 'corrupt_reasoning_correct_final', 'good_reasoning_wrong_final',
                     'persuasive_filler_correct', 'gold_distractor_wrong_final'}


def load_diagnostic_groups(path):
    rows = read_jsonl(path)
    if len(rows) != 100:
        raise ValueError(f'Expected fixed 100-response diagnostic set; got {len(rows)}')
    groups = defaultdict(dict)
    for row in rows:
        pid, variant = str(row['problem_id']), row['variant_type']
        if variant not in EXPECTED_VARIANTS or variant in groups[pid]:
            raise ValueError(f'Unexpected or duplicate variant: {pid}/{variant}')
        if row.get('manual_validation') is not True:
            raise ValueError(f'Unvalidated diagnostic: {pid}/{variant}')
        groups[pid][variant] = row
    if len(groups) != 20:
        raise ValueError('Expected 20 diagnostic problems')
    for pid, variants in groups.items():
        if set(variants) != EXPECTED_VARIANTS:
            raise ValueError(f'Problem {pid} missing variants')
        if len({r['question'] for r in variants.values()}) != 1 or len({str(r['gold_final']) for r in variants.values()}) != 1:
            raise ValueError(f'Inconsistent problem/gold for {pid}')
    return groups


def score_groups(groups, judge):
    scores, comparisons = [], []
    clean = 'clean_correct'
    for pid, variants in groups.items():
        rewards = {v: exact_reward(r['response'], r['gold_final']) for v, r in variants.items()}
        for v, r in variants.items():
            if rewards[v] != r['expected_exact_reward']:
                raise ValueError(f'Verifier disagrees with validated reward: {pid}/{v}')
        all_pairs = {}
        wins = dict.fromkeys(variants, 0.)
        for va, vb in itertools.combinations(sorted(variants), 2):
            pref = judge.compare(variants[va]['question'], variants[va]['response'], variants[vb]['response'])
            if pref not in {'A', 'B', 'TIE'}:
                raise ValueError(f'Invalid judge preference: {pref}')
            all_pairs[va, vb] = pref
            wins[va] += 1. if pref == 'A' else .5 if pref == 'TIE' else 0.
            wins[vb] += 1. if pref == 'B' else .5 if pref == 'TIE' else 0.
        for v, r in variants.items():
            scores.append({**r, 'exact_reward': rewards[v], 'ai_group_win_rate': wins[v] / 4})
            # The clean category is an identity control, with no diagnostically worse member.
            if v == clean:
                ai_pref = 'TIE'
            elif (clean, v) in all_pairs:
                ai_pref = all_pairs[clean, v]
            else:
                ai_pref = {'A': 'B', 'B': 'A', 'TIE': 'TIE'}[all_pairs[v, clean]]
            comparisons.append({'problem_id': pid, 'category': v, 'a_variant': clean, 'b_variant': v,
                                'is_identity_control': v == clean,
                                'rlvr_preference': verifier_preference(rewards[clean], rewards[v]),
                                'rlaif_preference': ai_pref,
                                'question': r['question'], 'gold_final': r['gold_final'],
                                'a_response': variants[clean]['response'], 'b_response': r['response']})
        for (va, vb), pref in all_pairs.items():
            comparisons.append({'problem_id': pid, 'category': 'all_pairs', 'a_variant': va, 'b_variant': vb,
                                'rlvr_preference': verifier_preference(rewards[va], rewards[vb]), 'rlaif_preference': pref})
    return scores, comparisons


def summarize_diagnostics(pairs):
    result = {}
    for mechanism in ('rlvr', 'rlaif'):
        key = mechanism + '_preference'
        categories = {v: rates([r[key] for r in pairs if r['category'] == v]) for v in sorted(EXPECTED_VARIANTS)}
        result[mechanism] = {'categories': categories,
            'Sreason': categories['corrupt_reasoning_correct_final']['better_rate'],
            'Soutcome': categories['good_reasoning_wrong_final']['better_rate'],
            'distractor_robustness': categories['gold_distractor_wrong_final']['better_rate'],
            'filler_preference_rate': categories['persuasive_filler_correct']['wrong_rate']}
    all_pairs = [r for r in pairs if r['category'] == 'all_pairs']
    result['all_pairs_agreement'] = sum(r['rlvr_preference'] == r['rlaif_preference'] for r in all_pairs) / len(all_pairs)
    result['protocol'] = 'All 10 unordered pairs per problem determine AI group win rates. Controlled comparisons place clean in A. Clean category is an identity/tie control, not a sensitivity estimate. Filler B is less relevant; a preference for B is filler susceptibility, not proof of mathematical error. Soutcome uses only clean vs good_reasoning_wrong_final; distractor pairs are reported separately.'
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/feedback.yaml')
    args = ap.parse_args()
    cfg = load_yaml(args.config)
    groups = load_diagnostic_groups(cfg['paths']['task5_diagnostics'])
    root = output_dir(cfg)
    judge = PairwiseAIJudge(cfg, root / 'judge_cache.json')
    initial = len(judge.cache)
    start = time.perf_counter()
    scores, pairs = score_groups(groups, judge)
    write_jsonl(root / 'diagnostic_scores.jsonl', scores)
    write_jsonl(root / 'diagnostic_pairs.jsonl', pairs)
    save_json(root / 'diagnostic_summary.json', {**summarize_diagnostics(pairs),
              'source_fingerprint': fingerprint(list(groups.values())), 'config': cfg,
              'judge_cost': {'requested_pairs': len(groups) * 10, 'new_cache_entries': len(judge.cache) - initial,
                             'elapsed_seconds': time.perf_counter() - start}})
    print('Scored 100 responses, 200 unordered judge pairs, and 80 controlled perturbation pairs.', flush=True)


if __name__ == '__main__':
    main()
