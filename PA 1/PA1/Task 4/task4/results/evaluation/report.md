# Task 4: report to complete after inspecting outputs

## Measured changes relative to Vanilla MLS

- vanilla / mls: CSA +0.00 percentage points; near AUROC +0.0000; far AUROC +0.0000; near rejection +0.00 points; far rejection +0.00 points.
- gcsc / mls: CSA +0.15 percentage points; near AUROC +0.0291; far AUROC +0.0139; near rejection +5.25 points; far rejection +3.50 points.
- proser / mls: CSA -0.58 percentage points; near AUROC +0.0012; far AUROC -0.0282; near rejection -2.37 points; far rejection -10.50 points.
- proser / placeholder: CSA -0.58 percentage points; near AUROC -0.0467; far AUROC -0.0545; near rejection -5.25 points; far rejection -14.37 points.

## Interpretation prompts

1. Use per_unknown_class.csv and unknown_label_absorption.csv to identify the most frequently accepted classes and absorbing known labels. Inspect failure_examples.png and complete failure_interpretation.md; distinguish plausible semantic confusions from surprising visual failures.

2. Compare score_rank_correlations_*.csv, score_decision_disagreements_*.csv and individual disagreement examples. MSP measures relative confidence; MLS absolute maximum logit; Energy aggregate logit evidence; Mahalanobis feature distance. Connect actual disagreements to these mechanisms.

3. Use the GCSC MLS row to determine whether RandAugment improved CSA, near OSR, far OSR, both, or neither. Do not assume greater CSA guarantees better rejection.

4. Contrast PROSER MLS and placeholder rows with both baselines. Its two losses encourage a dummy alternative after excluding the true class and assign mixed inter-class features to unknown. Discuss whether observed rejection gains cost CSA, and why interpolation cannot cover all unknown directions.

Distinguish AUROC ranking from the validation-calibrated operating point. The target is 95% known VALIDATION acceptance; actual known TEST acceptance can differ. Optional RPL was not implemented.