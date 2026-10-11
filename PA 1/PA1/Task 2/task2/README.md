# Task 2 — separate notebook repository

This folder follows the supplied layout with .ipynb in place of every .py.
Original Task 2 files and results are untouched. No old checkpoints or outputs
are copied. The existing immutable split is copied byte-for-byte.

## Preparation
Start Jupyter inside this repository with the existing pa1_env kernel.
Dependencies: torch, torchvision, numpy, pandas, scikit-learn, Pillow, tqdm,
IPython/Jupyter, matplotlib. Nothing is installed by this reorganization.
DATA_ROOT in each entry notebook defaults to the existing ../data/PACS folder
relative to the repository root. Edit it if needed.
Torchvision may download ImageNet weights when you later execute training.

## Execution order
Helper notebooks contain definitions and are loaded automatically by the entry
notebooks. You do not need to open or run helpers separately.

1. Open train.ipynb, set RUN = 'source_only' in its last cell, then run all cells.
2. Restart kernel, set RUN = 'dan', then run all cells.
3. Restart kernel, set RUN = 'dann', then run all cells.
4. Restart kernel, set RUN = 'cdan', then run all cells.
5. Restart kernel, set RUN = 'dan_lambda_0p1', then run all cells.
6. Restart kernel, set RUN = 'dan_lambda_10', then run all cells.
7. Review source-validation results and freeze all settings/checkpoints,
   including Task 3 settings, before looking at target recognition results.
8. Open evaluate_final.ipynb with a fresh kernel, set ALL_DECISIONS_LOCKED = True
   in the last cell after step 7, then run all cells.

Record the alignment-study hypothesis before training. The fixed DAN weights
are 0.1, 1, 10; the main DAN run supplies weight 1. Select settings using source
validation only. Never tune using final target results.
Every run starts from ImageNet initialization, not a previous trained model.
Existing best.pt files are protected against overwrite.

## Structure and responsibilities
- shared/pacs_protocol.ipynb (one directory above task2): common split/protocol.
- shared/pacs.ipynb: datasets, transforms, unlabeled target loading.
- shared/splits/pacs_sketch_seed6304.json: existing shared source split.
- configs/: base and method overrides copied from completed run metadata.
  Files use JSON syntax, a valid YAML subset.
- models/: ResNet-18 backbone, classifier head, domain discriminator.
- methods/: source-only, DAN, DANN, CDAN objectives outside the common loop.
- evaluation/: source metrics, held-out domain probe, class/confusion analysis.
- train.ipynb: shared training, source validation, checkpointing, CSV histories.
- evaluate_final.ipynb: locked final evaluation and CSV comparisons.
- results/: empty until you execute the notebooks.

The protocol retains seed 6304, eight examples per source per update,
24 unlabeled target examples for adaptation, frozen BatchNorm running statistics,
source macro-F1 checkpoint selection, and the original budget.
Future Task 3 code should reuse these shared notebooks and split; the existing
completed Task 3 has not been changed.

## Status
Written only. No notebook cells, training, evaluation, tests, project imports,
or installation were executed. Runtime behavior is unverified.
This reorganization does not claim to fix the numerical issues recorded in the
original DANN run. Existing plotting outputs are not copied.
## Revised recovery runs

For DANN, CDAN, and DAN lambda=10 recovery, run **train_recovery_v1.ipynb** with pa1_env (restart kernel, Run All). Then run Task 3's recovery training and review notebooks. See [recovery run order](../RECOVERY_RUN_ORDER.md). All checkpoints/results use Recommended Structure folders.



## Report support notebook

Open `report_support.ipynb` with the `Python (pa1_env)` kernel. Executed outputs
cover all six steps, PACS domain examples and same-image augmentation panels,
separate method tables, training/validation and alignment curves, class-level
transfer, confusions, failure cases, the original controlled MMD-weight study,
and the Task 2 research questions and Task 5 synthesis prompts.

Original and recovery experiments are explicitly separated. Recovery domain-probe
scores were not saved and are marked unavailable; target macro-F1 is computed
from saved predictions. Run All does not train or modify experimental outputs.
It writes PNG/SVG figures and CSV tables only to `report_assets/`.
See `report_assets/asset_index.csv` and `source_manifest.csv` for export and source
provenance. Report interpretation and wording must remain your own, as required
by the assignment manual.
