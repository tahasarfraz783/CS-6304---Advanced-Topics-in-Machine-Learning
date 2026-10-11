# Task 4 research answers



## 1. Do higher preference/reward scores correspond to better safety calibration?



The saved results do not establish a monotonic relationship. Standard DPO's Task 1 held-out implicit reward accuracy is 62.33%, preference accuracy 49.67%, and learned reward mean 1.2147 over 300 examples. Its safety audit still contains 12/30 safe over-refusals and one unsafe-compliance label among 30 unsafe responses. Preference objectives therefore do not certify calibrated safety.



On the common 200-prompt Tasks 2–3 evaluation, standard PPO learned reward is 1.7321 and standard GRPO is 1.7572. GRPO also has a slightly higher automated safe-answer rate (58.8% versus 57.6%) and one fewer safe over-refusal in the audit (10 versus 11). This descriptive concordance is weak: the AI judge is unreliable, the manual subset is small, and there is one class-inconsistent GRPO manual label. DPO's reward mean cannot be numerically ranked against these values because its evaluation prompts, decoding, cap, and reward regime differ. No matched SFT reward result is supplied here, so these measurements cannot establish improvement over SFT or optimizer causality.



## 2. Which policies confuse sensitive wording with harmful intent?



The supplied audit gives DPO the most safe over-refusals (40.0%), followed by PPO (36.7%), then SFT and GRPO (33.3% each). These differences are only one or two responses out of 30, not a robust population ranking. Beer-opening and similar benign requests expose confusion between threatening vocabulary and benign context. At the full-benchmark category level, safe privacy and historical prompts often receive the wrong JUSTIFIED_REFUSAL label; the AI output alone cannot determine whether every such case is an actual policy refusal.



Preference data may reward generic cautious responses, and reward models may correlate safety-associated phrasing with quality without tracking intent adequately. Continued policy optimization can preserve or amplify those correlations. These are plausible explanations, not measured causal mechanisms: no training-data attribution or factor-isolating intervention was performed, and the baseline also over-refuses. Context-sensitive preference examples and balanced benign/harmful contrasts are plausible future training signals, but Task 4 must not be used to retune the already frozen Tasks 1–3 checkpoints.



## 3. What does the AI judge misclassify, and how much does it affect the comparison?



It collapses the observed outputs to SAFE_ANSWER and JUSTIFIED_REFUSAL and assigns these labels across incompatible benchmark classes. Agreement with supplied manual labels is 76.7% SFT, 66.7% DPO, 75.0% PPO, and 78.3% GRPO. Overall, it agrees on 178/240 responses (74.17%); these observations share only 60 prompt IDs, so this pooled percentage is not an independent-sample uncertainty estimate.



All 43 supplied manual over-refusals across policies are missed as OVER_REFUSAL by the AI judge. It also misses the single supplied manual DPO unsafe-compliance case and all eight supplied manual ambiguous labels. The automated zero unsafe-compliance and over-refusal rates therefore conceal observed failure modes and should not support a claim that all policies are perfectly safe. Confusion matrices and paired response examples quantify these failures without discarding or silently remapping them.



The audit itself contains one class-inconsistent GRPO label that requires review. No confidence threshold or relabelling was applied after seeing results. Policy rankings remain descriptive, sensitive to annotation reliability, and unsupported as optimizer-specific causal conclusions.

