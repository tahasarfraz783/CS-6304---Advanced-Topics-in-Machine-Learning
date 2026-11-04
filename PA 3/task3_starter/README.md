# Task 3 · test-time compute

See `START_HERE.md` for the one-command launch. This directory follows the Task 2 layout, with independent `task3` modules and output folders.

## Pipeline and recovery

`run.py --mode run` executes download → preparation → live GPU inference → offline CPU analysis → evidence → archive. Live inference runs before offline analysis so all strategies are timed without competing analysis workers. Each completed live call and offline question is saved atomically. The pinned seed schedule makes later calls independent of whether earlier calls were resumed.

Individual modes: `prepare`, `live`, `offline`, `plots`, `package`, `check`, `status`. `live` and `offline` require prepared inputs from `prepare`. `check` expects the files to be downloaded. `python download_data.py` downloads them independently. `--workers 8` controls CPU analysis; it never changes live batch size. `--output PATH` selects an isolated experiment folder.

`run_identity.json` binds results to code/config hashes. `input_identity.json` binds prepared groups to input hashes and scorer versions. A change requires a new output folder; the runner refuses to silently mix results. Prepared pickle files are internal caches created locally from public Parquet; load only caches produced by this runner.

## Protocol

The supplied README and original assignment excerpt are in `inputs`. `expected_files.json` freezes the downloaded public snapshot by SHA256; all seven input files are checked against it before preparation. IDs are lexicographically sorted and permuted separately per dataset with `default_rng(6304)`: 200 dev, 800 eval, first 50 MATH eval for live inference. Ten per-question permutations use `SeedSequence([6304, lexicographic_question_index])`, and the exact orders are saved. All methods and policies reuse nested prefixes.

The scorer is `task3-scorer-v3/math-verify-0.9.0/parse-verify-8s`. MATH uses mathematical equivalence against rollout-ID-ordered representatives to form groups before gold is consulted. MathVista uses released question/answer types, choice matching, integer conversion, and precision rounding. Choice outputs become option letters. Missing/empty/invalid normalized predictions form `NO_ANSWER`, remain in voting, and are always incorrect. Choice text fallback follows the official minimum edit-distance rule, earliest choice for ties. MATH empty parse results are incorrect rather than assigned a numeric fallback.

Scoring runs parsing and verification in a persistent isolated process, each with an eight-second hard limit on both Windows and Linux. Parse validity is cached in the parent, while symbolic objects stay in the disposable worker. Failed parses are not repeatedly attempted for every candidate pair. The internal library timeout is disabled because its Windows wrapper has a process-pickling issue. A timed-out or resource-exhausted comparison is non-equivalent; timeouts log a warning and resource-limit events are counted in validation/scorer_timeouts.csv. This bounds pathological symbolic simplification while retaining the same scoring policy on both platforms. Run the scorer tests in the rental environment too.

Scores use raw supplied logp/KL. Visual attention is normalized by image+prompt+generated eligible mass. Confidence uses linear 5th/95th percentiles of only the current prefix's pooled token KL. RWC uses descending average ranks; score and vote ties select the earliest supporting rollout in the current order. Quartile analysis chooses exactly eight top/eight bottom rollouts with rollout-ID tie breaks. Undefined constant-signal correlations are omitted and reported as missing.

Adaptive policies are tuned separately per dataset using only the dev set: lowest mean token cost subject to dev accuracy ≥ fixed-32 SC − 0.01; ties favor accuracy, smaller tau, smaller gamma. Always-32 is a candidate fallback. Held-out controllers return SC, with no gold-based fallback. Gold and future correctness are used only for analysis and stated retrospective example selection.

At each N, FirstAns consumes/charges one candidate. Pool oracle coverage and pool diversity still describe the N-candidate opportunity, so oracle values are repeated across methods. All other fixed selectors pay for all N candidates. Order outcomes are averaged per question before aggregate results or 1,000 paired bootstrap resamples. `paired_bootstrap.csv` records main fixed-method comparisons; adaptive summaries include paired differences versus fixed-32 SC.

## Evidence

- `method_comparison.csv`: dev/eval accuracy, oracle coverage, costs, diversity, failure decomposition at all budgets.
- `*_per_question_orders.parquet`: exact selected groups, candidate IDs, costs, correctness, pool coverage for each order/method/budget.
- `signal_per_question.csv`, `signal_summary.csv`: within-question length/quality/correctness rank correlations and top-minus-bottom correctness, including shortest-response control.
- `confidence_vision_per_rollout.csv`, `confidence_vision_question_summary.csv`: calibrated-confidence/vision Pearson correlation and token-fusion covariance; summarize by question before dataset-level interpretation.
- `*_adaptive_all_settings.parquet`, `*_selected.parquet`, `adaptive_summary.json`, `frozen_policies.json`: all dev/controller simulations, frozen settings, held-out cost/accuracy, stop counts, and recoverable wrong early stops.
- `live/calls/*.json`, `live_per_question.csv`, `live_summary.csv`: exact prompts, responses, token IDs, independent seeds, lengths, caps, extraction flags, runtime, peak memory, and revision transitions.
- PNG + PDF curves, fixed trajectories, `qualitative.html`, and `example_selection.json`: aligned evidence with explicit selection rules.
- `report.md`: measured summaries organized around the five research questions. Review the linked cases when writing the final interpretation.

Live timing excludes model loading and warm-up, includes chat rendering, tokenization, host/device transfer, generation, output decode and synchronization. Strategy totals sum constituent calls; parallel sampling is executed sequentially at mandatory batch size 1. Output-token counts include actual termination tokens; retained-token counts exclude stop tokens for comparability with supplied pools. Truncation is reaching the cap without a terminating token. The shared initial call is charged independently to both parallel and refinement; its response is reused verbatim in the longer revision prompt. Final answers never use correctness to choose initial versus revision.

The output ZIP includes raw analyses, live records, evidence, provenance, and source. It omits the original public Parquet files, internal prepared caches, and base model weights. Re-download those from saved IDs/revisions when needed. SHA256 and ZIP CRC checks are generated for delivery.

## Performance and limits

Offline data are only about 419 MB compressed and 64,000 rollouts. They require no VLM weights, image downloads, attention regeneration, optimizer, or training. Float64 score reductions avoid avoidable numerical instability. Eight worker processes and cached per-question arrays use CPU/RAM efficiently while avoiding BLAS oversubscription. Use the measured monitor/telemetry to assess utilization; batch-1 autoregressive decoding cannot promise full A100 occupancy.

This starter is not a claim that the controlled GPU experiment has already run. See `VERIFICATION.md` for checks performed locally and what remains GPU-only.

