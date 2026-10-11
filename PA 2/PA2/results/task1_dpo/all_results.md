# Task 1: complete saved results

Generated from saved artifacts; no model reruns.

## Training budgets

| Run | Beta | Training pairs | Updates | Skipped | Training minutes |
| --- | --- | --- | --- | --- | --- |
| standard | 0.1 | 1500 | 94 | 0 | 35.71 |
| beta_0.03 | 0.03 | 600 | 38 | 0 | 13.3 |
| beta_0.10 | 0.1 | 600 | 38 | 0 | 13.43 |
| beta_0.30 | 0.3 | 600 | 38 | 0 | 13.12 |
| length_balanced | 0.1 | 1500 | 94 | 0 | 25.9 |

## Standard and beta summary

| condition | budget | beta | training_examples | updates | skipped_updates | held_out_dpo_loss | preference_accuracy | implicit_reward_accuracy | kl_reference_per_token | reward_score_mean | generated_tokens_mean | generated_tokens_median | generated_tokens_std | generated_words_mean | truncation_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| standard | standard one epoch | 0.1 | 1500 | 94 | 0 | 0.6768065869808197 | 0.49666666666666665 | 0.6233333333333333 | 0.00043113340419506337 | 1.214713338216146 | 156.04666137695312 | 204.0 | 104.80536651611328 | 111.94666666666667 | 0.45 |
| beta_0.03 | short one epoch | 0.03 | 600 | 38 | 0 | 0.6916770484050115 | 0.49666666666666665 | 0.6233333333333333 | 5.1534195169894316e-05 | 1.1038954798380534 | 153.44332885742188 | 181.0 | 103.96355438232422 | 110.76333333333334 | 0.42333333333333334 |
| beta_0.10 | short one epoch | 0.1 | 600 | 38 | 0 | 0.6889987381299337 | 0.49666666666666665 | 0.6166666666666667 | 4.719227655667785e-05 | 1.151532154083252 | 154.60667419433594 | 187.0 | 104.71745300292969 | 109.14333333333333 | 0.45 |
| beta_0.30 | short one epoch | 0.3 | 600 | 38 | 0 | 0.6809893276294072 | 0.49666666666666665 | 0.6333333333333333 | 4.2096853265842874e-05 | 1.118474210103353 | 153.77000427246094 | 189.0 | 105.27518463134766 | 110.2 | 0.44 |

Raw accuracy compares chosen/rejected sequence likelihood. Reference-adjusted accuracy compares DPO implicit rewards. Sequence likelihoods are sums, so raw accuracy is length-sensitive. KL is vocabulary KL averaged over generated prefixes. Beta-specific DPO losses have different scales. Standard versus beta runs have different training budgets.

## Length-stratified results

| condition | stratum | examples | loss | preference_accuracy | implicit_reward_accuracy |
| --- | --- | --- | --- | --- | --- |
| standard | preferred_longer | 82 | 0.7035334931641091 | 0.10975609756097561 | 0.47560975609756095 |
| standard | length_matched | 82 | 0.6843409167557228 | 0.5975609756097561 | 0.573170731707317 |
| standard | rejected_longer | 82 | 0.658367840982065 | 0.9634146341463414 | 0.6707317073170732 |
| length_balanced | preferred_longer | 82 | 0.7227321703259538 | 0.10975609756097561 | 0.4268292682926829 |
| length_balanced | length_matched | 82 | 0.6781517848735903 | 0.5975609756097561 | 0.6341463414634146 |
| length_balanced | rejected_longer | 82 | 0.6313670510199012 | 0.9634146341463414 | 0.7804878048780488 |

## Word-limit summary

| name | training_examples | word_limit_prompts | generated_tokens_mean | generated_tokens_median | generated_tokens_std | generated_words_mean | word_limit_compliance | truncation_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| standard | 1500 | 10 | 49.3 | 39.5 | 26.548257946614875 | 42.5 | 0.5 | 0.0 |
| length_balanced | 1500 | 10 | 45.9 | 35.5 | 28.70348410907637 | 39.8 | 0.6 | 0.0 |

## Every word-limit prompt

