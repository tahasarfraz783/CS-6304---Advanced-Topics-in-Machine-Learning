# Task 4 — Open-Set Recognition (notebook repository)

This is a separate implementation of **all required Task 4 steps** from the supplied PA text. Every executable source module is an `.ipynb`; there are no `.py` files here. Optional Step 5 (RPL) is not included. The original `Task 4/`, other tasks, and dataset files are unchanged.

**Implementation status:** authored and statically inspected only. No notebook cells, training, extraction, evaluation, installations or runtime tests were executed by Codex. All new notebook outputs are empty. Results cannot be assessed until you run the workflow. The existing completed Vanilla artifacts were copied byte-for-byte and recorded in `results/preserved_vanilla.json`.

## Exact execution order

Use your existing working PyTorch/Jupyter environment (the same kernel as your completed Vanilla notebook). Required packages: torch, torchvision, numpy, pandas, scipy, scikit-learn, matplotlib, IPython, and Jupyter/ipykernel. No package installation is performed by these notebooks. The `.yaml` configs use JSON syntax, a valid subset of YAML, so PyYAML is not required; retain that syntax when editing them.

Open this `task4` directory in Jupyter. **Restart the kernel before each numbered row**, edit the first parameter cell where applicable, save the notebook, and choose **Run All**. You do not need to execute helper notebooks individually.

| Order | Notebook | Parameter | What it does |
|---|---|---|---|
| 1 | `train.ipynb` | `RUN='vanilla'`, `REUSE_PRESERVED_VANILLA=True` | Checks and reuses your copied completed Vanilla model. It does **not** repeat its 100 epochs. |
| 2 | `train.ipynb` | `RUN='gcsc'` | Trains GCSC for 100 epochs and selects best known-validation checkpoint. |
| 3 | `train.ipynb` | `RUN='proser'` | Loads the selected Vanilla checkpoint, adds five dummy classifiers, fine-tunes all parameters for 50 epochs. |
| 4 | `extract_outputs.ipynb` | `PHASE='known'` | Freezes all three selected models and saves unaugmented CIFAR-10 training/validation/test features and logits. This re-extracts outputs; it does not retrain Vanilla. |
| 5 | `extract_outputs.ipynb` | `PHASE='calibrate'` | Fits Mahalanobis statistics on training features and calibrates all scores on known validation only. Locks checkpoints, definitions, caches and thresholds. |
| 6 | `extract_outputs.ipynb` | `PHASE='unknown'`, `CONFIRM_ALL_DECISIONS_FIXED=True` | Checks the lock, then extracts the fixed 800 near and 800 far CIFAR-100 **test** examples. |
| 7 | `evaluate_osr.ipynb` | No parameters | Produces both required tables, ROC panel, failures, per-class analysis, score comparisons, training curves and report scaffold. |
| 8 | Read generated evidence | `results/evaluation/report.md` and `failure_interpretation.md` | Complete the concise discussion and visual judgments using your actual results. |

These are notebook actions, not shell training commands. There are only **three entry notebooks**. `train` loads data/model/method definitions; `extract_outputs` loads score/calibration definitions; `evaluate_osr` loads extraction definitions without dispatching extraction and then loads metric/analysis definitions. Helper notebooks define functions, so running them alone does not perform a complete experiment.

`DATA_ROOT` defaults to the existing PA1 `data/` folder, shared with your old task. `DOWNLOAD=True` allows torchvision to download a missing dataset **when you run the notebooks**; set it to False in the bootstrap code before calibration if your data is already available and you want missing files to raise an error. Use the same data location in both entry bootstraps. The code uses zero DataLoader worker subprocesses for straightforward Windows notebook operation.

## What is preserved and what is new

`results/vanilla/` contains copies of the completed `best.pt`, history, config, split, completion record, known evaluation summary and training figure. The original files remain in the original Task 4 folder. The copied split must match the seed-6304 split generated from official labels. On your first run, the notebook checks the checkpoint metadata, tensor keys, split and saved SHA-256 before reuse. It does not claim to have verified model inference in advance.

Old cached features/logits remain in the original folder. Step 4 generates caches with the new metadata format for all models. This avoids mixing caches from different checkpoints or data ordering. Nothing here deletes or regenerates Task 1 cue-conflict data.

## File map

