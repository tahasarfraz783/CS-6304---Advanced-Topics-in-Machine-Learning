"""Export manually reviewed qualitative cases from existing saved generations."""
from common.data import read_jsonl, repo_path
from common.logging_utils import save_json


def main():
    root = repo_path("results/task1_dpo")
    models = ("standard", "beta_0.03", "beta_0.10", "beta_0.30")
    generated = {model: {r["prompt_id"]: r for r in read_jsonl(root / f"{model}_generations.jsonl")}
                 for model in models}
    course = {r["prompt_id"]: r for r in read_jsonl("data/dpo_standard_eval.jsonl")}
    table_id = "f4f4c3cf74765eab1f5e06cf4088dd107b7ddf56e62d8f693485913f37ac8464"
    irony_id = "295d81c7643e12a8817bb6c78b753f5a8009b6a3d9d98441fb023bec8117db72"
    word = next(r for r in read_jsonl(root / "word_limit_paired_examples.jsonl") if r["prompt_id"] == "wl04")
    table_high = generated["beta_0.03"][table_id]
    table_low = generated["beta_0.30"][table_id]
    irony_high = generated["beta_0.10"][irony_id]
    irony_low = generated["beta_0.03"][irony_id]
    assert table_high["reward_score"] > table_low["reward_score"]
    assert irony_high["reward_score"] > irony_low["reward_score"]
    assert irony_high["response"] == "situational" and irony_low["response"] == "polarity"
    assert word["standard"]["words"] == 50 and word["length_balanced"]["words"] == 31
    evidence = {
        "method": "Manual inspection of saved generations; selected examples, not a representative error-rate estimate.",
        "reward_disagreements": [{"prompt_id": prompt_id, "course_pair": course[prompt_id],
                                  "generations": {model: generated[model][prompt_id] for model in models}}
                                 for prompt_id in (table_id, irony_id)],
        "instruction_compliance": word,
        "limits": "No frozen-reference generated-answer baseline; comparisons are between trained conditions. "
                  "No claim of systematic degradation, causal reward hacking, or aggregate correctness improvement."}
    save_json(root / "qualitative_evidence.json", evidence)
    report = f"""# Task 1: qualitative evidence and Research Question 3

These cases were selected by manually reviewing saved model answers and reward scores. No models were rerun. The two reward comparisons use short beta conditions with the same 600-example training budget. The length comparison uses the two 1,500-example runs.

## 1. Higher reward for fabricated answer-key content

Prompt ID: `{table_id}`.

The user asks for a three-column table and says, “I am going to give you some answers from an answer key.” No answers or explanations have been supplied. A grounded response should request that input before populating the table.

| Condition | Reward score | Observed behavior |
| --- | ---: | --- |
| Beta 0.03 | {table_high['reward_score']:.6f} | Invents five question/answer/explanation rows |
| Beta 0.30 | {table_low['reward_score']:.6f} | Requests the missing question numbers, answers, and explanations |

Minimum supporting excerpts:

- Higher-scored response: “Sure! Here is your table:” followed by invented entries such as question 1, answer A, “The correct answer is choice A.”
- Lower-scored response: “Could you please provide me with the list of question numbers and their corresponding answers?”

The higher-scored response is worse on grounding and instruction fulfillment: its entries cannot be extracted from an answer key that has not been provided. The lower-scored response appropriately waits for the missing information. The course-preferred answer also asks the user to provide the answers. A polished table receives a stronger reward signal despite unsupported content. This is consistent with the reward model valuing apparent completion or formatting, but this single example cannot establish why it assigned the score.

## 2. Higher reward for the wrong irony label

Prompt ID: `{irony_id}`.

The prompt defines polarity irony as inversion of the intended meaning and situational irony as an event that violates expectations. The tweet describes a tiring chase and ends with “#AintItFun !! #notfun”. The positive wording is explicitly reversed by the negative hashtag, supporting the label `polarity`. The course-preferred completion gives the same interpretation.

| Condition | Complete generated answer | Reward score |
| --- | --- | ---: |
| Beta 0.03 | `polarity` | {irony_low['reward_score']:.6f} |
| Beta 0.10 | `situational` | {irony_high['reward_score']:.6f} |

The wrong label receives a higher score by {irony_high['reward_score']-irony_low['reward_score']:.6f}. Both outputs are one-word answers, so the observed disagreement cannot be explained by the higher-scored answer being longer. It illustrates a task-specific correctness error that the general reward model does not reliably penalize.

## 3. Length and explicit instruction compliance

Prompt ID: `wl04`. Prompt: “Explain gradient descent in under 35 words.”

| Condition | Words | Generated tokens | Compliant? | Truncated? |
| --- | ---: | ---: | --- | --- |
| Standard | 50 | 61 | No | No |
| Length-balanced | 31 | 37 | Yes | No |

The standard answer gives the core explanation and adds “The process continues until convergence or a maximum number of iterations is reached.” That extra explanation is unnecessary to fulfill the requested short definition, and the complete answer exceeds the limit.

The balanced answer ends with “moving in the direction of steepest descent as defined by the negative of the gradient.” It retains the central idea while satisfying the word limit. Both answers finish naturally, so this comparison is not caused by generation truncation.

Across all ten prompts, mean response length falls from 42.5 to 39.8 words and compliance rises from 5/10 to 6/10. The improvement is modest: this prompt accounts for the one additional compliant response, and other prompts remain noncompliant. These data do not establish that length balancing universally improves concision or that every shorter answer is better.

## Report-ready answer to Research Question 3

Stronger reward signals did not always indicate better responses. In the answer-key task, the beta 0.03 model received a reward of {table_high['reward_score']:.3f} for inventing a table without the required source answers, while the beta 0.30 model received {table_low['reward_score']:.3f} for appropriately requesting the missing information. In the irony task, the incorrect label `situational` received {irony_high['reward_score']:.3f}, whereas the task-supported label `polarity` received {irony_low['reward_score']:.3f}. The latter comparison holds response length fixed at one word. These examples show that a preference or reward proxy can disagree with grounding and task-specific correctness. Offline DPO fits the supplied preferences rather than directly guaranteeing correctness or instruction compliance; therefore, reward scores should be interpreted alongside direct response inspection and explicit compliance checks. The word-limit study also shows a limited improvement from length balancing: the gradient-descent answer shrank from 50 to 31 words and became compliant, but total compliance improved by only one of ten prompts.

## Scope and traceability

- These are selected illustrative cases, not an estimate of how often reward and quality disagree.
- Reward scores are the supplied reward model's scalar outputs, not calibrated correctness probabilities.
- Comparisons are between trained conditions; no frozen-reference generated-answer comparison was collected.
- The examples do not prove that DPO caused degradation relative to the original model, or that reward hacking occurred.
- Word counts use the experiment's regex definition; “under 35” requires fewer than 35 words.
- Full prompts, responses, and course preference pairs are retained in [qualitative_evidence.json]({(root / 'qualitative_evidence.json').as_posix()}).
- Source generations: [beta 0.03]({(root / 'beta_0.03_generations.jsonl').as_posix()}), [beta 0.10]({(root / 'beta_0.10_generations.jsonl').as_posix()}), [beta 0.30]({(root / 'beta_0.30_generations.jsonl').as_posix()}).
- Word-limit source: [paired responses]({(root / 'word_limit_paired_examples.jsonl').as_posix()}).
"""
    path = root / "qualitative_evidence.md"
    path.write_text(report, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
