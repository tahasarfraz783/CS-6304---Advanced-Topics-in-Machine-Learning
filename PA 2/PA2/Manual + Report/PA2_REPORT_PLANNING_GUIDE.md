# PA2 report planning guide

This is a planning worksheet, not report text. Write the submitted language, interpretation, and analysis yourself, as required by the manual's AI usage policy (page 1). Independently check saved summaries against underlying results before using them.

## Translate the PA1 feedback into writing decisions

| PA1 feedback | PA2 writing decision | Self-check |
|---|---|---|
| Separate task answers did not build a connected argument | Use the manual's shared research question to introduce and connect the experiments; keep task coverage easy to locate | Does each section explain why its experiment belongs in the overall study? |
| Results received less interpretation than diagnostics | Allocate text to the relationship between observations, possible explanations, alternatives, and limits | Have I explained what the evidence supports rather than repeating table entries? |
| Recovery and implementation details occupied too much space | Put full implementation recipes and extra plots in a short appendix; retain consequential deviations in Methods | Could a reader assess comparability without the appendix? |
| Methods explained settings more than experimental logic | For each intervention identify what changes, what stays fixed, the intended measurement, and its limits | Can the reader distinguish a controlled intervention from an observational comparison? |
| Cross-task synthesis was too short | Reserve space for Task 6 from the outset | Does Discussion connect tasks instead of summarizing them again? |
| References mainly attributed algorithms | Cite datasets, model provenance, evaluation instruments, and relevant methodological claims as well | Does each citation serve a specific claim or attribution? |

Do not copy the reference report's length or appendix strategy. PA2 requires eight pages of main content; all task-specific Required Evidence must appear there. References are excluded. The repository link belongs at the end of the abstract.

## Eight-page working budget

These are approximate space allocations, not mandatory page breaks. Tables and figures count within these allocations.

| Component | Pages | Purpose |
|---|---:|---|
| Abstract and Introduction | 0.65 | Shared question, experiment progression, research questions |
| Experimental Setup / Methods | 0.85 | Starting states, feedback sources, controls, metric definitions, deviations |
| Task 1: DPO | 1.00 | Standard/beta comparison, length intervention, required examples |
| Task 2: PPO | 1.25 | Standard trajectories, clipping, KL pressure, critic, quality examples |
| Task 3: GRPO | 1.15 | Standard trajectories, group sizes, normalization, sample efficiency |
| Task 4: Safety | 1.00 | Policy rates, category distributions, audit, disagreements |
| Task 5: Feedback source | 1.15 | GSM/SVAMP, all perturbations, sensitivity, examples, cost |
| Task 6 Discussion and Conclusion | 0.95 | Connections, limitations, answers to the overall question |
| Total | 8.00 | |

Give methods enough space to define the interventions, but avoid a tutorial on every paper. Use compact, readable tables and multi-panel figures to fit required evidence. Reduce redundant explanations before reducing font size.

## Evidence placement and questions to answer yourself

### Task 1

Source: `PA2/results/task1_dpo/all_results.md`. Use the qualitative-evidence file and underlying CSV/JSON files too. All source paths in this guide are relative to the workspace root.

Main-body evidence: standard and three beta conditions with budgets, loss, preference accuracy, KL, reward, and length dispersion; standard/balanced results across three length strata; generated length and word-limit compliance; two brief examples covering reward/quality disagreement and length/instruction compliance.

Writing questions:
- Which metric is the assignment's reference-adjusted preference accuracy, and which is raw sequence-likelihood accuracy?
- Across matched beta forks, which relationships are monotonic, and which are not?
- What distinguishes training-pair length correlations from generated verbosity?
- How much evidence can ten word-limit prompts provide?

### Task 2

Sources: `PA2/results/task2_ppo/all_results.md`, `qualitative_evidence.md`, trajectories, paired reward analysis, and original run logs.

Main-body evidence: required standard trajectories, compute counters, cached clipping fractions and actual affected fractions, short-fork results and stability, KL trajectories, critic diagnostics, and brief reward/quality examples. Combine related trajectories into legible panels rather than inserting the full 20-row log.

Writing questions:
- Does clipping activate in cached data, actual training, both, or neither?
- How do the outside-bound and affected-token fractions differ mathematically?
- What does a paired uncertainty interval permit you to claim about the reward change?
- What is learned reward versus effective reward, and how does termination affect the latter?
- What can training-rollout critic diagnostics establish about held-out calibration?

### Task 3

Sources: `PA2/results/task3_grpo/all_results.md`, `research_answers.md`, and original group/normalization logs.

Main-body evidence: standard trajectories and compute; K=2/4/8 results overall and by fixed difficulty proxy; informative/constant-reward examples; normalization and short/long gradient diagnostics; held-out reward, KL, length; required qualitative examples and sample-efficiency statistics.