```text
task4/
  configs/
    vanilla.yaml  gcsc.yaml  proser.yaml
  methods/
    vanilla.ipynb  gcsc.ipynb  proser.ipynb  manifold_mixup.ipynb
  data/
    cifar10.ipynb  cifar100_unknowns.ipynb  make_splits.ipynb  split.json
  models/
    resnet_cifar.ipynb
  scores/
    msp.ipynb  mls.ipynb  energy.ipynb  mahalanobis.ipynb
  cache/                         # generated raw features/logits + labels/provenance
  evaluation/
    metrics.ipynb  thresholds.ipynb  failure_analysis.ipynb
  train.ipynb
  extract_outputs.ipynb
  evaluate_osr.ipynb
  results/                       # checkpoints, calibration, tables, figures, reports
  README.md
```

- **configs** records the prescribed optimizer/training settings and method-specific parameters. Fixed PA constants such as the mixup point, coefficients and score temperature are also explicit in the corresponding helpers; changing a config alone is not a supported way to change the prescribed method.
- **data/make_splits** deterministically permutes each CIFAR-10 class using NumPy seed 6304: first 500 examples go to validation and remaining 4,500 to training. An incompatible saved split raises an error.
- **data/cifar10** builds optimization transforms and unaugmented extraction transforms. Vanilla/PROSER use crop and flip. GCSC additionally inserts RandAugment(2,9) before tensor conversion/normalization.
- **data/cifar100_unknowns** constructs only `train=False` CIFAR-100, requires a valid experiment lock and selects the exact listed near/far classes.
- **models/resnet_cifar** defines ResNet-18 with a 3x3 stride-1 stem, no max pool, ten known outputs and 512-dimensional penultimate features. PROSER adds a separate five-output linear dummy head. Its layer2 split permits manifold mixup.
- **methods/vanilla** computes ten-class cross-entropy. **gcsc** uses the same objective. **proser** defines placeholder training, known-only bias fitting and reference detection. **manifold_mixup** constructs mixed intermediate features from different classes.
- **scores** contains the four independent unknownness functions. All Vanilla scores use identical stored examples and model outputs.
- **evaluation/thresholds** implements the validation percentile and verifies experiment integrity. **metrics** implements unknown-positive AUROC and the PA's acceptance/rejection convention. **failure_analysis** exports accepted unknowns and selects examples for visual discussion.
- **train** optimizes/selects models. **extract_outputs** caches outputs and fixes calibration before unknown access. **evaluate_osr** computes the final evidence from fixed caches; it neither trains nor recalibrates.

## Exact protocol choices

Known data: CIFAR-10, 45,000 training, 5,000 validation, all 10,000 test. Normalization matches your preserved Vanilla: mean [0.4914,0.4822,0.4465], standard deviation [0.2470,0.2435,0.2616]. GCSC uses the same random initialization procedure, seed, SGD and cosine schedule as Vanilla. Changes in augmented batches naturally produce different later optimization trajectories.

Unknown groups are fixed:

- Near: bus, pickup_truck, motorcycle, tractor, wolf, fox, leopard, camel.
- Far: bottle, bowl, chair, clock, keyboard, mushroom, sunflower, wardrobe.

No CIFAR-100 training dataset is ever constructed. Unknown test data is loaded only after all model selection and score calibration have finished. CIFAR-10 test labels never select checkpoints or thresholds.

**Freezing** here means loading the selected checkpoint, calling evaluation mode (including fixed BatchNorm statistics), disabling parameter gradients, and performing inference without optimization. It does not alter the saved checkpoint and needs no extra manual action.

For PROSER let `d=max(dummy_logits)` and `a=[z_1,...,z_10,d]`. The first half of a minibatch contributes `CE(a,y) + 1*CE(a with true-class logit masked to -infinity, unknown)`. The second half is shuffled, same-class pairs excluded, and features mixed between layer2 and layer3 using one Beta(2,2) draw per batch. Its contribution is `0.1*CE(a_mixed, unknown)`. Both feature branches retain gradients. If no valid pair occurs, that batch's data term is zero; pair counts are logged. The 72-example final batch splits evenly. Known validation accuracy uses only ten known logits. This follows equations 4–7 and the multiple-dummy max rule in [Zhou et al.](https://arxiv.org/html/2103.15086v1).

