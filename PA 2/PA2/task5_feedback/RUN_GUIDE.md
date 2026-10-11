# Task 5 run guide

Run from PA2 using the existing environment. Task 5 evaluates the supplied base/SFT, RLVR, and RLAIF policies without training. Tasks 1-3 need not be rerun.

```powershell
. .\activate.ps1
python -m unittest task5_feedback.test_feedback
python -m task5_feedback.evaluate_math --config configs/feedback.yaml --dataset gsm --batch-size 4
python -m task5_feedback.score_perturbations --config configs/feedback.yaml
python -m task5_feedback.evaluate_math --config configs/feedback.yaml --dataset transfer --batch-size 4
python -m task5_feedback.compare_feedback --config configs/feedback.yaml
```

If GPU memory runs out during generation, rerun with `--batch-size 1`. Responses resume from validated completed prefixes. All policies use matched greedy decoding and the 512-token default completion cap. Course data, checkpoints, verifier, and judge remain unchanged.

Outputs in `results/task5_feedback` include response JSONL files, pairwise judgments, domain summaries, all 100 diagnostic response scores, diagnostic pairs, CSV comparisons, combined JSON, and `all_results.md`. The report covers accuracy, format, length, truncation, win/tie/loss rates, verifier/judge ranking agreement, sensitivity, transfer drops, final-answer failure types, qualitative evidence, inference cost, and the research questions.

Diagnostic group rewards use all ten unordered pairs per five-response group. Controlled perturbation rates put clean in A and the variant in B. Clean is an identity control with all ties, not a sensitivity observation. Outcome sensitivity uses only clean versus good reasoning with wrong final; distractors are separate. Filler preference measures susceptibility to irrelevant framing, not necessarily mathematical error. Verifier ties on reasoning-only changes are legitimate invariance.

SFT self-comparison is a defined 0.5 baseline. Agreement compares A/B/TIE rankings rather than numerical reward scales. Agreement restricted to unequal exact outcomes has a separate denominator. Failure labels describe observable final-answer errors, not inferred reasoning causes. Judge comparison times exclude model loading and separate new from reused cache entries.

Use `--overwrite` on math evaluation when deliberately regenerating after changing configuration. Judge cache keys include model, problem, and full candidate texts; keep the supplied judge unchanged while reusing this cache. Aggregation rejects changed configurations and math source data. Rerun diagnostic scoring if its source changes.

The starter documents deliberate algorithmic defects only in Tasks 1-3. Task 5's supplied verifier already ignores gold numbers appearing solely as intermediate distractors; regression tests verify this.

On Windows, the judge loader repacks the cached checkpoint into smaller local shards under `.cache/task5_judge_small_shards` to avoid paging-file failures when opening multi-gigabyte safetensors shards. This uses about 6.2 GB of additional disk space, performs no retraining, and preserves every tensor byte. The model ID, tokenizer, rubric, quantization settings, and cache keys remain unchanged.
