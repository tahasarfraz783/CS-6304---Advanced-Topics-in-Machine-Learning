# Verification · 27 October 2026 (Asia/Karachi)

## Completed locally

- Downloaded all five public Parquet files from the supplied Drive folder and the released MathVista testmini metadata. Saved SHA256/byte-count provenance for all seven runtime inputs. Manifest paths use portable forward slashes.
- Verified 32,000 rows per table, one-to-one joins on the three required keys, exactly 1,000 questions and rollout IDs 0–31 per dataset, retained-token/list alignment, finite logp/KL/attention, nonnegative attention/KL, positive attention denominators, and attention preceding-token indices.
- Reproduced README totals exactly: MATH 20,742,094 retained tokens, 523 capped rollouts, 521 missing extractions; MathVista 8,961,703 tokens, 487 capped rollouts, 3,032 missing extractions.
- Prepared and analyzed all 64,000 rollouts, all six candidate budgets and ten saved nested orders. Completed dev selection, held-out adaptive evaluation, 1,000 paired question bootstraps, signal analyses, aligned examples, and PNG/PDF evidence.
- Passed **14 automated tests** covering balanced last-box extraction; missing answers; vote/score ties; average ranks; singleton selection; prefix-only calibration; fusion/covariance; unique-leader stopping; split/order determinism; MATH equivalence; MathVista rules; isolated symbolic IPC; atomic recovery/locks; portable input hashes/mutation rejection; synthetic complete offline/evidence pipeline; and shared-initial live cost/transition accounting.
- Passed a small randomly initialized Qwen2 FP16/SDPA generation API compatibility probe on CPU with the pinned Transformers 4.57.1 interface and stopping criteria. This was not an assignment inference run.
- Generated offline dashboard, tables, plots, retrospective cases, and report notes in `outputs/offline_verified/evidence/`.

At N=32, held-out self-consistency accuracy is MATH **73.7875%**, MathVista **62.4375%**. Oracle coverage is **91.375%** and **89.5%**, respectively. These are offline supplied-rollout measurements, not live FP16 accuracy.

## Scorer limitation, disclosed in evidence

MATH question `test:4928` contains nested radicals raised to enormous exponents. Forty isolated parse/verify operations reached an eight-second or memory resource limit. The frozen scorer treats these as non-equivalent and records their hashes/counts; this question remains in evaluation. Other 1,999 questions recorded no such events. These limits can affect answer grouping/grading for that one question; its individual held-out weight is 1/800. Do not silently remove it or describe all symbolic comparisons as exact proofs.

The scorer uses math-verify 0.9.0 behind persistent process isolation on Windows and Linux. Symbolic objects stay inside that process because reconstructing a giant expression in a parent can itself allocate excessive memory. Parse validity and pair outcomes are cached; resource errors cannot crash the experiment controller.

## Requires the actual rental GPU

No remote connection or credentials were supplied, and no live assignment generations were run locally. The A100 throughput preflight, 250 seeded calls for the fixed 50-question comparison, actual inference times, FP16 extraction/truncation rates, memory peaks, revision transitions, and final complete result ZIP must be produced by `run.py --mode run` on the rental instance.

The runner preserves batch size 1, FP16, fixed weights, original revision, sampling parameters, all output allowances, and shared-initial accounting. It overlaps model-file caching with CPU preparation, then stops analysis workers before timing live inference. SDPA, KV caching, inference mode, a fixed disposable warm-up, one model load, and a 64-token measured preflight are implemented. No full-VRAM utilization or fixed runtime is claimed.

Local verification used staged development runs; the original preparation fingerprint and final verification source hashes are retained with local evidence. The portable upload starts a fresh, source-bound experiment on the rental machine.
