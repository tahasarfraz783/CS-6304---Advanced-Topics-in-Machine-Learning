# Task 4 safety calibration

Run from the PA2 directory using the existing virtual environment. Tasks 1–3 must be complete first. The feedback configuration uses the untouched base policy and the standard final adapters; never replace them with ablation checkpoints based on safety results.

```powershell
. .\activate.ps1
python -m unittest task4_safety.test_safety
python -m task4_safety.generate_responses --config configs/feedback.yaml --batch-size 4
python -m task4_safety.make_audit_sheet --config configs/feedback.yaml
```

Fill `manual_label` in each `results/task4_safety/manual_audit_<policy>.csv` without viewing AI judgments. Each sheet contains the same fixed 60 prompt IDs, 30 safe and 30 unsafe, sampled across categories. Use SAFE_ANSWER, JUSTIFIED_REFUSAL, UNSAFE_COMPLIANCE, OVER_REFUSAL, or AMBIGUOUS. Add notes for qualitative interpretation. This is 240 response judgments across four policies. Existing ID lists and human sheets are preserved on reruns.

Then run:

```powershell
python -m task4_safety.judge_responses --config configs/feedback.yaml
python -m task4_safety.evaluate_safety --config configs/feedback.yaml
```

The judge requires Qwen/Qwen2.5-3B-Instruct (downloaded on first use); its supplied prompt, parser, and scorer are unchanged. Judgment files resume from validated completed prefixes. Generation overwrites its response files; rerun judging only after removing any incompatible old judgment cache.

Outputs include safety_comparison.csv, category_results.csv (all five labels, counts and rates), summary.json, audit_confusion_<policy>.csv (manual rows, AI columns), audit_disagreements_<policy>.jsonl, and policy_disagreements.jsonl. Safe and unsafe rates use their respective class denominators. Ambiguous judgments remain in denominators. Confidence is not a reward or aggregation weight. Response lengths include EOS when emitted, matching the shared generation utility.

An empty manual sheet is reported as pending; partially completed sheets are reported as partial, never full audit agreement. Complete all human labels for final evidence. For the report, inspect disagreements and choose brief examples covering harmful compliance, justified refusal, and over-refusal. Identify policy differences versus judge errors, qualify automated results with audit reliability, and answer the three research questions using actual Tasks 1–3 scores. Do not infer optimizer causality from this observational comparison or invent missing measurements.
