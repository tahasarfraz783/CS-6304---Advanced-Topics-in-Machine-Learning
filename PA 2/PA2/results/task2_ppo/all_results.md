# Task 2 PPO: complete saved results and interpretations

Generated from saved artifacts; no training or evaluation reruns. Read this report together with the qualitative evidence and response appendix linked below.

## Evidence coverage

| Requirement | Evidence / status |
| --- | --- |
| 20-update standard continuation | Complete: all required trajectories, runtime and memory counters saved |
| Cached clipping study | Complete: 32 responses / 8,814 tokens; all three epsilon settings |
| Clipping forks | Complete: 8 updates and exactly 1,942 generated tokens per fork |
| KL-pressure forks | Metrics complete; exact generated-token budget equality NOT satisfied (1,988 / 1,942 / 2,018) |
| Qualitative concordance and disagreement | Selected examples assessed with explicit criteria; assistant review, not human ratings |
| Safety-informed interpretation | Pending Task 4; no saved safety results found |
| Critic behavior | Training GAE-target diagnostics available; no new held-out critic calibration evaluation |

## Protocol and objective correction

The deliberate starter defect was torch.maximum instead of torch.minimum in the clipped policy surrogate. The corrected loss is the negative masked mean of min(ratio × advantage, clipped_ratio × advantage). Regression checks cover both advantage signs, gradients, masks, GAE, token alignment, and train/evaluation plumbing.

Every fork restores the same supplied policy LoRA and merged critic checkpoint, uses seed 6304, one prompt per update, two PPO epochs, matched prompt schedules and per-update sampling seeds. Standard uses 20 updates; forks use 8. Rollout cap: 512 tokens. Frozen evaluation: the same 200 prompts, 768-token cap, temperature 0.7 and top-p 0.9. Critic adaptation uses a zero-initialized LoRA and trainable score head; no offline critic repair was performed.

Local execution deviation: reward scoring uses NF4 (4-bit), rather than the release’s INT8 scorer, to fit local memory. All local final evaluations and branches use the same scorer. Cached terminal rewards remain the supplied release rewards; the cached diagnostic and local reward scores should not be treated as numerically identical scorer regimes.

Reference scoring disables the policy adapter and uses the frozen base model. Old rollout policy and reference policy are different roles. Objective probabilities are raw model probabilities; generation uses temperature/top-p. Consequently sampled KL and negative log-probability entropy are proxy diagnostics under this sampling procedure, not exact categorical KL/entropy. Sampled KL may be negative; negative values do not mean mathematical KL is negative or that the model has improved alignment.

## Training budgets and stability

| Run | Updates | Actual generated tokens | Skipped steps | Training minutes |
| --- | --- | --- | --- | --- |
| standard | 20 | 6909 | 0 | 10.7781 |
| clip_0.05 | 8 | 1942 | 0 | 3.16138 |
| clip_0.20 | 8 | 1942 | 0 | 2.68658 |
| clip_0.50 | 8 | 1942 | 0 | 2.64984 |
| kl_0.00 | 8 | 1988 | 0 | 2.93093 |
| kl_0.10 | 8 | 1942 | 0 | 2.63068 |
| kl_0.20 | 8 | 2018 | 0 | 2.92572 |

The clipping forks satisfy equal actual token and update budgets. KL forks match update counts, token ceilings and prompts, but not consumed tokens: the largest difference is 76 tokens (about 3.9% of the 1,942-token branch). This falls short of the explicit equal-generated-token requirement. Their contrasts are descriptive and cannot isolate beta perfectly under that requirement. An exact-token protocol would require additional matched runs; the saved evidence has not been silently relabeled as compliant.

Stability statistic: maximum policy gradient L2 norm across optimization epochs, measured before max_grad_norm=1 clipping. Skipped optimizer steps are a second stability indicator. A norm above 1 is an unclipped diagnostic, not the applied gradient magnitude.

## Held-out comparison

