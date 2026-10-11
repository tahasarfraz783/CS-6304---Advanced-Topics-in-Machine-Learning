from __future__ import annotations

import argparse
import json
from common.data import load_yaml, read_jsonl
from task5_feedback.analysis import output_dir, save_json, save_table, POLICIES, fingerprint


def percent(value):
    return 'N/A' if value is None else f'{100 * value:.1f}%'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/feedback.yaml')
    args = ap.parse_args()
    cfg = load_yaml(args.config)
    root = output_dir(cfg)
    summaries = {}
    for name in ('gsm', 'transfer', 'diagnostic'):
        path = root / f'{name}_summary.json'
        if not path.exists():
            raise SystemExit(f'Missing {path}; run the corresponding evaluation first')
        summaries[name] = json.loads(path.read_text(encoding='utf-8'))
        if summaries[name]['config'] != cfg:
            raise ValueError(f'{name} results came from a different configuration')
    for dataset in ('gsm', 'transfer'):
        source = read_jsonl(cfg['paths']['gsm_eval' if dataset == 'gsm' else 'math_transfer_eval'])
        from task5_feedback.evaluate_math import policy_specs
        signature = fingerprint({'rows': source, 'base': cfg['base_model'], 'policies': policy_specs(cfg),
                                 'seed': cfg['seed'], 'cap': cfg['math_max_new_tokens'], 'prompt_cap': cfg.get('math_max_prompt_length', 1024), 'decoding': 'greedy'})
        if summaries[dataset]['signature'] != signature:
            raise ValueError(f'{dataset} summary does not match current source/configuration')
    from task5_feedback.score_perturbations import load_diagnostic_groups
    groups = load_diagnostic_groups(cfg['paths']['task5_diagnostics'])
    if summaries['diagnostic']['source_fingerprint'] != fingerprint(list(groups.values())):
        raise ValueError('Diagnostic summary does not match current source data')
    math_rows, drops = [], {}
    lines = ['# Task 5: RLVR versus RLAIF', '',
             'Fixed course checkpoints; matched greedy decoding and completion limits. Accuracy uses the supplied designated-final verifier. Judge results compare each adapted policy (A) with SFT (B). Win rate includes half credit for ties. SFT self-comparison is a defined 0.5 baseline and requires no judge call.', '',
             '| Domain | Policy | Accuracy | Judge win rate vs SFT | Format | Mean tokens | Verifier/judge agreement |',
             '|---|---|---:|---:|---:|---:|---:|']
    for dataset in ('gsm', 'transfer'):
        for policy in POLICIES:
            r = summaries[dataset]['policies'][policy]
            win = r['vs_sft']['win_rate_with_half_ties']
            agreement = r.get('verifier_judge_agreement')
            math_rows.append({'dataset': dataset, 'policy': policy, 'n': r['n'], 'accuracy': r['accuracy'],
                              'ai_win_rate_vs_sft': win, 'format_compliance': r['format_compliance'],
                              'mean_response_tokens': r['mean_response_tokens'], 'verifier_judge_agreement': agreement,
                              'truncation_rate': r['truncation_rate']})
            lines.append(f"| {dataset} | {policy} | {percent(r['accuracy'])} | {percent(win)} | {percent(r['format_compliance'])} | {r['mean_response_tokens']:.1f} | {percent(agreement)} |")
    lines += ['', '## Transfer change', '', 'Drops are GSM minus SVAMP, so negative values indicate improvement. These are fixed-set descriptive estimates; differences do not establish optimizer causality or general reasoning ability.', '',
              '| Policy | Accuracy drop | AI win-rate drop | Token-length change (SVAMP minus GSM) |', '|---|---:|---:|---:|']
    for policy in POLICIES:
        g, t = (summaries[d]['policies'][policy] for d in ('gsm', 'transfer'))
        drops[policy] = {'accuracy_drop': g['accuracy'] - t['accuracy'],
                         'ai_win_rate_drop': g['vs_sft']['win_rate_with_half_ties'] - t['vs_sft']['win_rate_with_half_ties'],
                         'response_token_change': t['mean_response_tokens'] - g['mean_response_tokens']}
        d = drops[policy]
        lines.append(f"| {policy} | {percent(d['accuracy_drop'])} | {percent(d['ai_win_rate_drop'])} | {d['response_token_change']:.1f} |")
    lines += ['', '## Controlled feedback sensitivity', '', summaries['diagnostic']['protocol'], '',
              '| Mechanism | Category | N | Better | Tie | Wrong / filler preference |', '|---|---|---:|---:|---:|---:|']
    diagnostic_rows = []
    for mechanism in ('rlvr', 'rlaif'):
        d = summaries['diagnostic'][mechanism]
        for category, r in d['categories'].items():
            diagnostic_rows.append({'mechanism': mechanism, 'category': category, 'n': r['n'],
                                    **{k: r[k] for k in ('better_rate', 'tie_rate', 'wrong_rate')}})
            lines.append(f"| {mechanism} | {category} | {r['n']} | {percent(r['better_rate'])} | {percent(r['tie_rate'])} | {percent(r['wrong_rate'])} |")
    for mechanism in ('rlvr', 'rlaif'):
        d = summaries['diagnostic'][mechanism]
        lines += ['', f"{mechanism}: Sreason={percent(d['Sreason'])}; Soutcome={percent(d['Soutcome'])}; distractor robustness={percent(d['distractor_robustness'])}; filler preference={percent(d['filler_preference_rate'])}.", '']
    lines += ['## Failure types', '']
    for dataset in ('gsm', 'transfer'):
        for policy in POLICIES:
            r = summaries[dataset]['policies'][policy]
            lines.append(f"- {dataset}/{policy}: {r['failure_counts']}; truncation rate {percent(r['truncation_rate'])}.")
    pairs = read_jsonl(root / 'diagnostic_pairs.jsonl')
    lines += ['', '## Qualitative diagnostic evidence', '', 'Each example gives a clean response (A) and its controlled variant (B). Selection prioritizes verifier/judge disagreement, then a stable problem ID.']
    for category in ('corrupt_reasoning_correct_final', 'persuasive_filler_correct', 'good_reasoning_wrong_final', 'gold_distractor_wrong_final'):
        candidates = [p for p in pairs if p['category'] == category]
        p = sorted(candidates, key=lambda p: (p['rlvr_preference'] == p['rlaif_preference'], str(p['problem_id'])))[0]
        lines += ['', f"### {category}: problem {p['problem_id']}", '', p['question'], '',
                  f"Gold: {p['gold_final']}. Verifier: {p['rlvr_preference']}; AI judge: {p['rlaif_preference']}.", '',
                  'A (clean):', '', '```text', p['a_response'], '```', '', 'B (variant):', '', '```text', p['b_response'], '```']
    rv, ai = (summaries['diagnostic'][m] for m in ('rlvr', 'rlaif'))
    lines += ['', '## Feedback-source discussion and research questions', '',
              f"1. The verifier ties on reasoning-only corruption at {percent(rv['categories']['corrupt_reasoning_correct_final']['tie_rate'])}; the judge prefers clean reasoning at {percent(ai['Sreason'])}. This measures extra ranking coverage on these controlled examples. A verifier tie is legitimate invariance when both designated finals are correct.", '',
              f"2. The judge prefers persuasive filler at {percent(ai['filler_preference_rate'])}, and wrongly prefers corrupted reasoning at {percent(ai['categories']['corrupt_reasoning_correct_final']['wrong_rate'])}. Read reasoning sensitivity alongside these rates: greater discrimination alone does not establish reasoning quality.", '',
              f"3. Verifier outcome sensitivity is {percent(rv['Soutcome'])} and distractor robustness is {percent(rv['distractor_robustness'])}; judge values are {percent(ai['Soutcome'])} and {percent(ai['distractor_robustness'])}. The checker ignores intermediate gold distractors, but cannot assess reasoning or relevance. The judge has wider feedback coverage with model-dependent preference errors. Neither reward scale represents a calibrated utility.", '',
              '4. The transfer table quantifies accuracy and preference changes for each policy, while failure counts and lengths show how behavior shifts. The fixed 100-example SVAMP sample covers a limited distribution, and a judge preference advantage without an exact-accuracy advantage provides weaker evidence of general reasoning. These supplied checkpoints support an observational comparison of feedback sources, not an isolated causal experiment.', '',
              'Exact checking is deterministic and cheap. Pairwise AI feedback requires model inference and persistent caching; the measured times below cover comparisons and cache access, excluding model loading. Cache reuse reduces rerun cost. Diagnostic group scores require ten unordered comparisons per five-response group. The fixed course judge uses deterministic hash-based A/B orientation balancing; a single orientation per pair does not fully eliminate position bias.', '']
    for name, summary in summaries.items():
        lines.append(f"- {name} judge cost: {summary['judge_cost']}")
    save_table(root / 'math_comparison.csv', math_rows)
    save_table(root / 'diagnostic_comparison.csv', diagnostic_rows)
    save_json(root / 'comparison.json', {'math': math_rows, 'diagnostics': diagnostic_rows, 'transfer_changes': drops, 'summaries': summaries})
    (root / 'all_results.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Saved {root / "all_results.md"}')


if __name__ == '__main__':
    main()