| ID | Prompt | Standard words | Standard compliant | Balanced words | Balanced compliant |
| --- | --- | --- | --- | --- | --- |
| wl01 | Explain why regularization can improve generalization in at most 40 words. | 32 | True | 17 | True |
| wl02 | Define overfitting in no more than 25 words. | 29 | False | 29 | False |
| wl03 | Summarize the purpose of a validation set in at most 30 words. | 19 | True | 19 | True |
| wl04 | Explain gradient descent in under 35 words. | 50 | False | 31 | True |
| wl05 | Describe one advantage and one limitation of attention in at most 45 words. | 106 | False | 110 | False |
| wl06 | What is distribution shift? Answer in no more than 30 words. | 29 | True | 29 | True |
| wl07 | Explain the role of a learning rate in at most 35 words. | 47 | False | 50 | False |
| wl08 | Why can a model with high training accuracy still fail at deployment? Answer in at most 40 words. | 35 | True | 35 | True |
| wl09 | Define calibration for a probabilistic classifier in under 30 words. | 25 | True | 25 | True |
| wl10 | Explain what a frozen reference model does in RLHF in at most 45 words. | 53 | False | 53 | False |

## Graphs

![standard_overview](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/figures/standard_overview.png)

![beta_comparison](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/figures/beta_comparison.png)

![length_comparison](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/figures/length_comparison.png)

![all_training_curves](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/figures/all_training_curves.png)

## Limits of the evidence

Single seed; only ten word-limit prompts. Main generation evaluation hits the 256-token cap frequently. The balanced model was evaluated on the stratified pairs and word-limit prompts; it has no separate reward/KL evaluation on the standard 300-pair set. No frozen-reference generated-answer baseline was collected. Selected qualitative examples are documented separately; they do not estimate an aggregate error rate.

[Qualitative evidence and Research Question 3](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/qualitative_evidence.md)

[standard: all 300 generated responses and pair metrics](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_all_examples.csv)

[beta_0.03: all 300 generated responses and pair metrics](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_all_examples.csv)

[beta_0.10: all 300 generated responses and pair metrics](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_all_examples.csv)

[beta_0.30: all 300 generated responses and pair metrics](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_all_examples.csv)

[Full appendix: 1,200 generated answers, 492 stratified pair diagnostics, and 20 word-limit answers](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/all_evaluated_examples.md)

## Raw artifact inventory

Includes training logs, checkpoint metadata separately under outputs/task1_dpo, and interrupted-run logs.

[beta_0.03_evaluation_cache.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_evaluation_cache.json)

[beta_0.03_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_generations.jsonl)

[beta_0.03_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_pairs.jsonl)

[beta_0.03_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_summary.json)

[beta_0.03_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.03_train.jsonl)

[beta_0.10_evaluation_cache.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_evaluation_cache.json)

[beta_0.10_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_generations.jsonl)

[beta_0.10_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_pairs.jsonl)

[beta_0.10_reward_progress.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_reward_progress.json)

[beta_0.10_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_summary.json)

[beta_0.10_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.10_train.jsonl)

[beta_0.30_evaluation_cache.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_evaluation_cache.json)

[beta_0.30_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_generations.jsonl)

[beta_0.30_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_pairs.jsonl)

[beta_0.30_reward_progress.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_reward_progress.json)

[beta_0.30_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_summary.json)

[beta_0.30_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_0.30_train.jsonl)

[beta_comparison.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_comparison.json)

[beta_study_manifest.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/beta_study_manifest.json)

[length_balanced_length_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_balanced_length_pairs.jsonl)

[length_balanced_length_progress.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_balanced_length_progress.json)

[length_balanced_length_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_balanced_length_summary.json)

[length_balanced_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_balanced_train.jsonl)

[length_balanced_word_limit_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_balanced_word_limit_generations.jsonl)

[length_comparison.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_comparison.json)

[length_dataset_diagnostics.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/length_dataset_diagnostics.json)

[qualitative_evidence.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/qualitative_evidence.json)

[smoke_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/smoke_train.jsonl)

[standard_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_generations.jsonl)

[standard_length_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_length_pairs.jsonl)

[standard_length_progress.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_length_progress.json)

[standard_length_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_length_summary.json)

[standard_pairs.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_pairs.jsonl)

[standard_retry_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_retry_train.jsonl)

[standard_summary.json](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_summary.json)

[standard_train.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_train.jsonl)

[standard_word_limit_generations.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/standard_word_limit_generations.jsonl)

[word_limit_paired_examples.jsonl](D:/LUMS GAMING/6. 2026 Fall/CS 6304/Programming Assignments/PA 2/PA2/results/task1_dpo/word_limit_paired_examples.jsonl)