# Recovery runs — Recommended Structure only

Use **Python (pa1_env)**. Restart the kernel before each notebook, then **Run All**.
Run the notebooks sequentially; each training notebook saves results automatically.

1. `Task 2/task2/train_recovery_v1.ipynb`
   trains DANN, CDAN, then DAN lambda=10.
2. `Task 3/task3/train_recovery_v1.ipynb`
   trains DAN-DG lambda=1, then DAN-DG lambda=10.
3. `Task 3/task3/review_recovery_v1.ipynb`
   reviews source predictions, locks all five completed checkpoints, recomputes
   source accuracy, evaluates Sketch, and displays a separate old/new accuracy
   table for each task. Both the old references and the new runs are from the
   Recommended Structure folders.

No run-selection edits are needed. The new entry points load the setup and
training definitions from each Recommended Structure `train.ipynb`, skipping its
original run cell. The common recovery helper is under Recommended Structure
Task 2's `shared/recovery_support.py`. No legacy root-level training modules or
legacy checkpoints are loaded.

## Revised settings

| Setting | DANN / CDAN | DAN lambda=10 | DAN-DG lambda=1 | DAN-DG lambda=10 |
|---|---:|---:|---:|---:|
| Backbone learning rate | 1e-5 | 1e-6 | 1e-5 | 1e-6 |
| Classifier learning rate | 1e-5 | 1e-5 | 1e-5 | 1e-5 |
| Discriminator learning rate | 1e-5 | N/A | N/A | N/A |
| Maximum GRL strength | 0.1 | N/A | N/A | N/A |
| Final MMD weight | N/A | 10 | 1 | 10 |

Initialization uses `Task 2/task2/results/source_only/best.pt`.
All five freeze BatchNorm running statistics and affine parameters, clip gradient
norm at 1, and ramp alignment over five epochs. The standard GRL schedule remains,
with the smaller maximum and extra ramp. Domain loss weight remains 1; CDAN's
feature/probability paths remain attached. MMD kernels and data split are unchanged.

Training has at most 20 epochs and patience 8. Mean source validation macro-F1
selects checkpoints starting at epoch 5, after alignment reaches its full MMD
weight. Base changes are in each task's `configs/recovery_v1.yaml`; the lambda=10
backbone-rate overrides are in `shared/recovery_support.py` under Recommended
Structure Task 2. Original `train.ipynb` defaults remain unchanged.

This is a recovery experiment after inspection of the original target results,
not a fresh blind evaluation or a lambda-only comparison. These settings aim to
stabilize training but do not guarantee better accuracy.

## Saved files

New training artifacts are under each Recommended Structure task's
`task2/results/recovery_v1/` or `task3/results/recovery_v1/`, in named run folders.
Each contains `best.pt`, `config.json` (including initialization hash),
`completion.json`, `history.csv`, `source_validation.csv`,
`source_validation_predictions.csv`, and `training_curves.png`.

The final review saves `source_review.csv` and, under each recovery folder's
`final_evaluation/`, `comparison.csv`, `target_predictions.csv`, `per_class.csv`,
`evaluation_lock.json`, and `verification.json`. CSV accuracy values are fractions;
the notebook displays percentages, and `change_pp` is percentage points.

Inspect predicted-class counts and dominant prediction share for collapse. One
predicted class is complete collapse. Review classification losses and source
macro-F1 alongside accuracy. Completed training cells reload matching saved runs.
Interrupted folders and changed recipes require a fresh recovery version; they
are not overwritten or resumed automatically. Existing results stay available.

The workflow was checked with synthetic data using the Recommended Structure
training definitions. Full PACS training is left for the notebook run order above.