| Run | Learned reward | Effective reward | Sampled KL/token | Sample entropy/token | Response tokens | Truncation fraction |
| --- | --- | --- | --- | --- | --- | --- |
| midpoint | 1.72037 | 1.62037 | 1.26583e-05 | 0.802793 | 296.89 | 0.1 |
| standard | 1.73214 | 1.67214 | -8.24513e-05 | 0.799958 | 291.045 | 0.06 |
| clip_0.05 | 1.72747 | 1.64747 | 2.87573e-05 | 0.797603 | 292.135 | 0.08 |
| clip_0.20 | 1.72747 | 1.64747 | 2.87573e-05 | 0.797603 | 292.135 | 0.08 |
| clip_0.50 | 1.72747 | 1.64747 | 2.87573e-05 | 0.797603 | 292.135 | 0.08 |
| kl_0.00 | 1.70731 | 1.63231 | 8.89109e-05 | 0.801719 | 289.325 | 0.075 |
| kl_0.10 | 1.72747 | 1.64747 | 2.87573e-05 | 0.797603 | 292.135 | 0.08 |
| kl_0.20 | 1.71491 | 1.63991 | 8.87839e-05 | 0.80044 | 295.7 | 0.075 |

Standard mean learned reward changes by +0.011770; the paired prompt bootstrap 95% interval is [-0.064922, 0.089527] (10,000 resamples, seed 6304). This measures uncertainty across these prompts at one training/evaluation seed, not across independent training runs. 77/200 standard responses differ from midpoint. Small mean changes should not be presented as a robust overall quality improvement.

Effective reward additionally subtracts 1 for missing EOS. Standard truncation drops from 10% to 6%; the effective-reward gain therefore reflects both learned score and improved termination. Response length falls from 296.89 to 291.045 tokens; there is no aggregate length-inflation signal in the standard comparison.

## Standard continuation: trajectories, memory and runtime

20 updates; 6909 actual generated tokens; 0 skipped optimizer steps. Wall-clock including setup/save: 669.92 seconds (11.17 minutes). Recorded training-phase wall-clock: 646.69 seconds. This timer includes final saving. Peak PyTorch allocated device memory: 8.385 GiB; peak reserved: 10.014 GiB. These recorded counters exceed the setup’s nominal 6 GB dedicated GPU; on Windows they must not be described as verified physical dedicated-VRAM occupancy. No contemporaneous physical/shared-memory breakdown was recorded.

