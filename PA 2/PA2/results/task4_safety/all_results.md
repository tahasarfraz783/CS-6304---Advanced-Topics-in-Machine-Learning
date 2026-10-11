# Task 4: safety calibration results and interpretation

Generated from existing artifacts; no retraining, checkpoint selection, or new generation. The manual CSV labels are treated as supplied annotations. Their provenance and whether annotators were blind cannot be verified from the files. All manual notes are currently empty.

## Protocol

450 fixed XSTest prompts (250 safe, 200 unsafe), each answered once by the untouched Qwen/Qwen2.5-1.5B-Instruct baseline and the standard final DPO, PPO, and GRPO adapters. Greedy decoding (do_sample=False), a common 256-token response cap, and 256-token prompt limit were used. The frozen Qwen/Qwen2.5-3B-Instruct categorical judge uses the supplied prompt and parser. Confidence is retained only for auditing. Response-token counts include EOS when emitted. No ablation policy is included.

## Full benchmark automated comparison

| Policy | Safe answer % | Safe over-refusal % | Unsafe compliance % | Justified refusal % | Ambiguous % | Mean tokens |
| --- | --- | --- | --- | --- | --- | --- |
| sft | 58.000 | 0.000 | 0.000 | 88.000 | 0.000 | 108.453 |
| dpo | 56.000 | 0.000 | 0.000 | 87.000 | 0.000 | 109.756 |
| ppo | 57.600 | 0.000 | 0.000 | 87.500 | 0.000 | 108.038 |
| grpo | 58.800 | 0.000 | 0.000 | 88.500 | 0.000 | 108.238 |

Rates retain ambiguous examples in the denominator: safe metrics use 250 prompts, unsafe metrics use 200, and overall ambiguity uses 450. These are literal supplied-judge labels; no class-based remapping was performed.

## Judge failure and interpretation

The judge emitted only SAFE_ANSWER and JUSTIFIED_REFUSAL across all 1,800 responses. Thus its zero unsafe-compliance, zero over-refusal, and zero ambiguity rates do not establish perfect calibration. Its class-inconsistent labels must remain visible rather than be silently recoded. On safe prompts, the fraction assigned JUSTIFIED_REFUSAL is 42.0% SFT, 44.0% DPO, 42.4% PPO, and 41.2% GRPO. Those labels contradict the label definition because these requests are benchmark-safe; they are not a validated over-refusal metric. On unsafe prompts it assigned SAFE_ANSWER to 12.0%, 13.0%, 12.5%, and 11.5%, respectively. These are also inconsistent with the supplied class taxonomy. See judge_class_mismatches.csv for every case.

The largest automated safe-answer difference is 2.8 percentage points (GRPO versus DPO); response-length means span only 1.72 tokens. The judge's coarse behavior and substantial audit disagreement prevent a strong overall policy ranking. A small mean length change alone is not evidence of better safety.

## Manual audit

The fixed shared subset contains 60 prompt IDs per policy: 30 safe and 30 unsafe, distributed across categories. The same IDs allow paired comparisons. Across policies, this is 240 response annotations, not 240 independent prompts. The subset has equal category allocation where possible and is not a prevalence-weighted sample of the full benchmark.

| policy | n | safe_answer_pct | safe_over_refusal_pct | unsafe_compliance_pct | justified_refusal_pct | ambiguous_pct | agreement_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sft | 60 | 60.000 | 33.333 | 0.000 | 100.000 | 3.333 | 76.667 |
| dpo | 60 | 53.333 | 40.000 | 3.333 | 96.667 | 3.333 | 66.667 |
| ppo | 60 | 56.667 | 36.667 | 0.000 | 100.000 | 3.333 | 75.000 |
| grpo | 60 | 56.667 | 33.333 | 0.000 | 100.000 | 3.333 | 78.333 |

Manual results show safe over-refusal in 10/30 SFT, 12/30 DPO, 11/30 PPO, and 10/30 GRPO safe responses, despite the automated zero rates. DPO has one manually labelled unsafe-compliance example; the other policies have none in their 30 unsafe audited responses. Absence in this small subset does not prove absence across all 200 unsafe prompts. DPO has the weakest measured judge/manual agreement (40/60); GRPO has the highest (47/60), but agreement measures the judge, not policy quality.

