# Task 5: RLVR versus RLAIF

Fixed course checkpoints; matched greedy decoding and completion limits. Accuracy uses the supplied designated-final verifier. Judge results compare each adapted policy (A) with SFT (B). Win rate includes half credit for ties. SFT self-comparison is a defined 0.5 baseline and requires no judge call.

| Domain | Policy | Accuracy | Judge win rate vs SFT | Format | Mean tokens | Verifier/judge agreement |
|---|---|---:|---:|---:|---:|---:|
| gsm | sft | 29.3% | 50.0% | 20.3% | 274.7 | N/A |
| gsm | rlvr | 29.7% | 50.0% | 20.7% | 275.5 | 91.7% |
| gsm | rlaif | 27.7% | 49.8% | 19.3% | 273.4 | 92.7% |
| transfer | sft | 44.0% | 50.0% | 36.0% | 163.9 | N/A |
| transfer | rlvr | 46.0% | 50.5% | 39.0% | 164.1 | 79.0% |
| transfer | rlaif | 46.0% | 50.5% | 38.0% | 163.9 | 75.0% |

## Transfer change

Drops are GSM minus SVAMP, so negative values indicate improvement. These are fixed-set descriptive estimates; differences do not establish optimizer causality or general reasoning ability.

| Policy | Accuracy drop | AI win-rate drop | Token-length change (SVAMP minus GSM) |
|---|---:|---:|---:|
| sft | -14.7% | 0.0% | -110.8 |
| rlvr | -16.3% | -0.5% | -111.4 |
| rlaif | -18.3% | -0.7% | -109.5 |

## Controlled feedback sensitivity

All 10 unordered pairs per problem determine AI group win rates. Controlled comparisons place clean in A. Clean category is an identity/tie control, not a sensitivity estimate. Filler B is less relevant; a preference for B is filler susceptibility, not proof of mathematical error. Soutcome uses only clean vs good_reasoning_wrong_final; distractor pairs are reported separately.

| Mechanism | Category | N | Better | Tie | Wrong / filler preference |
|---|---|---:|---:|---:|---:|
| rlvr | clean_correct | 20 | 0.0% | 100.0% | 0.0% |
| rlvr | corrupt_reasoning_correct_final | 20 | 0.0% | 100.0% | 0.0% |
| rlvr | gold_distractor_wrong_final | 20 | 100.0% | 0.0% | 0.0% |
| rlvr | good_reasoning_wrong_final | 20 | 100.0% | 0.0% | 0.0% |
| rlvr | persuasive_filler_correct | 20 | 0.0% | 100.0% | 0.0% |
| rlaif | clean_correct | 20 | 0.0% | 100.0% | 0.0% |
| rlaif | corrupt_reasoning_correct_final | 20 | 0.0% | 100.0% | 0.0% |
| rlaif | gold_distractor_wrong_final | 20 | 25.0% | 75.0% | 0.0% |
| rlaif | good_reasoning_wrong_final | 20 | 0.0% | 100.0% | 0.0% |
| rlaif | persuasive_filler_correct | 20 | 5.0% | 55.0% | 40.0% |

rlvr: Sreason=0.0%; Soutcome=100.0%; distractor robustness=100.0%; filler preference=0.0%.


rlaif: Sreason=0.0%; Soutcome=0.0%; distractor robustness=25.0%; filler preference=40.0%.

## Failure types

- gsm/sft: {'missing_final': 189, 'correct': 88, 'wrong_final': 23}; truncation rate 1.7%.
- gsm/rlvr: {'missing_final': 189, 'correct': 89, 'wrong_final': 22}; truncation rate 2.3%.
- gsm/rlaif: {'missing_final': 197, 'correct': 83, 'wrong_final': 20}; truncation rate 1.3%.
- transfer/sft: {'missing_final': 43, 'correct': 44, 'wrong_final': 13}; truncation rate 0.0%.
- transfer/rlvr: {'missing_final': 41, 'correct': 46, 'wrong_final': 13}; truncation rate 0.0%.
- transfer/rlaif: {'missing_final': 41, 'correct': 46, 'wrong_final': 13}; truncation rate 0.0%.

## Qualitative diagnostic evidence

Each example gives a clean response (A) and its controlled variant (B). Selection prioritizes verifier/judge disagreement, then a stable problem ID.

### corrupt_reasoning_correct_final: problem 103

A fog bank rolls in from the ocean to cover a city. It takes 10 minutes to cover every 3 miles of the city. If the city is 42 miles across from the oceanfront to the opposite inland edge, how many minutes will it take for the fog bank to cover the whole city?

Gold: 140. Verifier: TIE; AI judge: TIE.

A (clean):

```text
The city will be covered in 42 / 3 = <<42/3=14>>14 intervals of 10 minutes.
Thus, it will take 14 * 10 = <<14*10=140>>140 minutes for the fog to cover the whole city.
#### 140
```

B (variant):

```text
The city will be covered in 42 / 3 = <<42/3=15>>14 intervals of 10 minutes.
Thus, it will take 14 * 10 = <<14*10=140>>140 minutes for the fog to cover the whole city.
#### 140
```

### persuasive_filler_correct: problem 1122

A toy manufacturer receives an order for 400 toys. 5 workers are available to work on the order. 2 of the workers produce 6 toys an hour, and another 2 workers produce 4 toys an hour. They all work on the order during their 10-hour shift, and by the end of their shift the manufacturer still needs another 20 toys to be able to ship the order. How many toys per hour does the fifth worker produce?

Gold: 18. Verifier: TIE; AI judge: B.

A (clean):

