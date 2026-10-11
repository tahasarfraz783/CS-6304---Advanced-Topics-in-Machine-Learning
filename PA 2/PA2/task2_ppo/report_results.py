"""Reproduce the PPO report from saved evidence, without model reruns."""
import csv
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common.data import repo_path, read_jsonl
from common.logging_utils import save_json


ROOT = repo_path('results/task2_ppo')
NAMES = ['midpoint', 'standard', 'clip_0.05', 'clip_0.20', 'clip_0.50', 'kl_0.00', 'kl_0.10', 'kl_0.20']


def read(name, suffix):
    return json.loads((ROOT / f'{name}_{suffix}.json').read_text(encoding='utf-8'))


def link(path, label=None):
    return f'[{label or path.name}](<{path.resolve().as_posix()}>)'


def table(headers, rows):
    def fmt(value):
        if isinstance(value, float):
            return f'{value:.6g}'
        return str(value).replace('|', '\\|').replace('\n', ' ')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(fmt(v) for v in row) + ' |' for row in rows])


def write_csv(path, headers, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def report():
    evaluations = {n: read(n, 'evaluation') for n in NAMES}
    generations = {n: read_jsonl(ROOT / f'{n}_eval.jsonl') for n in NAMES}
    histories = {n: read_jsonl(ROOT / f'{n}_train.jsonl') for n in NAMES if n != 'midpoint'}
    summaries = {n: read(n, 'summary') for n in histories}
    cached = read('cached', 'clipping')['results']
    standard = histories['standard']
    figures = ROOT / 'figures'
    figures.mkdir(exist_ok=True)
    baseline = {r['prompt_id']: r for r in generations['midpoint']}
    rng = np.random.default_rng(6304)
    paired = {}
    for name in NAMES[1:]:
        delta = np.array([r['learned_reward'] - baseline[r['prompt_id']]['learned_reward']
                          for r in generations[name]])
        draws = rng.choice(delta, size=(10000, len(delta)), replace=True).mean(axis=1)
        paired[name] = {'mean_reward_delta': float(delta.mean()),
                        'paired_prompt_bootstrap_95_percent': np.quantile(draws, [.025, .975]).tolist(),
                        'changed_responses': sum(r['response'] != baseline[r['prompt_id']]['response'] for r in generations[name]),
                        'positive_reward_deltas': int((delta > 0).sum()),
                        'negative_reward_deltas': int((delta < 0).sum())}
    save_json(ROOT / 'paired_reward_analysis.json', paired)

    # Every required standard trajectory as a table, not only an endpoint.
    keys = ['update', 'learned_reward', 'kl', 'policy_loss', 'value_loss', 'entropy',
            'clip_fraction', 'policy_grad_norm', 'value_grad_norm', 'response_length',
            'value_explained_variance', 'value_mean', 'return_mean']
    trajectory = [[r[k] for k in keys] for r in standard]
    write_csv(ROOT / 'standard_trajectories.csv', keys, trajectory)
    kl_rows = [[name, r['update'], r['learned_reward'], r['kl'], r['entropy'], r['response_length']]
               for name in ['kl_0.00', 'kl_0.10', 'kl_0.20'] for r in histories[name]]
    write_csv(ROOT / 'kl_trajectories.csv', ['condition', 'update', 'reward', 'kl', 'entropy', 'response_length'], kl_rows)

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for key, ax in zip(['learned_reward', 'kl', 'entropy', 'response_length'], axes.flat):
        for name in ['kl_0.00', 'kl_0.10', 'kl_0.20']:
            rows = histories[name]
            ax.plot([r['update'] for r in rows], [r[key] for r in rows], marker='o', label=name)
        ax.set(xlabel='PPO update', ylabel=key)
        ax.grid(alpha=.25)
        ax.legend()
    fig.tight_layout()
    fig.savefig(figures / 'kl_trajectory_comparison.png', dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot([r['epsilon'] for r in cached], [100*r['outside_ratio_bounds_fraction'] for r in cached], marker='o', label='Outside ratio bounds')
    axes[0].plot([r['epsilon'] for r in cached], [100*r['affected_token_fraction'] for r in cached], marker='o', label='Surrogate actually affected')
    axes[0].set(xlabel='epsilon', ylabel='Cached tokens (%)')
    axes[0].legend()
    for name in ['clip_0.05', 'clip_0.20', 'clip_0.50']:
        rows = histories[name]
        axes[1].plot([r['update'] for r in rows], [r['policy_grad_norm'] for r in rows], marker='o', label=name)
    axes[1].set(xlabel='PPO update', ylabel='Pre-clipping policy gradient L2 norm')
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(figures / 'clipping_comparison.png', dpi=160)
    plt.close(fig)

    notes = {
        63: ('Reward and quality move together (partial improvement)',
             'The request asks for a course and a 90-day host-collaboration campaign. The midpoint answer is truncated mid-item ("Social Media Engagement (Weeks 4"). The continuation finishes its campaign with Day 1–3, Day 4–6, Day 7–90, and a post-collaboration reflection phase. Completion and coverage improve while reward rises. This is a partial quality improvement: neither answer provides a fully developed set of text/audio/video teaching assets, and the proposed schedule is still broad. This assessment uses visible completeness and instruction coverage, not factual verification of marketing effectiveness.'),
        102: ('Reward and quality disagree: reward rises without fixing the error',
              'The prompt asks why hunters can live underwater without equipment. Both answers accept the false premise and say hunters have evolved to survive underwater. The continuation only changes the closing phrase to refer to oceans and aquatic environments; it does not clarify the ambiguity or correct the premise for human hunters. A higher reward here is not evidence of improved factual reliability. This is a local reward-quality mismatch, not proof that PPO learned systematic reward exploitation.'),
        155: ('Reward rises but the final quantitative answer remains wrong',
              'The prompt specifies a central 10,000 lb point load and a 1 square inch cross-section. By symmetry, each reaction is 5,000 lb; equilibrium gives V=5,000 lb on the left half and average shear stress V/A=5,000 psi. The continuation correctly computes V=5,000 lb but invents a 0.5-inch height and concludes 10,000 psi. The midpoint also contains serious errors and is truncated. Reward increases and some intermediate reasoning/completeness improve, yet the requested final answer is still incorrect. This mixed case shows why fluent completion cannot replace task-specific correctness checks.')}
    evidence = []
    qualitative = ['# PPO qualitative evidence and interpretation', '',
                   'Selected paired examples from the same held-out prompt IDs and evaluation seeds. These are assistant qualitative assessments using explicit criteria, not independent human annotations or an aggregate quality score. Selection is illustrative and is not a representative sample.', '']
    for index, (title, interpretation) in notes.items():
        after = generations['standard'][index]
        before = baseline[after['prompt_id']]
        record = {'source_index': index, 'prompt_id': after['prompt_id'], 'title': title,
                  'before_reward': before['learned_reward'], 'after_reward': after['learned_reward'],
                  'reward_delta': after['learned_reward'] - before['learned_reward'],
                  'before_truncated': before['truncated'], 'after_truncated': after['truncated'],
                  'interpretation': interpretation, 'before': before, 'after': after}
        evidence.append(record)
        qualitative += [f'## {title}', '', f"Prompt index: {index}; ID: `{after['prompt_id']}`", '',
                        '**Prompt**', '', '\n'.join(m['content'] for m in after['prompt']), '',
                        f"Reward: **{before['learned_reward']:.6f} → {after['learned_reward']:.6f}**; delta **{record['reward_delta']:+.6f}**.", '',
                        '**Interpretation:** ' + interpretation, '', '**Midpoint response (verbatim)**', '',
                        before['response'], '', '**Standard continuation response (verbatim)**', '', after['response'], '']
    qualitative += ['## Safety and overoptimization limit', '',
                    'No Task 4 safety evaluation artifacts were found under results at report generation. Ordinary held-out responses do not establish safety improvement or regression. A safety-calibrated overoptimization conclusion remains pending Task 4. Do not infer that a higher reward means safer behavior.', '']
    (ROOT / 'qualitative_evidence.md').write_text('\n'.join(qualitative), encoding='utf-8')
    save_json(ROOT / 'qualitative_evidence.json', evidence)

    # Full response appendix and per-condition CSVs mirror the DPO artifacts.
    appendix = ['# PPO: all evaluated examples', '', 'Eight full evaluation conditions, 200 responses each (1,600 total). Smoke evaluation is excluded. Responses are saved model outputs, not endorsed factual answers.', '']
    for name in NAMES:
        rows = generations[name]
        headers = ['source_index', 'prompt_id', 'learned_reward', 'effective_reward', 'kl', 'entropy', 'response_length', 'truncated', 'prompt', 'response']
        write_csv(ROOT / f'{name}_all_examples.csv', headers,
                  [[r.get(k) if k != 'prompt' else json.dumps(r[k], ensure_ascii=False) for k in headers] for r in rows])
        appendix += [f'## {name}', '']
        for r in rows:
            appendix += [f"### Prompt {r['source_index']} — {r['prompt_id']}", '',
                         table(['Reward', 'Effective reward', 'KL', 'Sample entropy', 'Tokens', 'Truncated'],
                               [[r[k] for k in ['learned_reward', 'effective_reward', 'kl', 'entropy', 'response_length', 'truncated']]]), '',
                         '**Prompt**', '', '\n'.join(m['content'] for m in r['prompt']), '', '**Response**', '', r['response'], '']
    (ROOT / 'all_evaluated_examples.md').write_text('\n'.join(appendix), encoding='utf-8')

    s = summaries['standard']
    p = paired['standard']
    low, high = p['paired_prompt_bootstrap_95_percent']
    metric_rows = [[n, *[evaluations[n][k] for k in ['learned_reward', 'effective_reward', 'kl', 'entropy', 'response_length', 'truncated']]] for n in NAMES]
    clipping_rows = [[r['epsilon'], 100*r['outside_ratio_bounds_fraction'], 100*r['affected_token_fraction'], r['clipped_surrogate'],
                     evaluations[f"clip_{r['epsilon']:.2f}"]['learned_reward'], evaluations[f"clip_{r['epsilon']:.2f}"]['kl'],
                     evaluations[f"clip_{r['epsilon']:.2f}"]['response_length'], summaries[f"clip_{r['epsilon']:.2f}"]['max_policy_grad_norm']] for r in cached]
    budget_rows = [[n, summaries[n]['updates'], summaries[n]['generated_tokens'], summaries[n]['skipped_optimizer_steps'], summaries[n]['training_wall_seconds']/60] for n in histories]
    stable = [r['value_explained_variance'] for r in standard]
    report_lines = ['# Task 2 PPO: complete saved results and interpretations', '',
        'Generated from saved artifacts; no training or evaluation reruns. Read this report together with the qualitative evidence and response appendix linked below.', '',
        '## Evidence coverage', '',
        table(['Requirement', 'Evidence / status'], [
            ['20-update standard continuation', 'Complete: all required trajectories, runtime and memory counters saved'],
            ['Cached clipping study', 'Complete: 32 responses / 8,814 tokens; all three epsilon settings'],
            ['Clipping forks', 'Complete: 8 updates and exactly 1,942 generated tokens per fork'],
            ['KL-pressure forks', 'Metrics complete; exact generated-token budget equality NOT satisfied (1,988 / 1,942 / 2,018)'],
            ['Qualitative concordance and disagreement', 'Selected examples assessed with explicit criteria; assistant review, not human ratings'],
            ['Safety-informed interpretation', 'Pending Task 4; no saved safety results found'],
            ['Critic behavior', 'Training GAE-target diagnostics available; no new held-out critic calibration evaluation']]), '',
        '## Protocol and objective correction', '',
        'The deliberate starter defect was torch.maximum instead of torch.minimum in the clipped policy surrogate. The corrected loss is the negative masked mean of min(ratio × advantage, clipped_ratio × advantage). Regression checks cover both advantage signs, gradients, masks, GAE, token alignment, and train/evaluation plumbing.', '',
        'Every fork restores the same supplied policy LoRA and merged critic checkpoint, uses seed 6304, one prompt per update, two PPO epochs, matched prompt schedules and per-update sampling seeds. Standard uses 20 updates; forks use 8. Rollout cap: 512 tokens. Frozen evaluation: the same 200 prompts, 768-token cap, temperature 0.7 and top-p 0.9. Critic adaptation uses a zero-initialized LoRA and trainable score head; no offline critic repair was performed.', '',
        'Local execution deviation: reward scoring uses NF4 (4-bit), rather than the release’s INT8 scorer, to fit local memory. All local final evaluations and branches use the same scorer. Cached terminal rewards remain the supplied release rewards; the cached diagnostic and local reward scores should not be treated as numerically identical scorer regimes.', '',
        'Reference scoring disables the policy adapter and uses the frozen base model. Old rollout policy and reference policy are different roles. Objective probabilities are raw model probabilities; generation uses temperature/top-p. Consequently sampled KL and negative log-probability entropy are proxy diagnostics under this sampling procedure, not exact categorical KL/entropy. Sampled KL may be negative; negative values do not mean mathematical KL is negative or that the model has improved alignment.', '',
        '## Training budgets and stability', '',
        table(['Run', 'Updates', 'Actual generated tokens', 'Skipped steps', 'Training minutes'], budget_rows), '',
        'The clipping forks satisfy equal actual token and update budgets. KL forks match update counts, token ceilings and prompts, but not consumed tokens: the largest difference is 76 tokens (about 3.9% of the 1,942-token branch). This falls short of the explicit equal-generated-token requirement. Their contrasts are descriptive and cannot isolate beta perfectly under that requirement. An exact-token protocol would require additional matched runs; the saved evidence has not been silently relabeled as compliant.', '',
        'Stability statistic: maximum policy gradient L2 norm across optimization epochs, measured before max_grad_norm=1 clipping. Skipped optimizer steps are a second stability indicator. A norm above 1 is an unclipped diagnostic, not the applied gradient magnitude.', '',
        '## Held-out comparison', '',
        table(['Run', 'Learned reward', 'Effective reward', 'Sampled KL/token', 'Sample entropy/token', 'Response tokens', 'Truncation fraction'], metric_rows), '',
        f"Standard mean learned reward changes by {p['mean_reward_delta']:+.6f}; the paired prompt bootstrap 95% interval is [{low:.6f}, {high:.6f}] (10,000 resamples, seed 6304). This measures uncertainty across these prompts at one training/evaluation seed, not across independent training runs. {p['changed_responses']}/200 standard responses differ from midpoint. Small mean changes should not be presented as a robust overall quality improvement.", '',
        'Effective reward additionally subtracts 1 for missing EOS. Standard truncation drops from 10% to 6%; the effective-reward gain therefore reflects both learned score and improved termination. Response length falls from 296.89 to 291.045 tokens; there is no aggregate length-inflation signal in the standard comparison.', '',
        '## Standard continuation: trajectories, memory and runtime', '',
        f"20 updates; {s['generated_tokens']} actual generated tokens; {s['skipped_optimizer_steps']} skipped optimizer steps. Wall-clock including setup/save: {s['wall_seconds']:.2f} seconds ({s['wall_seconds']/60:.2f} minutes). Recorded training-phase wall-clock: {s['training_wall_seconds']:.2f} seconds. This timer includes final saving. Peak PyTorch allocated device memory: {s['peak_vram_bytes']/2**30:.3f} GiB; peak reserved: {s['peak_reserved_vram_bytes']/2**30:.3f} GiB. These recorded counters exceed the setup’s nominal 6 GB dedicated GPU; on Windows they must not be described as verified physical dedicated-VRAM occupancy. No contemporaneous physical/shared-memory breakdown was recorded.", '',
        table(keys, trajectory), '',
        'Interpretation: rollout reward is noisy and nonmonotonic (one changing prompt per update), spanning -0.3738 to 3.1934; first-to-last reward is not a matched-prompt learning estimate. Sampled KL stays close to zero and changes sign. Policy losses are small, and clip fraction is zero on every standard update. Normalized advantages make the first epoch’s loss near zero at ratio=1 without making its gradient zero. The logs show no skipped steps or catastrophic policy-gradient spike.', '',
        f"The critic remains weak: value loss spans {min(r['value_loss'] for r in standard):.4f}–{max(r['value_loss'] for r in standard):.4f}; explained variance is negative on all 20 updates (range {min(stable):.4f} to {max(stable):.4f}, mean {np.mean(stable):.4f}). Critic pre-clipping gradient norms reach {max(r['value_grad_norm'] for r in standard):.3f}. Negative explained variance means squared-error residual variation exceeds target variation; it does not support an accurate baseline. These compare pre-update values with bootstrapped GAE returns on training rollouts, not independent Monte-Carlo held-out targets. First-to-last value loss falls, but prompt/target changes prevent attributing that difference solely to critic learning.", '',
        f"![Standard diagnostics]({(ROOT/'standard_train_diagnostics.png').as_posix()})", '',
        '## Clipping study and Research Question 1', '',
        table(['Epsilon', 'Cached outside bounds %', 'Cached affected %', 'Cached surrogate', 'Fork reward', 'Fork KL/token', 'Fork response tokens', 'Max policy grad L2'], clipping_rows), '',
        'Outside-bound fraction counts ratios beyond [1−epsilon, 1+epsilon]; affected fraction counts tokens where the clipped surrogate is actually smaller. Advantage sign explains the difference. Tightening epsilon increases both cached fractions: affected tokens rise from 0.3290% at 0.50 to 0.4538% at 0.20 and 5.2190% at 0.05. The unclipped cached surrogate is 0.000133770 for all settings. The tighter surrogate is more pessimistic.', '',
        'However, all training-epoch and post-update clip fractions are zero in the short forks. The policy updates stay inside even epsilon=0.05, so epsilon has no active role in their optimization. All three held-out summaries and response texts are identical, with max pre-clipping policy gradient 1.34086 and zero skipped steps. This is evidence of no observable epsilon effect under this small-update budget, not evidence that clipping is generally unnecessary. Cached geometry and actual continuation stability answer different questions.', '',
        f"![Clipping comparison]({(figures/'clipping_comparison.png').as_posix()})", '',
        '## KL-pressure study and Research Question 2', '',
        table(['Condition', 'Update', 'Reward', 'Sampled KL/token', 'Sample entropy', 'Response tokens'], kl_rows), '',
        'Relative to beta=0.10, both beta=0 and beta=0.20 first differ in learned reward, sampled KL, entropy and response length at update 2. Update 1 generates the same response before any beta-dependent update; beta first changes shaped rewards/advantages during optimization. At the next logged rollout all four observables differ simultaneously. At this measurement resolution there is no defensible claim that one observable changes first. Qualitative behavior was not systematically scored at every update, so its onset cannot be ranked.', '',
        'Held-out beta=0 has lower reward (1.70731) than beta=0.10 (1.72747), a slightly larger sampled KL proxy, slightly higher sample entropy and shorter responses. Beta=0.20 also has lower reward (1.71491) than 0.10 and longer responses. Reward and KL do not follow a clear monotonic trade-off across all three conditions. Small proxy differences, one seed and unequal token consumption limit causal conclusions; removing the penalty did not produce a clear reward-overoptimization signature here.', '',
        f"![KL trajectories]({(figures/'kl_trajectory_comparison.png').as_posix()})", '',
        '## Qualitative evidence and Research Question 3', '',
        table(['Example index', 'Criterion', 'Midpoint reward', 'Standard reward', 'Interpretation'],
              [[r['source_index'], r['title'], r['before_reward'], r['after_reward'], r['interpretation']] for r in evidence]), '',
        'Learned reward is useful as one signal but is not a trustworthy substitute for task quality. The course example shows a reward gain accompanying improved completion/coverage. The underwater-hunter example shows a reward gain with essentially unchanged factual failure. The beam example shows improved intermediate steps and fluency while the final quantitative answer remains wrong. These demonstrate local reward-quality disagreement; they do not establish systematic exploitation learned during PPO.', '',
        'Against a strong overoptimization claim: aggregate reward gains are small; sampled drift remains near zero; standard responses become slightly shorter; weaker beta does not yield a higher held-out mean reward. For caution: highly rewarded outputs can still violate instructions or give incorrect answers, and the reward model can respond to wording/completeness rather than correctness. This run does not explore substantial departure from the reference, so it cannot establish how reward reliability behaves under large distribution shift. Task 4 safety evidence is still required before assigning a safety explanation.', '',
        link(ROOT/'qualitative_evidence.md', 'Full selected prompts, before/after responses and assessments'), '',
        '## Files and reproducibility', '',
        link(ROOT/'standard_trajectories.csv'), '', link(ROOT/'kl_trajectories.csv'), '',
        link(ROOT/'paired_reward_analysis.json'), '', link(ROOT/'qualitative_evidence.json'), '',
        link(ROOT/'all_evaluated_examples.md', 'Full appendix: all 1,600 generated responses'), '',
        'Per-condition CSVs contain all responses and their metrics. Original JSON/JSONL evidence, configuration snapshots and checkpoint files are preserved. Regenerate this report with python -m task2_ppo.report_results; regenerate base plots with python -m task2_ppo.export_results.', '',
        '## Remaining requirements', '',
        'Exact consumed-token matching for the KL study is not met. Task 4 safety evidence is absent. Those are genuine gaps, not conclusions supplied by this report. Qualitative judgments are assistant assessments; obtain human review if the course requires it. The NF4 scorer deviation, proxy KL/entropy, weak critic, fixed single seed and finite generation caps must accompany the results.']
    (ROOT / 'all_results.md').write_text('\n'.join(report_lines), encoding='utf-8')
    print('Saved PPO report, qualitative evidence, full appendix, tables and comparison plots:', ROOT)


if __name__ == '__main__':
    report()
