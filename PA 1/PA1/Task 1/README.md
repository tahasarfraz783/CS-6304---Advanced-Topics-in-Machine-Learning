# Task 1 — recommended notebook structure, preserving completed work

No experiment/notebook cells, training, evaluation, stylization, or tests were
executed during restructuring. Existing artifacts were copied as files and their
SHA-256 hashes compared. All original Task 1 files remain untouched.

## STEP 3 IS ALREADY COMPLETE: DO NOT GENERATE OR REVIEW AGAIN
The preserved set has 200 conflicts: 20 per direction across five class pairs.
The review log records 200 accepted and 375 rejected candidates.
data/preserved_cue_conflicts contains byte-identical copies of:
- cue_conflict_evaluation.pt: actual 224x224 image tensors, labels, source IDs,
  frozen features and classifier logits (not just a CSV).
- unfinished_review.pt: the saved manual review state; its historical filename
  does not mean you must repeat the review.
- cue_conflict_manifest.csv: accepted image pairing/labels.
- cue_conflict_review_log.csv: historical accepted/rejected decisions.

configs/preservation.json records source paths, sizes and hashes.
data/make_cue_conflicts.ipynb is deliberately a LOAD/VERIFY helper despite the
recommended filename. It contains no stylizer, generator, or acceptance UI.
Missing/changed preserved files cause an error, never automatic regeneration.
Do not run the original cue_conflicts.ipynb to initialize this new version.

## Existing work retained
The complete old results directory was copied, including the trained clean heads,
500-image test manifest, cue evaluation, translation/patch features and t-SNE
caches. Copied results are inherited results, not newly executed experiments.
The official STL-10 files are stored locally in data/stl10_binary.
Their copies were SHA-256 verified; configs/local_dataset.json records the hashes.
The original Task 1 folder is no longer required.
The new workflow only writes inside its own results.
Existing matching translation, patch and representation caches are reused.
Color evaluation may extract frozen features; it does not regenerate conflicts.

## Exact execution order
Use the existing pa1_env kernel. Start Jupyter inside Task 1.
Open scripts/run_task1.ipynb. Select STEP in the final cell and run all cells.
Restart the kernel before each subsequent STEP.

1. STEP = 'clean'
   Loads the preserved baseline, exact split/test IDs and trained classifier heads.
   Displays saved clean results. No head retraining.
2. STEP = 'color'
   Evaluates grayscale and fixed hue rotation 0.25; saves color tables.
3. STEP = 'cue_conflicts'
   LOADS the 200 preserved conflicts and their matching cached predictions,
   recomputes shape/texture tables, and displays examples. NO GENERATION/REVIEW.
4. STEP = 'translation'
   Reuses matching existing features/results for 0, 8, 16, 32 pixels.
5. STEP = 'patch_shuffle'
   Recreates deterministic patch permutations and reuses matching saved evaluation.
6. STEP = 'representation'
   Pairs preserved conflicts with their clean content IDs; uses saved translation,
   patch, grayscale features and joint t-SNE caches where available.

All helper notebooks are loaded automatically. Do not run them separately.
The protected cue archive is verified at each entry-point run.
Keep the baseline unchanged to reuse cached predictions. The entry point does
not offer automatic retraining or regeneration that would invalidate caches.

## File roles
configs/protocol.json: documented fixed choices; not a universal runtime config.
configs/preservation.json: provenance and SHA-256 fingerprints for copied files.
data/make_subset.ipynb: loads exact saved split, subset, class mapping and heads.
data/make_cue_conflicts.ipynb: protected archive loader only.
data/transforms.ipynb: color generation, reflection translation, patch permutation.
models/backbones.ipynb: frozen wrappers and original linear-head training function.
analysis/evaluate_bias.ipynb: prediction metrics and five experiment actions.
analysis/feature_similarity.ipynb: cosine/prediction stability calculations.
analysis/representation.ipynb: paired-feature analysis, joint t-SNE and plots.
scripts/run_task1.ipynb: sole entry point and STEP selection.
results/: preserved artifacts and any future derived outputs.

## Protocol and provenance
The cue dataset was produced using the original optimization-based VGG-19 style
transfer, not AdaIN; its implementation referenced the official PyTorch neural
style tutorial: https://docs.pytorch.org/tutorials/advanced/neural_style_tutorial.html
The source notebook documents content/style layers and the visual rejection rule.
The historical generator/review notebook is not required for this preserved workflow.
The five pairs are cat/dog, deer/horse, bird/monkey, car/truck, airplane/ship,
with both directions. Existing choices, manual decisions and labels are retained.
Models: ImageNet ResNet-50 V2, ViT-B/16 V1, OpenCLIP ViT-B-32/openai.
The official dataset was copied byte-for-byte into this recommended folder.

## Modification limits
This is a preservation-first reorganization, not a fresh experiment.
A retrained head requires recomputing compatible logits and cache metadata, but
does not require regenerating cue images. Do not mix old predictions with new heads.
The original head-training function is retained for code study; default actions
reuse the completed baseline. Intentional fresh training requires a separate
output/cache plan and is not triggered by Run All.
Protocol JSON documents settings; relevant implementation constants are in the
entry point and transform/analysis helpers. Keep cache fingerprints consistent
with intentional changes. No runtime validation was performed during creation.


## Report support notebook

Open `report_support.ipynb` with the `Python (pa1_env)` kernel. It includes executed
outputs, explanations of all six steps, separate model tables, saved training
curves, same-image intervention panels, cue-conflict cases, representation plots,
and worksheets covering Task 1 research questions and Task 5 synthesis.
Run All reads existing results and writes only to `report_assets/`; it does not
train models or regenerate cue conflicts. Exported PNG/SVG figures and CSV tables
are listed in `report_assets/asset_index.csv`. The notebook is a study/evidence aid;
write your report interpretation and wording yourself, as required by the manual.