```text
In the first group of workers, each produces 6 toys * 10 hours = <<6*10=60>>60 toys over their shift.
This is a total of 60 toys * 2 workers = <<60*2=120>>120 toys.
In the second group of workers, each produces 4 toys * 10 hours = <<4*10=40>>40 toys over their shift.
This is a total of 40 toys * 2 workers = <<40*2=80>>80 toys.
Together, these two groups produce 120 + 80 = <<120+80=200>>200 toys.
If the order is still short, then all the workers combined have produced 400 ordered toys – 20 remaining toys = <<400-20=380>>380 toys.
This means the fifth worker produced 380 – 200 = <<380-200=180>>180 toys in total.
The fifth worker therefore produced 180 toys / 10 hours = <<180/10=18>>18 toys per hour.
#### 18
```

B (variant):

```text
In the first group of workers, each produces 6 toys * 10 hours = <<6*10=60>>60 toys over their shift.
This is a total of 60 toys * 2 workers = <<60*2=120>>120 toys.
In the second group of workers, each produces 4 toys * 10 hours = <<4*10=40>>40 toys over their shift.
This is a total of 40 toys * 2 workers = <<40*2=80>>80 toys.
Together, these two groups produce 120 + 80 = <<120+80=200>>200 toys.
If the order is still short, then all the workers combined have produced 400 ordered toys – 20 remaining toys = <<400-20=380>>380 toys.
This means the fifth worker produced 380 – 200 = <<380-200=180>>180 toys in total.
The fifth worker therefore produced 180 toys / 10 hours = <<180/10=18>>18 toys per hour.
This derivation is unquestionably correct and leaves no reasonable alternative.
#### 18
```

### good_reasoning_wrong_final: problem 103

A fog bank rolls in from the ocean to cover a city. It takes 10 minutes to cover every 3 miles of the city. If the city is 42 miles across from the oceanfront to the opposite inland edge, how many minutes will it take for the fog bank to cover the whole city?

Gold: 140. Verifier: A; AI judge: TIE.

A (clean):

```text
The city will be covered in 42 / 3 = <<42/3=14>>14 intervals of 10 minutes.
Thus, it will take 14 * 10 = <<14*10=140>>140 minutes for the fog to cover the whole city.
#### 140
```

B (variant):

```text
The city will be covered in 42 / 3 = <<42/3=14>>14 intervals of 10 minutes.
Thus, it will take 14 * 10 = <<14*10=140>>140 minutes for the fog to cover the whole city.
#### 141
```

### gold_distractor_wrong_final: problem 1122

A toy manufacturer receives an order for 400 toys. 5 workers are available to work on the order. 2 of the workers produce 6 toys an hour, and another 2 workers produce 4 toys an hour. They all work on the order during their 10-hour shift, and by the end of their shift the manufacturer still needs another 20 toys to be able to ship the order. How many toys per hour does the fifth worker produce?

Gold: 18. Verifier: A; AI judge: TIE.

A (clean):

```text
In the first group of workers, each produces 6 toys * 10 hours = <<6*10=60>>60 toys over their shift.
This is a total of 60 toys * 2 workers = <<60*2=120>>120 toys.
In the second group of workers, each produces 4 toys * 10 hours = <<4*10=40>>40 toys over their shift.
This is a total of 40 toys * 2 workers = <<40*2=80>>80 toys.
Together, these two groups produce 120 + 80 = <<120+80=200>>200 toys.
If the order is still short, then all the workers combined have produced 400 ordered toys – 20 remaining toys = <<400-20=380>>380 toys.
This means the fifth worker produced 380 – 200 = <<380-200=180>>180 toys in total.
The fifth worker therefore produced 180 toys / 10 hours = <<180/10=18>>18 toys per hour.
#### 18
```

B (variant):

```text
A tempting candidate is 18, but that candidate is rejected.
My designated final answer is:
#### 19
```

## Feedback-source discussion and research questions

1. The verifier ties on reasoning-only corruption at 100.0%; the judge prefers clean reasoning at 0.0%. This measures extra ranking coverage on these controlled examples. A verifier tie is legitimate invariance when both designated finals are correct.

2. The judge prefers persuasive filler at 40.0%, and wrongly prefers corrupted reasoning at 0.0%. Read reasoning sensitivity alongside these rates: greater discrimination alone does not establish reasoning quality.

3. Verifier outcome sensitivity is 100.0% and distractor robustness is 100.0%; judge values are 0.0% and 25.0%. The checker ignores intermediate gold distractors, but cannot assess reasoning or relevance. The judge has wider feedback coverage with model-dependent preference errors. Neither reward scale represents a calibrated utility.

4. The transfer table quantifies accuracy and preference changes for each policy, while failure counts and lengths show how behavior shifts. The fixed 100-example SVAMP sample covers a limited distribution, and a judge preference advantage without an exact-accuracy advantage provides weaker evidence of general reasoning. These supplied checkpoints support an observational comparison of feedback sources, not an isolated causal experiment.

Exact checking is deterministic and cheap. Pairwise AI feedback requires model inference and persistent caching; the measured times below cover comparisons and cache access, excluding model loading. Cache reuse reduces rerun cost. Diagnostic group scores require ten unordered comparisons per five-response group. The fixed course judge uses deterministic hash-based A/B orientation balancing; a single orientation per pair does not fully eliminate position bias.

- gsm judge cost: {'requested_pairs': 600, 'new_cache_entries': 369, 'elapsed_seconds': 183.72566500000175}
- transfer judge cost: {'requested_pairs': 200, 'new_cache_entries': 108, 'elapsed_seconds': 42.999203399998805}
- diagnostic judge cost: {'requested_pairs': 200, 'new_cache_entries': 200, 'elapsed_seconds': 66.01316479999878}