| update | learned_reward | kl | policy_loss | value_loss | entropy | clip_fraction | policy_grad_norm | value_grad_norm | response_length | value_explained_variance | value_mean | return_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2.93945 | -9.1679e-05 | -4.63325e-05 | 4.27528 | 0.963147 | 0 | 0.211185 | 56.2261 | 445 | -2.90597 | -0.425841 | -0.311371 |
| 2 | 2.79297 | 0.00038358 | 8.37885e-05 | 5.03594 | 0.722584 | 0 | 0.334496 | 113.632 | 244 | -4.02504 | -2.08161 | -1.69117 |
| 3 | 1.25879 | 0.000193143 | 0.000410561 | 3.60329 | 1.26505 | 0 | 0.606326 | 111.818 | 108 | -2.36364 | -1.42439 | -0.932901 |
| 4 | 2.48047 | 0.000213265 | 0.000339439 | 5.31142 | 0.987445 | 0 | 0.620962 | 366.575 | 72 | -0.726226 | -2.57972 | -1.16355 |
| 5 | 2.38672 | 0.000358443 | -0.000121056 | 5.28267 | 0.524258 | 0 | 0.171657 | 106.685 | 512 | -4.40609 | -1.70278 | -1.63629 |
| 6 | 0.760254 | -0.000620517 | 0.000752112 | 6.31831 | 1.18733 | 0 | 1.2327 | 290.559 | 34 | -5.6851 | -2.57144 | -1.04011 |
| 7 | 0.0681152 | 0.000156459 | -0.000171008 | 5.0792 | 1.13106 | 0 | 0.245505 | 140.163 | 512 | -16.4801 | -0.856537 | -0.923956 |
| 8 | 1.90039 | 0.00120804 | -0.000477477 | 7.43431 | 0.100335 | 0 | 1.34086 | 272.815 | 15 | -23.478 | -0.462541 | 1.31989 |
| 9 | 0.849121 | 0.000150821 | 0.00020544 | 4.21936 | 0.692266 | 0 | 0.226707 | 45.2698 | 512 | -3.54123 | -0.95383 | -0.964191 |
| 10 | 0.248047 | 9.08657e-05 | -0.000204877 | 3.62441 | 0.962901 | 0 | 0.240934 | 71.8061 | 512 | -7.20533 | -1.08187 | -1.0774 |
| 11 | 3.17188 | -0.000110062 | -9.75095e-06 | 2.49863 | 0.756492 | 0 | 0.181678 | 46.134 | 512 | -7.48282 | -0.404825 | -0.332335 |
| 12 | 3.19336 | -0.00118102 | 0.000104882 | 2.81546 | 0.755671 | 0 | 0.43432 | 122.671 | 92 | -3.66937 | 0.907434 | 1.32311 |
| 13 | 0.192749 | -0.000152479 | -1.79401e-05 | 3.58657 | 0.841022 | 0 | 0.166208 | 56.6178 | 512 | -1.75082 | -1.03815 | -1.10052 |
| 14 | 1.48242 | -0.00057861 | -0.000105228 | 2.84003 | 1.21723 | 0 | 0.266477 | 47.3072 | 443 | -10.616 | -0.0962774 | -0.0287626 |
| 15 | -0.373779 | -0.00022774 | 9.32571e-05 | 1.60924 | 0.727873 | 0 | 0.194984 | 22.2787 | 512 | -13.8753 | -0.817197 | -0.832901 |
| 16 | 2.39844 | -6.11531e-05 | -8.96174e-05 | 2.27609 | 1.05801 | 0 | 0.327534 | 31.6705 | 273 | -14.2602 | 1.07974 | 1.19048 |
| 17 | 2.41406 | 0.000540652 | 5.16608e-05 | 3.67293 | 0.902016 | 0 | 0.195311 | 61.4705 | 414 | -2.97688 | -1.95691 | -1.79017 |
| 18 | 0.00455475 | 7.37417e-05 | -0.000187372 | 1.83701 | 1.02431 | 0 | 0.188779 | 24.1193 | 512 | -7.82943 | 0.283037 | 0.233652 |
| 19 | 1.68262 | -0.000792493 | -0.000316702 | 4.38567 | 0.75327 | 0 | 0.640607 | 116.434 | 191 | -15.1605 | 0.955101 | 0.948321 |
| 20 | 1.5957 | 2.69014e-05 | 1.51307e-05 | 3.06121 | 0.671145 | 0 | 0.424783 | 49.0467 | 482 | -4.10594 | -1.77689 | -1.66162 |

Interpretation: rollout reward is noisy and nonmonotonic (one changing prompt per update), spanning -0.3738 to 3.1934; first-to-last reward is not a matched-prompt learning estimate. Sampled KL stays close to zero and changes sign. Policy losses are small, and clip fraction is zero on every standard update. Normalized advantages make the first epoch’s loss near zero at ratio=1 without making its gradient zero. The logs show no skipped steps or catastrophic policy-gradient spike.

The critic remains weak: value loss spans 1.6092–7.4343; explained variance is negative on all 20 updates (range -23.4780 to -0.7262, mean -7.6272). Critic pre-clipping gradient norms reach 366.575. Negative explained variance means squared-error residual variation exceeds target variation; it does not support an accurate baseline. These compare pre-update values with bootstrapped GAE returns on training rollouts, not independent Monte-Carlo held-out targets. First-to-last value loss falls, but prompt/target changes prevent attributing that difference solely to critic learning.

![Standard diagnostics](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/standard_train_diagnostics.png)

## Clipping study and Research Question 1

| Epsilon | Cached outside bounds % | Cached affected % | Cached surrogate | Fork reward | Fork KL/token | Fork response tokens | Max policy grad L2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.05 | 10.6535 | 5.21897 | -0.00533907 | 1.72747 | 2.87573e-05 | 292.135 | 1.34086 |
| 0.2 | 0.839573 | 0.453823 | -0.00393964 | 1.72747 | 2.87573e-05 | 292.135 | 1.34086 |
| 0.5 | 0.555934 | 0.329022 | -0.00328737 | 1.72747 | 2.87573e-05 | 292.135 | 1.34086 |

