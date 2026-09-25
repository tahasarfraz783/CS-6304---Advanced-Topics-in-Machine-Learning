# Task 3 — recommended notebook structure

Written only: no notebook cells, training, evaluation, imports of project code,
tests, or dependency installation were executed during creation.

This folder follows the provided task3 layout, substituting .ipynb for every .py.
Original Task 3 and both Task 2 versions are untouched. Results start empty.
The selected controlled study remains DAN-DG lambda = 0.1, 1, 10.

## Shared dependencies
Keep this folder beside "Task 2" inside PA1.
Task 3 directly reuses that folder's shared PACS notebooks, saved split, MMD,
model definitions, source metrics, and task2/results/source_only/best.pt.
It does not copy a second protocol or silently fall back to the old baseline.
The models notebooks are small adapters that load those shared definitions.
PACS images remain in PA1/data/PACS.
For moving the repository, preserve this sibling layout and the existing data path.
Use the existing pa1_env Jupyter kernel and installed scientific dependencies.

## Exact run order
Start Jupyter inside Task 3.
Open task3/train.ipynb. Before running, review HYPOTHESIS in its study-plan cell.
The hypothesis is recorded once and protected against silent changes.
Set RUN in the final cell, then run all cells for each action below.
Restart the kernel between actions.

1. RUN = 'erm'
   Loads the new Task 2 source-only checkpoint unchanged and evaluates sources.
   Does not retrain ERM. First finish Task 2's source_only run if missing.
2. RUN = 'dan_dg'
   Trains main DAN-DG with lambda=1 from ImageNet initialization.
3. RUN = 'sam'
   Trains standard non-adaptive SAM with rho=0.05 from ImageNet initialization.
4. RUN = 'dan_dg_lambda_0p1'
   Trains the lambda=0.1 controlled-study setting.
5. RUN = 'dan_dg_lambda_10'
   Trains the lambda=10 controlled-study setting. Main run supplies lambda=1.
6. RUN = 'diagnostics'
   Requires all five completed checkpoints, including the reused ERM.
   Locks checkpoints and computes source metrics, three-way source separability,
   and the shared sharpness proxy. No Sketch images are accessed.
7. Freeze all Task 3 settings and checkpoint choices.
8. Open task3/evaluate_sketch.ipynb in a fresh kernel.
   Set ALL_DECISIONS_LOCKED = True in its final cell and run all cells.
   Only this entry point opens Sketch and performs final target/failure analysis.

Do not run helper notebooks separately. They are loaded automatically.
Definitions share the entry notebook namespace; restart after helper edits.
The shared PACS notebook defines an unlabeled target dataset for Task 2, but
Task 3 training/diagnostics never instantiate it or access its images.
Existing training checkpoints are protected; there is no automatic resume.

## Task 2 comparison
Final evaluation looks only in the new Task 2 results/final_evaluation folder.
If absent, Task 3 final tables/plots still complete and report comparison pending.
After the new Task 2 final evaluation is available, rerun evaluate_sketch.ipynb
with unchanged Task 3 checkpoints to add cross-task DAN/DAN-DG comparisons.
It checks target paths, split identity, and exact shared ERM checkpoint identity.
Do not use Task 2 target results to revise Task 3 settings.

## Files
configs/erm.yaml: full common protocol, also checked against the ERM checkpoint.
configs/dan_dg.yaml and sam.yaml: full method configurations, using JSON syntax
(valid YAML) for dependency-free loading. The loader requires JSON syntax.
models/backbone.ipynb, classifier_head.ipynb: reuse Task 2 model definitions.
methods/erm.ipynb: existing-checkpoint validation and source-only ERM evaluation.
methods/dan_dg.ipynb: average shared MMD over the three source pairs and objective.
methods/sam.ipynb: two-pass SAM step with exact weight restoration.
selection/source_validation.ipynb: source validation and fixed-protocol checks.
evaluation/domain_metrics.ipynb: locks, inventories, mean/worst metrics, diagnostics.
evaluation/source_domain_separability.ipynb: balanced three-class linear probe.
evaluation/sharpness.ipynb: fixed 96-image source batch, radius-0.05 CE perturbation.
train.ipynb: common source-only loop, study plan, action selection and training plots.
evaluate_sketch.ipynb: gated target evaluation, per-class analysis and final plots.
results/: all new run artifacts; existing Task 3 results are not imported.

## Outputs and limits
Training: best.pt, config.json, history.csv, completion.json, source predictions,
per-source metrics, mean/worst summary and training_curves.png.
ERM: source metrics, summary and provenance referencing Task 2's original weights.
Diagnostics/final: checkpoint lock, source/target inventories, probe split,
sharpness batch, source diagnostics, aggregate and class tables, controlled-study
table, confusion counts, selected examples and plots.
The three-way probe chance score is 33.3%; SAM training loss differences are
distinct from the common validation sharpness diagnostic.
Some protocol descriptors (weights, transforms, fixed architecture) describe
shared code constants. Changing their YAML strings does not implement a new
protocol. Fixed main settings are checked; intentional protocol changes require
updating shared definitions and checks consistently.
No previous execution outputs or conclusions are embedded in these notebooks.
Runtime behavior of this reorganization has not been tested.

## Revised recovery runs

After Task 2 Recommended Structure recovery training, run **train_recovery_v1.ipynb**, then **review_recovery_v1.ipynb**, using pa1_env and restarting the kernel before each Run All. The training notebook runs DAN-DG lambda=1 and lambda=10. The review evaluates all five revised models and saves separate task tables under results/recovery_v1/final_evaluation. All checkpoints and comparison references use Recommended Structure folders.

