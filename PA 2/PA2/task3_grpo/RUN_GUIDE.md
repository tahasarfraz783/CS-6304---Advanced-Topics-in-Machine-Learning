# Task 3: GRPO

Run commands from `PA2`, using the local environment:

```powershell
. .\activate.ps1
python -m unittest task3_grpo.test_grpo
python -m task3_grpo.run_all
```

`run_all` executes a 20-update standard continuation, evaluates its saved adapter on the full held-out pool, analyzes the supplied group cache, runs two 8-update normalization branches and evaluates them, then writes the report and diagnostic plot.

Models use the supplied GRPO midpoint, the base policy with its adapter disabled as reference (matching PPO), and the same NF4 reward scorer as local PPO. Completions are generated and differentiated serially, with gradients accumulated before each optimizer step. This avoids a simultaneous K-completion graph on the 6 GB GPU. Adapter dropout probabilities are set to zero for consistent rollout and update probabilities; training mode keeps backbone gradient checkpointing active. Trainable weights use FP32 and CUDA GradScaler handles mixed-precision gradients. All-truncated batches are logged and skip the optimizer step.

## Individual commands

```powershell
python -m task3_grpo.continue_train
python -m task3_grpo.evaluate --adapter outputs/task3_grpo/standard
python -m task3_grpo.analyze_group_size
python -m task3_grpo.compare_normalization
python -m task3_grpo.report_results
```

Training and evaluation refuse to overwrite existing runs. If interrupted, completed artifacts remain; run the remaining individual commands. There is no automatic recovery of a partially completed training run. Use a new `--run-name` and `--output` for standard training, or a new `--prefix` for the normalization comparison. Evaluate custom standard runs using a matching `--name`; pass the matching `--run-name` and comparison `--prefix` to the report exporter.

## Controlled normalization design

The comparison generates a shared rollout plan from the unchanged midpoint, then independently loads that midpoint for each branch. Both branches use exactly the same prompts, completions, rewards, reference log probabilities, behavior log probabilities, and generated and unmasked token budgets. Only `loss_type` changes. The reward is not divided by reward standard deviation differently between conditions: both use the assignment's group-relative advantages; the supplied Dr. GRPO condition changes sequence normalization only.

This is a fixed-rollout replay comparison. Later updates are off-policy relative to the unchanged midpoint generator, using the clipped importance ratio against the saved generator log probabilities. It isolates normalization without confounding different generated token counts. It is not a comparison of independently sampled on-policy training trajectories. State this design in the report. Held-out evaluation generates fresh completions for each resulting adapter using identical prompts, per-prompt seeds, sampling settings, and length cap.

The standard continuation is on-policy and generates fresh groups before each update. Its training response cap is 512; evaluation uses 768, matching the local PPO evaluation cap. Max-length completions without EOS are excluded from both policy and KL training losses but retained in reward, response-length, and group statistics. Advantages use all K rewards before applying truncation masks.

## Evidence

Outputs are saved under `outputs/task3_grpo`; measurements are under `results/task3_grpo`:

- `standard_train.jsonl`: per-update diagnostics, optimizer skips, and per-completion length statistics.
- `standard_summary.json`: run configuration, elapsed time including loading, peak allocated VRAM, token counts.
- `standard_rollouts.jsonl` and `standard_eval.jsonl`: prompts, responses, rewards, and evaluation diagnostics.
- `group_size_comparison.json`: equal-generation statistics, fixed difficulty bins, and qualitative examples.
- `normalization_midpoint_rollouts.pt`: shared generation plan, generated once.
- `normalization_comparison.json`: matched budgets, held-out results, and length-conditioned gradient allocation.
- `all_results.md` and `standard_diagnostics.png`: report evidence and continuation curves.

The length statistic is the L1 derivative of the loss with respect to sampled token log probabilities. The additional `policy_gradient_weight` is `1/B` for canonical GRPO and `T/(B*max_completion_length)` for Dr. GRPO on an unmasked completion, directly testing the normalization effect independently of reward and KL. Length bins use the median response length of unmasked completions in the shared generation plan. Masked responses are excluded from these bins.

Group-size analysis sorts each prompt's eight cached completions by generation index and partitions them into disjoint groups. Every completion is used once for every K. Difficulty is a reward-based proxy: mean reward across all eight completions is compared with the global median. Informative groups have population reward standard deviation greater than 1e-6. Standardized advantage variance is largely determined by the informative-group fraction; do not interpret it as an independent estimate of raw reward uncertainty.

Training KL is the k3 estimator in the supplied objective. Held-out KL is the same sampled log-probability-difference estimator used in PPO; finite-sample estimates can be negative. Entropy is sampled negative log probability, not exact categorical entropy. Use the same estimator when comparing conditions.

The generated report contains measurements and examples. Complete the research-question discussion after the runs finish; do not treat smoke-test measurements as assignment results.