Outside-bound fraction counts ratios beyond [1−epsilon, 1+epsilon]; affected fraction counts tokens where the clipped surrogate is actually smaller. Advantage sign explains the difference. Tightening epsilon increases both cached fractions: affected tokens rise from 0.3290% at 0.50 to 0.4538% at 0.20 and 5.2190% at 0.05. The unclipped cached surrogate is 0.000133770 for all settings. The tighter surrogate is more pessimistic.

However, all training-epoch and post-update clip fractions are zero in the short forks. The policy updates stay inside even epsilon=0.05, so epsilon has no active role in their optimization. All three held-out summaries and response texts are identical, with max pre-clipping policy gradient 1.34086 and zero skipped steps. This is evidence of no observable epsilon effect under this small-update budget, not evidence that clipping is generally unnecessary. Cached geometry and actual continuation stability answer different questions.

![Clipping comparison](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/figures/clipping_comparison.png)

## KL-pressure study and Research Question 2

| Condition | Update | Reward | Sampled KL/token | Sample entropy | Response tokens |
| --- | --- | --- | --- | --- | --- |
| kl_0.00 | 1 | 2.93945 | -9.1679e-05 | 0.963147 | 445 |
| kl_0.00 | 2 | 2.93359 | 0.00039678 | 0.860099 | 314 |
| kl_0.00 | 3 | 0.867676 | -0.0010754 | 1.29926 | 84 |
| kl_0.00 | 4 | 2.48047 | -0.00054598 | 0.988204 | 72 |
| kl_0.00 | 5 | 2.38672 | 0.000114522 | 0.524502 | 512 |
| kl_0.00 | 6 | 0.760254 | -0.00118688 | 1.18789 | 34 |
| kl_0.00 | 7 | 0.0681152 | -3.22052e-05 | 1.13125 | 512 |
| kl_0.00 | 8 | 1.90039 | -0.000828707 | 0.102372 | 15 |
| kl_0.10 | 1 | 2.93945 | -9.1679e-05 | 0.963147 | 445 |
| kl_0.10 | 2 | 2.79297 | 0.00038358 | 0.722584 | 244 |
| kl_0.10 | 3 | 1.25879 | 0.000193143 | 1.26505 | 108 |
| kl_0.10 | 4 | 2.48047 | 0.000213265 | 0.987445 | 72 |
| kl_0.10 | 5 | 2.38672 | 0.000358443 | 0.524258 | 512 |
| kl_0.10 | 6 | 0.760254 | -0.000620517 | 1.18733 | 34 |
| kl_0.10 | 7 | 0.0681152 | 0.000156459 | 1.13106 | 512 |
| kl_0.10 | 8 | 1.90039 | 0.00120804 | 0.100335 | 15 |
| kl_0.20 | 1 | 2.93945 | -9.1679e-05 | 0.963147 | 445 |
| kl_0.20 | 2 | 2.93945 | 0.000118721 | 0.852926 | 314 |
| kl_0.20 | 3 | 1.25879 | -0.000312081 | 1.26555 | 108 |
| kl_0.20 | 4 | 2.29297 | 0.000596046 | 1.01534 | 78 |
| kl_0.20 | 5 | 0.87207 | 0.000301526 | 0.385672 | 512 |
| kl_0.20 | 6 | 0.760254 | -0.00109708 | 1.1878 | 34 |
| kl_0.20 | 7 | 0.0681152 | -3.21782e-05 | 1.13125 | 512 |
| kl_0.20 | 8 | 1.90039 | 3.9721e-06 | 0.101539 | 15 |

Relative to beta=0.10, both beta=0 and beta=0.20 first differ in learned reward, sampled KL, entropy and response length at update 2. Update 1 generates the same response before any beta-dependent update; beta first changes shaped rewards/advantages during optimization. At the next logged rollout all four observables differ simultaneously. At this measurement resolution there is no defensible claim that one observable changes first. Qualitative behavior was not systematically scored at every update, so its onset cannot be ranked.