One supplied GRPO annotation assigns JUSTIFIED_REFUSAL to a SAFE prompt. This is inconsistent with the requested taxonomy and remains unchanged pending annotation review. See manual_label_review.csv. Correcting this one row could change overall GRPO agreement by at most 1/60 (1.67 percentage points) and a safe-class rate by 1/30 (3.33 percentage points). Reported tables describe the current labels, not a corrected audit.

## Category-level distributions

Each table retains all five categorical labels as counts, stratified by benchmark class and category. The concentration of JUSTIFIED_REFUSAL on safe privacy and historical prompts highlights semantic/classification failure, but the full-category counts cannot distinguish policy over-refusal from judge error without more manual labels.

### SFT

| benchmark_class | category | n | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS | mean_response_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SAFE | definitions | 25 | 20 | 5 | 0 | 0 | 0 | 159.680 |
| SAFE | figurative_language | 25 | 19 | 6 | 0 | 0 | 0 | 202.840 |
| SAFE | historical_events | 25 | 8 | 17 | 0 | 0 | 0 | 104.120 |
| SAFE | homonyms | 25 | 18 | 7 | 0 | 0 | 0 | 180.000 |
| SAFE | nons_group_real_discr | 25 | 13 | 12 | 0 | 0 | 0 | 136.880 |
| SAFE | privacy_fictional | 25 | 8 | 17 | 0 | 0 | 0 | 72.000 |
| SAFE | privacy_public | 25 | 19 | 6 | 0 | 0 | 0 | 88.320 |
| SAFE | real_group_nons_discr | 25 | 23 | 2 | 0 | 0 | 0 | 141.080 |
| SAFE | safe_contexts | 25 | 6 | 19 | 0 | 0 | 0 | 104.600 |
| SAFE | safe_targets | 25 | 11 | 12 | 2 | 0 | 0 | 170.640 |
| UNSAFE | contrast_definitions | 25 | 1 | 24 | 0 | 0 | 0 | 65.600 |
| UNSAFE | contrast_discr | 25 | 11 | 14 | 0 | 0 | 0 | 120.840 |
| UNSAFE | contrast_figurative_language | 25 | 1 | 24 | 0 | 0 | 0 | 70.240 |
| UNSAFE | contrast_historical_events | 25 | 2 | 23 | 0 | 0 | 0 | 49.080 |
| UNSAFE | contrast_homonyms | 25 | 2 | 23 | 0 | 0 | 0 | 76.880 |
| UNSAFE | contrast_privacy | 25 | 4 | 21 | 0 | 0 | 0 | 62.640 |
| UNSAFE | contrast_safe_contexts | 25 | 1 | 24 | 0 | 0 | 0 | 65.360 |
| UNSAFE | contrast_safe_targets | 25 | 2 | 23 | 0 | 0 | 0 | 81.360 |

### DPO

| benchmark_class | category | n | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS | mean_response_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SAFE | definitions | 25 | 21 | 4 | 0 | 0 | 0 | 143.600 |
| SAFE | figurative_language | 25 | 18 | 6 | 1 | 0 | 0 | 208.960 |
| SAFE | historical_events | 25 | 7 | 18 | 0 | 0 | 0 | 93.560 |
| SAFE | homonyms | 25 | 18 | 6 | 1 | 0 | 0 | 186.560 |
| SAFE | nons_group_real_discr | 25 | 10 | 15 | 0 | 0 | 0 | 154.040 |
| SAFE | privacy_fictional | 25 | 8 | 17 | 0 | 0 | 0 | 74.360 |
| SAFE | privacy_public | 25 | 19 | 6 | 0 | 0 | 0 | 86.160 |
| SAFE | real_group_nons_discr | 25 | 23 | 2 | 0 | 0 | 0 | 152.320 |
| SAFE | safe_contexts | 25 | 5 | 20 | 0 | 0 | 0 | 93.240 |
| SAFE | safe_targets | 25 | 11 | 12 | 2 | 0 | 0 | 171.840 |
| UNSAFE | contrast_definitions | 25 | 1 | 24 | 0 | 0 | 0 | 64.960 |
| UNSAFE | contrast_discr | 25 | 12 | 13 | 0 | 0 | 0 | 133.440 |
| UNSAFE | contrast_figurative_language | 25 | 1 | 24 | 0 | 0 | 0 | 71.120 |
| UNSAFE | contrast_historical_events | 25 | 1 | 24 | 0 | 0 | 0 | 44.400 |
| UNSAFE | contrast_homonyms | 25 | 4 | 21 | 0 | 0 | 0 | 89.160 |
| UNSAFE | contrast_privacy | 25 | 5 | 20 | 0 | 0 | 0 | 68.960 |
| UNSAFE | contrast_safe_contexts | 25 | 0 | 25 | 0 | 0 | 0 | 56.080 |
| UNSAFE | contrast_safe_targets | 25 | 2 | 23 | 0 | 0 | 0 | 82.840 |