The placeholder score follows the `CONF_DeltaP` branch of the [authors' reference implementation](https://github.com/LAMDA-CL/CVPR21-Proser/blob/main/proser_unknown_detection.py): append the strongest dummy, apply softmax at fixed T=1024, and use `P(dummy)-max P(known)`. Following the paper's known-only calibration, add bias equal to the 5th percentile of `max(known)-max(dummy)` on validation, then apply the PA's 95th-percentile score threshold. Temperature, score orientation, beta and gamma are never selected on unknowns. We do not reproduce reference-code unknown-based model selection or choosing the better of opposite AUROC directions. Training follows the paper plus PA constants rather than copying the reference script's different experimental recipe.

Every score increases with unknownness:

| Score | Formula | What it measures |
|---|---|---|
| MSP | `1-max softmax(z)` | Relative confidence |
| MLS | `-max(z)` | Absolute strongest known logit |
| Energy | `-logsumexp(z)` | Aggregate evidence, T=1 |
| Mahalanobis | minimum class distance using shared diagonal covariance | Distance from known feature clusters |

Mahalanobis uses only unaugmented training features: class means plus pooled within-class squared residuals divided by N, with 1e-6 added to every variance. It uses float64 for statistics and scoring. It never estimates covariance from validation, test or unknowns.

For each score, `tau=quantile(u_validation,0.95,method='linear')`. Accept when `u<=tau`, reject when `u>tau`. Ties can make actual validation acceptance exceed 95%. Report actual known-test acceptance separately. `fpr95val` is the fraction of unknowns accepted at this fixed threshold, not a threshold interpolated from a test ROC. AUROC uses unknown=1 and is never sign-flipped to inflate the result. CSA is measured before rejection, always from the ten known logits.

## Required output evidence

After you run evaluation, `results/evaluation/` contains:

- `table1_vanilla_scores.csv`: MSP, MLS, Energy, Mahalanobis on the same Vanilla caches; near/far/all AUROC, rejection, FPR, validation and test acceptance.
- `table2_model_comparison.csv`: Vanilla/GCSC/PROSER MLS and an additional PROSER placeholder row; CSA and the same OSR metrics.
- `vanilla_roc.png`: compact MSP/MLS/Mahalanobis panel. The plot treats unknown as positive, so its x-axis is known false rejection, y-axis unknown detection.
- `failure_examples.png` and `.csv`: three accepted near and three accepted far examples, prioritizing class diversity then confident errors. If fewer than three exist, the notebook reports the actual count; it never loosens a threshold to create failures.
- `vanilla_mls_all_accepted_unknowns.csv`: full accepted-unknown inventory.
- `per_unknown_class.csv` and `unknown_label_absorption.csv`: class difficulty and destinations of accepted unknowns.
- `score_rank_correlations_*.csv`, `score_decision_disagreements_*.csv`, and `score_disagreement_examples_*.csv`: evidence for comparing the four signals.
- `per_example_scores.csv`, `changes_vs_vanilla_mls.csv`, `training_curves.png`, and provenance manifests.
- `report.md` and `failure_interpretation.md`: measured comparisons and prompts for your own result-dependent discussion. These prose files are not overwritten on reruns. Fill them in; a scaffold is not a finished research report.

All CSV metrics are fractions, not percentages, except raw score thresholds and explicit percentage-point text. PROSER training accuracy measures the ordinary first half; its validation/test CSA always measures all known examples with only known logits.

## Reruns and edits

Completed training runs are reused after validation. Incomplete training raises an error instead of silently overwriting checkpoints; this implementation does not automatically resume optimizer state. Preserve an interrupted method directory under a different name/location before deliberately restarting that method from epoch 1. Do not move the completed Vanilla directory needed by PROSER.

Matching caches are reused; incompatible caches raise errors. Calibration locks source code (ignoring outputs, cell counts and tagged parameter cells), configs, all checkpoints and known caches. Jupyter `.ipynb_checkpoints` backups are excluded. Changing `PHASE` and the confirmation parameter between steps is expected. Save any legitimate implementation edits **before** extraction/calibration. After unknown evaluation, use a new separate experiment for changes rather than deleting the lock and tuning against these unknown results.

Disk usage includes the copied Vanilla model, two new checkpoints and raw caches for all models. No training-time estimates or numerical outcomes are promised because this implementation has not been run.