Held-out beta=0 has lower reward (1.70731) than beta=0.10 (1.72747), a slightly larger sampled KL proxy, slightly higher sample entropy and shorter responses. Beta=0.20 also has lower reward (1.71491) than 0.10 and longer responses. Reward and KL do not follow a clear monotonic trade-off across all three conditions. Small proxy differences, one seed and unequal token consumption limit causal conclusions; removing the penalty did not produce a clear reward-overoptimization signature here.

![KL trajectories](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/figures/kl_trajectory_comparison.png)

## Qualitative evidence and Research Question 3

| Example index | Criterion | Midpoint reward | Standard reward | Interpretation |
| --- | --- | --- | --- | --- |
| 63 | Reward and quality move together (partial improvement) | 0.541504 | 2.79492 | The request asks for a course and a 90-day host-collaboration campaign. The midpoint answer is truncated mid-item ("Social Media Engagement (Weeks 4"). The continuation finishes its campaign with Day 1–3, Day 4–6, Day 7–90, and a post-collaboration reflection phase. Completion and coverage improve while reward rises. This is a partial quality improvement: neither answer provides a fully developed set of text/audio/video teaching assets, and the proposed schedule is still broad. This assessment uses visible completeness and instruction coverage, not factual verification of marketing effectiveness. |
| 102 | Reward and quality disagree: reward rises without fixing the error | 0.917969 | 1.15527 | The prompt asks why hunters can live underwater without equipment. Both answers accept the false premise and say hunters have evolved to survive underwater. The continuation only changes the closing phrase to refer to oceans and aquatic environments; it does not clarify the ambiguity or correct the premise for human hunters. A higher reward here is not evidence of improved factual reliability. This is a local reward-quality mismatch, not proof that PPO learned systematic reward exploitation. |
| 155 | Reward rises but the final quantitative answer remains wrong | -0.0455627 | 2.56836 | The prompt specifies a central 10,000 lb point load and a 1 square inch cross-section. By symmetry, each reaction is 5,000 lb; equilibrium gives V=5,000 lb on the left half and average shear stress V/A=5,000 psi. The continuation correctly computes V=5,000 lb but invents a 0.5-inch height and concludes 10,000 psi. The midpoint also contains serious errors and is truncated. Reward increases and some intermediate reasoning/completeness improve, yet the requested final answer is still incorrect. This mixed case shows why fluent completion cannot replace task-specific correctness checks. |

Learned reward is useful as one signal but is not a trustworthy substitute for task quality. The course example shows a reward gain accompanying improved completion/coverage. The underwater-hunter example shows a reward gain with essentially unchanged factual failure. The beam example shows improved intermediate steps and fluency while the final quantitative answer remains wrong. These demonstrate local reward-quality disagreement; they do not establish systematic exploitation learned during PPO.

Against a strong overoptimization claim: aggregate reward gains are small; sampled drift remains near zero; standard responses become slightly shorter; weaker beta does not yield a higher held-out mean reward. For caution: highly rewarded outputs can still violate instructions or give incorrect answers, and the reward model can respond to wording/completeness rather than correctness. This run does not explore substantial departure from the reference, so it cannot establish how reward reliability behaves under large distribution shift. Task 4 safety evidence is still required before assigning a safety explanation.

[Full selected prompts, before/after responses and assessments](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/qualitative_evidence.md>)

## Files and reproducibility

[standard_trajectories.csv](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/standard_trajectories.csv>)

[kl_trajectories.csv](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/kl_trajectories.csv>)

[paired_reward_analysis.json](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/paired_reward_analysis.json>)

[qualitative_evidence.json](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/qualitative_evidence.json>)

[Full appendix: all 1,600 generated responses](<D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task2_ppo/all_evaluated_examples.md>)

Per-condition CSVs contain all responses and their metrics. Original JSON/JSONL evidence, configuration snapshots and checkpoint files are preserved. Regenerate this report with python -m task2_ppo.report_results; regenerate base plots with python -m task2_ppo.export_results.

## Remaining requirements

Exact consumed-token matching for the KL study is not met. Task 4 safety evidence is absent. Those are genuine gaps, not conclusions supplied by this report. Qualitative judgments are assistant assessments; obtain human review if the course requires it. The NF4 scorer deviation, proxy KL/entropy, weak critic, fixed single seed and finite generation caps must accompany the results.