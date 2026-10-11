# Task 4 evidence checklist

Checked against the corrected Task 4 screenshot and original pasted specification.

| Requirement | Evidence | Status |
| --- | --- | --- |
| Four standard policies and all six calibration/length metrics | all_results.md; safety_comparison.csv; summary.json | Complete |
| All five judge labels by XSTest category for each policy | all_results.md category tables; category_results.csv | Complete |
| Fixed 60-example audit per policy, agreement, confusion breakdown, ambiguity | all_results.md embedded confusion matrices; audit_confusion_*.csv; manual_calibration.csv; summary.json | Metrics complete; one supplied annotation needs review |
| Harmful compliance, justified refusal, exaggerated refusal; policy difference, judge error, or both | qualitative_evidence.md; audit_disagreements_*.jsonl | Complete; borderline compliance interpretation disclosed |
| Research question 1: preference/reward versus safety | research_answers.md, question 1 | Answered with earlier scores and comparability limits |
| Research question 2: sensitive wording versus harmful intent | research_answers.md, question 2 | Answered; training-signal mechanisms remain hypotheses |
| Research question 3: judge errors and comparison impact | research_answers.md, question 3 | Answered with measured disagreement |

Both safe over-refusal and unsafe compliance/refusal are reported. The judge is treated as an evaluation instrument: its zero over-refusal and unsafe-compliance rates are not accepted as proof of perfect safety. Comparisons are observational, with no optimizer-specific causal claims or safety-based checkpoint selection.

The supplied GRPO manual label at xstest_id 406 assigns JUSTIFIED_REFUSAL to a benchmark-safe prompt. It remains unchanged pending annotation review. File contents cannot establish whether annotation was independent or blind.

After correcting any manual annotation, regenerate reports from PA2 without model reruns:

```powershell
.\.venv\Scripts\python.exe -m task4_safety.evaluate_safety --config configs/feedback.yaml
.\.venv\Scripts\python.exe -m task4_safety.report_results
```
