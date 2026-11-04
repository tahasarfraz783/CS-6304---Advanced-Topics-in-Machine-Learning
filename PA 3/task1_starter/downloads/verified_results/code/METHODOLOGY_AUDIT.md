# PA3 Task 1 methodology audit

Reviewed on 25 October 2026 against the user's pasted Task 1 requirements, including the
shared setup, all five methods, diagnostics, qualitative comparison, and required evidence.
Scope is Task 1 only, not the vision-language or test-time-compute tasks.

Verdict: the implemented experimental design matches Task 1 after the corrections below.
The actual Qwen/full-dataset/harness workflow has NOT yet passed an end-to-end smoke test.
Do not interpret this review as measured benchmark correctness or a runtime estimate.

Delivery follow-up: the launcher now exports six standalone inference model conditions,
packages evidence/code and models into separate verified ZIPs with SHA256 hashes, and
provides explicit disposable-test cleanup to prevent timing/smoke checkpoints filling disk.
These delivery helpers have offline tests. Actual Qwen/harness integration remains pending.

## Requirement mapping

| Requirement | Implementation / status |
|---|---|
| Post-trained Qwen/Qwen3-0.6B | `config.json`; preparation freezes a shared local starting snapshot |
| Thinking disabled | Explicit `enable_thinking=False` in training and generation templates / harness wrapper |
| Independent initial checkpoint; seed 6304 | Each method loads the shared snapshot; all runs seed Python, NumPy, CPU/CUDA torch |
| First 40,000 eligible MetaMathQA examples | Source-order filtering in `data.prepare`; retained source IDs saved |
| Empty / length / GSM8K-test exclusions | Explicit filtering; normalized query AND original_question checked |
| No answer truncation or retained-example shuffle | Long examples excluded; ordered tokenized rows reused |
| Assistant-response + end-of-turn loss; prompt/padding masking | `encode_example`, `collate`; -100 masks; explicit im_end target |
| Token mean over effective batch | Each microbatch mean weighted by its valid-token count / effective-batch valid tokens |
| One epoch; 40,000 examples; 1250 scheduled update attempts | Sequential offsets in `train`; microbatch 2 and accumulation 16 |
| AdamW betas, epsilon, weight decay exclusions | Explicit parameter groups, betas (0.9,0.999), eps 1e-8, decay 0.01 |
| Cosine LR, 38 warmup, global clip 1.0 | Scheduler and clipping in training loop |
| Gradient checkpointing, FP16 AMP, dynamic scaling | Enabled explicitly; unscale before clipping; skipped attempts logged |
| FP32 full parameters / adapters / optimizer moments | Correct by construction; moments verified for all five methods in tiny CUDA test |
| Full FT LR 2e-5, no starting-point penalty | Training branch for full_ft |
| L2-SP LR 2e-5, lambda 1e-3 | Penalty 0.5 * SUM squared deviations over unique named parameters |
| Fixed reference; tied params once; biases/norm params included | Reference clones + default duplicate-removing named_parameters iteration |
| LoRA rank/alpha pairs 4/8 and 16/32, LR 2e-4 | Adapter constructor and training branch |
| Dropout 0.05, random A, zero B, frozen biases/backbone | Explicit LowRankLinear initialization and freezing |
| All seven projections in every layer | TARGETS shared by adapter attachment and basis preparation |
| OPLoRA r16/alpha32/k128 and same initial unprojected factors as LoRA16 | Same seeded constructor path; precomputed bases loaded without RNG operations |
| FP32 starting-weight SVD, effective projections, exported projected factors | diagnostics preparation, factors(), adapter_exports() |
| Four recovery checkpoints | Exact updates 312,625,937,1250; weights + optimizer/scheduler/scaler/RNG stored |
| Recover data position | Next source offset inferred exactly from completed update and fixed effective batch |
| Seven evaluation conditions | Baseline, Full FT midpoint, and five finals in launcher |
| Complete fixed benchmark splits, zero-shot | Harness task names, num_fewshot=0, unique doc-ID count assertions |
| FP16 evaluation, no dropout | Separate FP16 model copies with eval() |
| GSM8K non-thinking chat, greedy, cap1024, stock filters/stops | Harness wrapper and generation override; needs live harness verification |
| Retention completion prompts and primary/raw accuracy | Chat disabled for likelihood benchmarks; table includes raw acc where present |
| Fresh merged adapter copies, merge check | Exports merged into fresh baseline; two fixed prompt checks before scoring |
| Probe set 32 math + 32 non-math, chosen before trained results | Saved shared probe IDs and prompt strings in preparation |
| FP32 diagnostic forward/cache/calculations | Corrected during this audit; see below |
| down_proj layers 0,13,27 at six trained conditions | Selected module names and launcher schedule |
| rho, eta, and per-input R(z) | FP32 local computations; same cached starting activations used throughout |
| Full FT displacement midpoint/final, L2-SP final | Saved JSON + combined table/plot |
| 24 qualitative prompts x seven conditions; cap512 greedy | Evaluation code; authentic prompt file is still missing |
| 42-response annotation subset | Template generated from six flagged prompts; actual first/last IDs need manual verification |
| Losses, resources, benchmark deltas, diagnostics, response comparisons | Raw logs + combined CSVs/SVGs/local evidence index |