Writing questions:
- With equal total generations, what changes when cached completions are regrouped?
- Is standardized advantage variance independent evidence of reduced noise?
- Does the normalization experiment measure fixed-rollout replay or separate on-policy trajectories?
- Which gradient statistic was actually measured?
- Are apparent held-out differences distinguishable from prompt-level uncertainty?
- How many generated tokens actually enter the loss, and why are others excluded?

### Task 4

Sources: `PA2/results/task4_safety/all_results.md`, `evidence_checklist.md`, `qualitative_evidence.md`, and audit records. Treat saved research answers as material to verify, not language to reuse.

Main-body evidence: all required safe/unsafe rates, ambiguity and length for four standard policies; all category-level distributions; per-policy audit agreement and confusion breakdown; harmful compliance, justified refusal, and over-refusal examples with the source of disagreement identified.

Writing questions:
- How do automated labels differ from audited behavior?
- Which failure types disappear in the automated summary but appear in the audit?
- Are policy differences large relative to the audit's sample size?
- Are comparisons of reward and safety based on matching evaluation regimes?
- Has the class-inconsistent manual label been checked?

### Task 5

Sources: `PA2/results/task5_feedback/all_results.md` and underlying policy/diagnostic records.

Main-body evidence: all three policies on GSM and SVAMP, accuracy, pairwise results, format, length, agreement and domain changes; all five diagnostic categories with better/tie/wrong rates for both mechanisms; reasoning/outcome sensitivity; brief reasoning-corruption, filler, wrong-final/distractor examples; feedback coverage, noise, exploitability and inference cost.

Writing questions:
- When is a verifier tie legitimate invariance rather than an error?
- What distinction does each controlled perturbation isolate?
- Does judge preference respond to correctness, reasoning, or presentation in each example?
- How do missing-final failures affect the meaning of exact-answer accuracy?
- Does higher SVAMP accuracy establish generalization improvement, given different datasets?
- Which measured costs include cache access, and which exclude model loading?

## Build Task 6 with connections, not another results table

Use these prompts to develop your own synthesis:

1. Connect DPO beta, PPO KL pressure, and GRPO normalization: what does each constrain, and which metrics can legitimately be compared?
2. Compare DPO length strata, PPO termination/length, and GRPO normalization/masking: where does length enter the learning or evaluation procedure?
3. Connect preference/reward disagreement examples with the safety audit and feedback perturbations: what independent behavioral checks are needed?
4. Compare PPO critic limitations with GRPO group informativeness and discarded tokens: where is computation spent without delivering useful learning signal?
5. Compare exact checking with learned and AI feedback: what does each detect, miss, or misrank, and at what measured cost?

For each connection, cite evidence from at least two tasks, explain the relationship yourself, consider an alternative explanation, and state the limit of the comparison. Do not create a global algorithm ranking from incompatible reward or KL measurements.

## Checks before drafting

- DPO metric naming: the manual defines preference accuracy using the reference-adjusted margin. The saved summary labels this `implicit_reward_accuracy`; its `preference_accuracy` is raw likelihood accuracy. Verify the underlying implementation and use explicit labels in the report.
- DPO KL: the saved summary describes vocabulary KL averaged over generated prefixes, whereas the manual specifies a released sampled-response estimator. Inspect the implementation and resolve/document this before comparing KL values.
- PPO KL forks consume 1,988 / 1,942 / 2,018 tokens. The saved summary identifies failure to meet exact consumed-token equality. Writing alone cannot repair this experimental gap.
- PPO uses an NF4 reward scorer locally rather than the release INT8 regime. Keep cached and local scoring regimes explicit.
- PPO/GRPO entropy and KL summaries include proxy statistics and different training/evaluation estimators. Label each accurately.
- PPO memory counters should not be described as verified physical dedicated-VRAM occupancy. Preserve the recorded counter definition.
- Task 2's summary still says Task 4 safety is pending, although Task 4 outputs now exist. Check source dates and avoid copying stale status statements.
- GRPO has no saved midpoint held-out evaluation in the inspected summary. Do not infer improvement from the final value alone.
- Existing qualitative assessments include assistant-generated judgments. Independently examine the actual responses and develop your own analysis.

## Paragraph worksheet

Before writing each major results paragraph, fill these fields in notes:

1. Question and controlled comparison.
2. Exact observation and source file, including denominator/budget.
3. Relationship to another diagnostic or qualitative case.
4. Your explanation, with supporting citation if needed.
5. Alternative explanation or comparability limit.
6. Implication for the shared research question.

This is a thinking sequence, not a requirement to write six sentences every time. If a paragraph only restates table values, develop the reasoning or remove it.

## References and final review

Use the manual's required readings as starting points. Verify each paper before citing it. Add model/data/evaluation provenance and methodological citations only where they serve your text; do not target a reference count. Prefer primary papers and official documentation.

Final review: all Required Evidence visible in the main body; every research question answered; every value traceable to saved artifacts; matched and unmatched comparisons clearly identified; concise quotations; no unsupported optimizer causality; discussion adds connections; eight-page limit met; repository link in abstract; your own language and analysis throughout.
