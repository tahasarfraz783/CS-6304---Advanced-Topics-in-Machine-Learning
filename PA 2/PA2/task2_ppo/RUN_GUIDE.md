# Task 2 PPO run guide

Run these commands from the inner `PA2` directory. The objective defect is fixed:
PPO uses the minimum of the clipped and unclipped surrogates.

## 1. Activate and validate

```powershell
. .\activate.ps1
python -m unittest task2_ppo.test_ppo task2_ppo.test_runtime
python -m scripts.check_environment
python -m scripts.validate_assets
```

## 2. One-update GPU smoke test

```powershell
python -m task2_ppo.continue_train --updates 1 --run-name smoke --output outputs/task2_ppo/smoke
python -m task2_ppo.evaluate --adapter outputs/task2_ppo/smoke --name smoke --max-examples 2
```

The smoke run is separate from the required experiments. Confirm finite losses,
reasonable gradient norms, and no repeated skipped optimizer steps. CPU tiny-model
tests validate the loop but cannot establish that full models fit in 6 GB VRAM.
The local PPO configuration uses a frozen NF4 (4-bit) reward model to leave
GPU space for policy/critic training. This differs from the release's INT8 reward
scoring numerically; record that local execution adaptation and use it consistently
across every PPO branch and evaluation. CPU placement is also supported via
`reward_device: cpu`, but requires more system RAM/paging capacity.
If the real smoke test runs out of GPU memory, preserve the release settings and
use a larger GPU rather than silently reducing the experiment budgets.

## 3. Frozen midpoint and standard continuation

```powershell
python -m task2_ppo.evaluate --adapter checkpoints/ppo_midpoint_policy --name midpoint
python -m task2_ppo.continue_train --run-name standard
python -m task2_ppo.evaluate --adapter outputs/task2_ppo/standard --name standard
```

The baseline uses 20 updates, 1 prompt per update, and 2 PPO epochs. The policy
starts with the supplied LoRA; the critic starts with the released merged state
plus a fresh zero-initialized LoRA adapter, as specified by the starter. Optimizers
start fresh because the continuation bundle does not supply optimizer states.
The reference is the frozen base policy (policy LoRA disabled).

## 4. Clipping and KL studies

```powershell
python -m task2_ppo.analyze_clipping --cached-only
python -m task2_ppo.analyze_clipping --forks-only
python -m task2_ppo.ablate_kl
python -m task2_ppo.export_results
```

Each fork starts from the original policy AND critic midpoint, with 8 updates,
the same prompt schedule, the same per-update sampling seeds, and a 512-token cap.
Frozen evaluation uses a 768-token cap on all 200 released held-out prompts.
Do not evaluate final results with `--max-examples`.

Completed forks can be reused by orchestration; interrupted/incomplete training
outputs are deliberately not overwritten. Use a fresh run name/output for manual
retry runs. Partial evaluation output is also protected against accidental reuse.

## Evidence and interpretation

- `results/task2_ppo/*_train.jsonl`: update trajectories and per-epoch losses,
  pre-clipping gradient norms, skipped steps, critic explained variance, and lengths.
- `*_summary.json`: effective configuration, completed updates, actual tokens,
  runtime including setup, training runtime, peak allocated/reserved VRAM, and
  the maximum pre-clipping policy gradient norm (the stability statistic).
- `*_eval.jsonl` and `*_evaluation.json`: responses and held-out aggregates.
- `cached_clipping.json`: token-weighted cached surrogate, outside-bound fraction,
  and the fraction for which clipping actually changes the surrogate. Those two
  fractions differ because clipping is advantage-sign dependent.
- `clip_comparison.json`, `kl_comparison.json`, and `*_budgets.json`: fork comparisons.
- Exported diagnostic PNGs, `held_out_comparison.csv`, and `qualitative_review.md`.

Entropy is the supplied sampled negative raw token log-probability estimator,
not the exact categorical entropy. KL is the sampled raw token log-probability
difference from the reference and can be negative on finite samples. Generation
uses the released temperature/top-p settings; objective probabilities are raw
model probabilities, consistently across old/new/reference scoring.

Configured token ceilings and update budgets match across forks. Actual token
counts may differ because of EOS and are explicitly recorded in budget files.
Do not claim exact actual-token matching if these counts differ; if your instructor
requires exact consumed-token equality, clarify the stopping/termination protocol
before using the runs for that comparison.

Cached prompts are resolved by stable `prompt_id`, including the evaluation pool;
the cache's original `source_index` is not a released-pool row number. Retokenized
response lengths must match cached log-probability lengths, otherwise analysis
stops rather than silently pairing the wrong tokens. Cached current-policy ratios
may remain close to 1 when the cache matches the midpoint; report the observed
result without inventing a policy perturbation.

Review qualitative examples yourself: the export supplies paired responses and
reward changes, not fabricated human judgments. Include a concordant case and a
disagreement case, and use the Task 4 safety evidence when drawing conclusions
about overoptimization.