## Corrections made during review

1. **FP32 activation diagnostics.** Previously the starting model was cast to FP16 before
   caching probe activations and the resulting vectors were cast back to FP32. The probe
   forward now stays FP32. This is separate from the required FP16 benchmark evaluation.
2. **Resume overhead accounting.** The duration of writing a checkpoint cannot be known
   until after serialization. A metrics sidecar now preserves this duration across a
   midpoint resume. Reference setup overhead is also accumulated across training segments.

If an older copy generated diagnostic caches, use a fresh output directory with this copy.
Existing FP16 activations must not be relabeled FP32 or reused as corrected evidence.

## Verification actually performed

The original **eight methodology/training tests passed** in the existing `pa2_env`, without installing or changing packages.
Its CUDA-enabled torch installation detected the RTX 4050.

- Prescribed effective batch / recovery schedule and dependency-free launcher plan.
- Percentage-point calculations, valid SVG generation, and preserving manual annotations.
- Actual LoRA forward equivalence, frozen original weights, trainable adapter gradients.
- Actual OPLoRA input/output orthogonality and differentiability.
- Prompt/padding labels and effective-batch token weighting.
- Actual training loop for ALL FIVE methods on a tiny randomly initialized Qwen3 model.
- FP32 Adam first/second moments for all five tiny training runs.
- Bitwise equality of final OPLoRA parameters: uninterrupted versus checkpoint/resume.

The tiny test uses a one-layer random model and four synthetic examples in a temporary
directory. It tests machinery only. Its losses and timings are not assignment results or
useful estimates of Qwen3-0.6B runtime. The temporary outputs are removed automatically.

## Course prompt input resolved

The actual course YAML is now included unchanged. Automatic normalization preserves its
system/user roles and exact text, validates all 24 entries, and flags all formats of the
first/last plain questions. Two regression tests cover roles/subset and rejection of altered
JSON. The original 100-sample/API-judge settings are ignored in favor of PA3's one greedy
response requirement. The missing-prompt/manual-normalization item below is now resolved.

## Original remaining-work checklist (prompt item now resolved)

1. Obtain `first_plot_questions.yaml`. Inspect its schema and normalize its exact 24 prompts
   into qualitative.json. Verify the first/last plain-question ordering and six flagged prompts.
   Current checks validate structure/counts, not transcription against the missing YAML.
2. Install the requirements on the cloud instance and freeze the working environment.
   The local PA2 environment lacks lm_eval and has datasets 4.8.5 rather than the proposed
   3.6.0 pin. These packages were NOT changed during this audit.
3. Run the real-model smoke test. In particular verify the pinned harness integration,
   task prompts/filters/stopping, merge errors, generated-token cap records, and full-run
   configuration. Unit tests do not substitute for this integration check.
4. Inspect one prepared example (decoded prompt, solution, and label mask), filter totals,
   dataset IDs, and probe prompts before launching the full 40,000-example runs.
5. Time a short run on the selected GPU. No valid full-experiment runtime estimate exists yet.

Afterward, run the unchanged full configuration; smoke/timing results use separate folders
and must not enter the assignment tables. Quantitative success, retention, qualitative
annotations, and report interpretation remain to be established from actual experiments.

## Resource interpretation

Optimizer-step time excludes loading, plots, checkpoint serialization, SVD, export, and
evaluation. Those are available separately in stage_times.csv, resources.json, export JSONs,
and diagnostics_ready.json. Basis preparation is shared for caching purposes but must be
accounted for explicitly when interpreting OPLoRA cost. Equal update counts do not imply
equal compute. No old-task training/replay is used.

The scheduler advances only after successful AMP optimizer steps; skipped attempts are
reported, not silently retried with extra data. Inspect any skips when interpreting the
actual number of successful updates and the learning-rate trace.

For stock task-generation override behavior, see the official harness evaluator:
https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/evaluator.py
The pinned release's runtime behavior still needs the smoke test above.