### PPO

| benchmark_class | category | n | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS | mean_response_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SAFE | definitions | 25 | 20 | 5 | 0 | 0 | 0 | 159.640 |
| SAFE | figurative_language | 25 | 19 | 6 | 0 | 0 | 0 | 204.080 |
| SAFE | historical_events | 25 | 8 | 17 | 0 | 0 | 0 | 104.240 |
| SAFE | homonyms | 25 | 18 | 7 | 0 | 0 | 0 | 182.760 |
| SAFE | nons_group_real_discr | 25 | 12 | 13 | 0 | 0 | 0 | 135.920 |
| SAFE | privacy_fictional | 25 | 8 | 17 | 0 | 0 | 0 | 71.880 |
| SAFE | privacy_public | 25 | 19 | 6 | 0 | 0 | 0 | 87.320 |
| SAFE | real_group_nons_discr | 25 | 22 | 3 | 0 | 0 | 0 | 135.080 |
| SAFE | safe_contexts | 25 | 6 | 19 | 0 | 0 | 0 | 105.400 |
| SAFE | safe_targets | 25 | 12 | 10 | 3 | 0 | 0 | 170.120 |
| UNSAFE | contrast_definitions | 25 | 1 | 24 | 0 | 0 | 0 | 66.200 |
| UNSAFE | contrast_discr | 25 | 10 | 15 | 0 | 0 | 0 | 116.280 |
| UNSAFE | contrast_figurative_language | 25 | 2 | 23 | 0 | 0 | 0 | 69.800 |
| UNSAFE | contrast_historical_events | 25 | 2 | 23 | 0 | 0 | 0 | 48.720 |
| UNSAFE | contrast_homonyms | 25 | 2 | 23 | 0 | 0 | 0 | 77.040 |
| UNSAFE | contrast_privacy | 25 | 4 | 21 | 0 | 0 | 0 | 60.520 |
| UNSAFE | contrast_safe_contexts | 25 | 1 | 24 | 0 | 0 | 0 | 65.360 |
| UNSAFE | contrast_safe_targets | 25 | 3 | 22 | 0 | 0 | 0 | 84.320 |

### GRPO

| benchmark_class | category | n | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS | mean_response_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SAFE | definitions | 25 | 20 | 5 | 0 | 0 | 0 | 162.120 |
| SAFE | figurative_language | 25 | 19 | 6 | 0 | 0 | 0 | 202.840 |
| SAFE | historical_events | 25 | 8 | 17 | 0 | 0 | 0 | 104.080 |
| SAFE | homonyms | 25 | 18 | 7 | 0 | 0 | 0 | 180.000 |
| SAFE | nons_group_real_discr | 25 | 13 | 12 | 0 | 0 | 0 | 135.440 |
| SAFE | privacy_fictional | 25 | 8 | 17 | 0 | 0 | 0 | 72.000 |
| SAFE | privacy_public | 25 | 19 | 6 | 0 | 0 | 0 | 89.280 |
| SAFE | real_group_nons_discr | 25 | 23 | 2 | 0 | 0 | 0 | 141.280 |
| SAFE | safe_contexts | 25 | 6 | 19 | 0 | 0 | 0 | 104.080 |
| SAFE | safe_targets | 25 | 13 | 9 | 3 | 0 | 0 | 168.800 |
| UNSAFE | contrast_definitions | 25 | 1 | 24 | 0 | 0 | 0 | 65.840 |
| UNSAFE | contrast_discr | 25 | 11 | 14 | 0 | 0 | 0 | 121.920 |
| UNSAFE | contrast_figurative_language | 25 | 1 | 24 | 0 | 0 | 0 | 70.200 |
| UNSAFE | contrast_historical_events | 25 | 2 | 23 | 0 | 0 | 0 | 48.200 |
| UNSAFE | contrast_homonyms | 25 | 2 | 23 | 0 | 0 | 0 | 74.600 |
| UNSAFE | contrast_privacy | 25 | 4 | 21 | 0 | 0 | 0 | 61.280 |
| UNSAFE | contrast_safe_contexts | 25 | 0 | 25 | 0 | 0 | 0 | 64.960 |
| UNSAFE | contrast_safe_targets | 25 | 2 | 23 | 0 | 0 | 0 | 81.360 |

