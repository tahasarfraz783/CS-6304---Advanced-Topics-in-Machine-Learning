# Task 2 results audit

Verdict: the saved results are coherent and reproducible from the raw records. They
support useful visual grounding on these small selected subsets, with weaker counting
and natural-question consistency. There is one training-budget caveat: ten AMP-overflow
steps were skipped but counted by the launcher's update counter.

## Checks performed

- Both downloaded ZIPs matched their recorded SHA256 checksums and sizes and passed CRC checks.
- Training contains exactly 4,500 unique, contiguous attempt records, with stage counts
  2,250/1,500/750 and 72,000 example presentations. All recorded losses are finite.
- All 1,280 final records are unique and present: (128 grounding + 192 natural questions)
  × four conditions. Accuracy was recomputed from original references and predictions;
  no discrepancies were found.
- All 35 suite/type/condition bootstrap summary rows were recomputed using the supplied
  scoring implementation and seed; every numeric field matches to 1e-12.
- Saved evaluation references match the preselected manifest in every condition.
  Complementary swaps use partner images; mismatches match the fixed mapping and exclude
  both original-pair images.
- The manifest split audit passes: 8,876 train, 208 dev, 320 test images. Required natural
  and grounding pair counts are present.
- All 320 swapped predictions equal the corresponding partner's correct-image prediction.
  This is expected for deterministic greedy decoding with the same question and image;
  it is a consistency check, not a separate independent statistical discovery.
- No-image predictions are identical within all 160 pairs. Without an image, each pair
  supplies identical text, so deterministic answers should agree exactly.
- Development records occur at the required updates: 0,500,1000,1500,2000,2250,2500,
  3000,3500,3750,4000,4500.
- All three saved connectors and both saved LoRA adapters contain finite parameters.
  Connector parameters are FP32; the fixed calibration scalar is unchanged across stages.

## Why the learning curves make sense

Caption development loss falls from 5.499 initially to 2.340 after caption alignment.
It remains approximately 2.32–2.34 through the question-training stages, consistent
with replay limiting caption degradation.

Stage 1 does not monotonically improve short-answer NLL: grounding NLL is 7.208 at
its endpoint, and its swap penalty is slightly negative (-0.140). Caption alignment
alone has therefore not established reliable short-answer grounding. This is not a
reason to hide the intermediate curve or select a different final checkpoint.

At Stage 2's endpoint, grounding answer NLL falls to 0.739 and its swap penalty becomes
strongly positive (2.393). Natural-question NLL improves to 1.644 even before natural
specialization. At Stage 3's endpoint, natural NLL improves further to 0.905 with a
2.108 swap penalty; grounding NLL rises slightly to 0.765, while caption loss rises
slightly to 2.343. These are plausible specialization/replay tradeoffs.

No-image development NLL remains exactly constant throughout Stage 1. That is expected:
only the connector trains, and removing visual tokens removes its effect. It changes
after LoRA is enabled, also as expected.

## Final image controls

| Suite | Correct image | Complementary swap | Mismatched | No image |
|---|---:|---:|---:|---:|
| Grounding normalized exact match | 67.19% | 15.63% | 38.28% | 39.06% |
| Natural VQA soft consensus | 58.39% | 24.27% | 32.34% | 31.77% |

Correct-minus-swap accuracy advantages are 51.56 percentage points for grounding
(95% pair-bootstrap CI 37.50–64.84) and 34.11 points for natural VQA
(23.96–44.01). Corresponding swap-minus-correct NLL penalties are 2.405
(1.816–2.998) and 1.478 (1.089–1.899). Likelihood and generated answers therefore
agree that the correct image helps. These intervals describe the selected subsets,
not the full VQAv2 benchmark.

Presence is stronger than counting: 87.50% versus 46.88% correct-image exact match.
Natural VQA is strongest for yes/no (70.83%), followed by other (52.22%) and number
(48.96%). Their small sample sizes and different scoring rules prevent treating these
as precise or directly interchangeable capability estimates.

Pair accuracy is lower than per-question accuracy: 50.00% grounding and 31.25% natural.
Correct-image identical-answer rates remain 23.44% and 42.71%, respectively. Thus the
model uses images but still often fails to distinguish both complementary cases.
There are no empty outputs.

Natural no-image generation is slower despite a shorter prefix. Its answers average
2.82 content tokens rather than 1.13 with correct images; examples include full generic
sentences about cats/dogs. Longer answers make the timing direction plausible. Re-encoding
the saved outputs found none reaching 16 content tokens; these lengths do not recover
the original EOS/padding token trace exactly.

## Important qualification: optimizer skips

The training loop increments its counter even when GradScaler skips an optimizer step.
The saved logs show:

| Stage | Logged attempts | Skipped steps | Successful optimizer steps |
|---|---:|---:|---:|
| 1 | 2,250 | 5 | 2,245 |
| 2 | 1,500 | 3 | 1,497 |
| 3 | 750 | 2 | 748 |
| Total | 4,500 | 10 | 4,490 |

Skipped global attempts: 1,2,3,4,6,2251,2252,2264,3757,3823. These have nonfinite
unscaled gradient norms while the loss remains finite; the scaler lowers its scale
and correctly avoids applying those gradients. All saved final parameters are finite.

This affects 0.22% of attempted steps. It does not make the observed results nonsensical,
but the run is not literally 4,500 successful optimizer updates. Report 4,500 attempts,
72,000 presentations, and 10 AMP skips. Do not silently add ten final-stage updates:
that would not reproduce the missing steps in their original stages and would exceed
the prescribed presentation budget. A strict recipe correction would require a clearly
defined rerun policy; no rerun was performed during this audit.

The displayed phase ETA also underestimated remaining time because the phase timer
reset around evaluations while the counter retained the cumulative stage position.
This is a monitoring defect, not an accuracy/scoring defect.

## Costs and limits

Recorded training time totals 35.12 minutes; this invocation's wall time before
packaging is 45.45 minutes. Peak training allocation is approximately 5.09 GiB.
GPU samples across all phases have median utilization 47% and maximum 85%; those
samples include preparation and idle periods and do not prove optimal training utilization.
The low VRAM allocation alone does not establish either efficiency or inefficiency.

Annotation absence can miss visible objects, and counts can remain ambiguous even
after the documented broccoli/crowd policy. The label-review template is blank, so do
not claim a completed exhaustive human label audit. Small, high-agreement selected
subsets are not representative full-benchmark scores. Greedy generation, reference
likelihood, and pair accuracy answer different questions; discuss their agreement
and the remaining pair-level failures rather than claiming complete visual understanding.