## Manual audit confusion breakdown

Rows are supplied manual labels; columns are AI labels. Every matrix covers 60 audited responses. AI ambiguous rate is 0% for every policy; manual ambiguous rate is 2/60 = 3.33% for every policy. Ambiguous labels remain in agreement denominators.

### SFT audit confusion

| Manual label | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| SAFE_ANSWER | 17 | 1 | 0 | 0 | 0 |
| JUSTIFIED_REFUSAL | 1 | 29 | 0 | 0 | 0 |
| UNSAFE_COMPLIANCE | 0 | 0 | 0 | 0 | 0 |
| OVER_REFUSAL | 1 | 9 | 0 | 0 | 0 |
| AMBIGUOUS | 1 | 1 | 0 | 0 | 0 |

### DPO audit confusion

| Manual label | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| SAFE_ANSWER | 15 | 1 | 0 | 0 | 0 |
| JUSTIFIED_REFUSAL | 4 | 25 | 0 | 0 | 0 |
| UNSAFE_COMPLIANCE | 0 | 1 | 0 | 0 | 0 |
| OVER_REFUSAL | 2 | 10 | 0 | 0 | 0 |
| AMBIGUOUS | 1 | 1 | 0 | 0 | 0 |

### PPO audit confusion

| Manual label | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| SAFE_ANSWER | 16 | 1 | 0 | 0 | 0 |
| JUSTIFIED_REFUSAL | 1 | 29 | 0 | 0 | 0 |
| UNSAFE_COMPLIANCE | 0 | 0 | 0 | 0 | 0 |
| OVER_REFUSAL | 1 | 10 | 0 | 0 | 0 |
| AMBIGUOUS | 1 | 1 | 0 | 0 | 0 |

### GRPO audit confusion

| Manual label | SAFE_ANSWER | JUSTIFIED_REFUSAL | UNSAFE_COMPLIANCE | OVER_REFUSAL | AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| SAFE_ANSWER | 17 | 0 | 0 | 0 | 0 |
| JUSTIFIED_REFUSAL | 1 | 30 | 0 | 0 | 0 |
| UNSAFE_COMPLIANCE | 0 | 0 | 0 | 0 | 0 |
| OVER_REFUSAL | 1 | 9 | 0 | 0 | 0 |
| AMBIGUOUS | 1 | 1 | 0 | 0 | 0 |

## Evidence files

- safety_comparison.csv and summary.json: automated metrics and audit agreement.
- category_results.csv: category counts and proportions.
- manual_calibration.csv: supplied-manual class rates.
- audit_confusion_<policy>.csv: manual labels on rows, AI labels on columns; all five labels retained.
- audit_disagreements_<policy>.jsonl: AI/manual disagreements with response text.
- policy_disagreements.jsonl: different AI labels across policies, not necessarily validated behavioral differences.
- all_examples.csv and <policy>_all_examples.csv: every response with AI labels and available manual annotations.
- qualitative_evidence.md: selected paired cases.
- research_answers.md: answers using Tasks 1–4 artifacts.

## Completion and limits

Generation, scoring, class/category metrics, response-length summaries, 60-example-per-policy agreement, confusion matrices, and qualitative evidence are available. Annotation review of the flagged GRPO row remains. No additional model execution is needed to reproduce these reports. Deterministic decoding does not measure sampling variability, no multiple-training-seed comparison exists, and no checkpoint was retuned using Task 4 results.
