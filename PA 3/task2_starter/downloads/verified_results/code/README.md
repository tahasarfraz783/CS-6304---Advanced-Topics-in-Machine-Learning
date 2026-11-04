# PA3 Task 2 — one launcher, one curriculum

This directory implements the supplied Task 2 specification. The official experiment is
one continuous 196-token SigLIP–Qwen run, not three independently initialized models.
**No assignment-scale run or A100 performance result has been produced locally.**
The launcher performs a disposable real-GPU preflight before official training.

## On the A100 instance

Upload `task2_starter_upload.zip`, extract it, and enter `task2_starter/`.
Use Python 3.11 or 3.12. Reusing the working Task 1 environment avoids reinstalling
PyTorch and the same pinned transformers/PEFT packages. First verify CUDA:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name())"
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python run.py --mode check
```

If CUDA-enabled PyTorch is absent, install the appropriate CUDA build from the
[official PyTorch selector](https://pytorch.org/get-started/locally/) first.
The instance's “Max CUDA 12.8” is a driver compatibility ceiling, not proof of the
installed PyTorch CUDA runtime. `check` prints the actual GPU and package versions.

Launch **all preparation, preflight, training, evaluation, plots, and packaging**:

```bash
nohup python -u run.py --mode run > task2.log 2>&1 &
python monitor.py
```

`nohup` returns immediately. `monitor.py` is a viewer; Ctrl+C stops the viewer only.
Follow detailed messages with `tail -f task2.log`. The first run downloads annotations
and selected images, so training does not begin immediately. Progress names each phase.
The launcher does not have credentials to connect to the supplied IP automatically;
these commands run in your instance terminal.

## Progress you can inspect throughout

Open `outputs/assignment/evidence/index.html` in Jupyter's HTML preview or serve the
output folder through your existing authenticated Jupyter proxy. The dashboard refreshes
every 30 seconds. When served over HTTP, the status card polls `progress.json` every
5 seconds. A local `file://` browser may block this fetch; the monitor still works.
Do not expose an unauthenticated output server directly to the public internet.

- Every optimizer attempt: loss, stage/global update, examples/s, peak allocated GiB.
- Every 15 seconds: heartbeat with activity age. Heartbeats do not imply useful progress.
- Every 10 seconds: `nvidia-smi` utilization, VRAM use, and power samples.
- Every 50 updates: inexpensive PNG loss, throughput, and memory refresh.
- Every development evaluation: complete PNG/SVG/PDF graphs and CSV tables.
- Every final generation batch: atomic saved answers; no end-of-suite-only cache.
- `python run.py --mode status` or `python monitor.py --once`: immediate status.

The displayed ETA belongs to the current phase. The preflight estimate covers training
only; preparation, development, generation, saves, and packaging are separate costs.

## How this uses the A100 efficiently

The assignment mandates training microbatch 8 × accumulation 2 and final generation
batch 8. Increasing these would change the required recipe. The implementation instead:

1. Caches deterministic FP16 SigLIP patch features in batches of 128 with eight persistent
   preprocessing workers. Only selected images are downloaded, using 16 download workers.
   SigLIP is unloaded before Qwen is loaded.
2. Keeps the few-GiB feature tensor resident on the GPU throughout Qwen training/evaluation.
   This avoids repeated image encoding, disk reads, and feature transfers per update.
3. Uses PyTorch SDPA, nonreentrant gradient checkpointing, FP16 frozen weights/autocast,
   FP32 trainable weights/states, dynamic scaling, and fused AdamW.
4. Projects Qwen hidden states to vocabulary logits only at supervised target positions.
   Visual and prompt logits are unused by the loss, so computing them wastes both memory
   and time. The tests compare losses AND connector gradients with a full projection.
5. Batches teacher-forced likelihood evaluation. Preflight tests 8/16/32/64 caption batches,
   then freezes the fastest measured seconds/example with allocated memory below 90%.
   Selection is written to `evaluation_runtime.json`; final decoding stays batch 8.
6. Runs 20 disposable updates per stage; excludes five warmups from training estimates.
   It tests actual LoRA/FP16/optimizer/generation paths. The official model and RNG are
   freshly recreated afterward. Test updates never enter the official 4,500-update budget.

VRAM occupancy is not a speed target. A small frozen backbone and cached features can
leave free memory even when useful compute is saturated. Inspect measured examples/s
and `gpu_samples.jsonl`; allocator-reserved memory is shown separately from allocated
memory. No claim of optimal A100 utilization is made before measurements. The preflight
is short and runs once per output; completed preparation/evaluations are reused.

## Exact scientific recipe

- Seed 6304; original `Qwen/Qwen3-0.6B`; non-thinking chat template for training/generation.
- Frozen `google/siglip-base-patch16-224`; 196 ordered patch features, final layer norm
  already applied by `last_hidden_state`, cached FP16. No second normalization.
- FP32 768→1024→1024 GELU connector. A fixed scalar matches initial connector RMS to
  training-caption text embedding RMS, using only the first 64 selected training captions.
  The rule, values, and example IDs are saved in `prepared/calibration.json`.
- Stage 1: 2,250 updates, exactly two shuffled passes over 18,000 caption examples.
- Stage 2: 1,500 updates, pair draws: presence .50 / counting .25 / caption replay .25.
- Stage 3: 750 updates, pair draws: natural .70 / presence .10 / counting .10 / captions .10.
- A draw contributes a complete QA pair or two captions; no forced mixture quotas.
- LoRA starts at Stage 2: r16, alpha32, dropout .05; q/k/v/o projections, no biases.
- Per-stage peak LRs, weight decay, clipping, warmup/cosine floor, caps, and schedules
  are recorded in `config.json`. Effective batch 16. No quantization or silent OOM retry.
- The response-token loss includes end of turn, with token average per example then
  example average. Prompts, visual tokens, and padding are masked.

## Data, isolation, and label review

`inputs/selected_manifest.json` is bundled after local validation against the official
COCO/VQAv2 files. It contains the exact required quotas, 9,404 selected images, all
references, training pools, annotation boxes, and original-source SHA256 checksums.
The default cloud run verifies its hash and reuses it, saving annotation downloads and
CPU selection time on the paid instance. It downloads only the selected JPEGs.

For a different data-selection config (including the tiny smoke setup), the launcher
downloads the official COCO 2014 annotations and VQAv2 questions, annotations, and
complementary pairs and regenerates the manifest. COCO uses its official S3 bucket via a valid-TLS
path endpoint because `https://images.cocodataset.org` failed hostname verification
during local endpoint checks. Certificate checking stays enabled.

`prepared/manifest.json` fixes every image/caption/question/pair ID, all ten natural
references, original consensus target strings, split choices, and mismatched-image
mappings before any model prediction. Natural references require ≥8/10 agreement after
normalization, different consensus answers, and the same question. The selected natural
pair counts are exactly 640/256/640 train, 12/8/12 dev, and 36/24/36 test.

Training grounding pools are restricted to images already selected for captions/natural
training, which reduces downloads without violating the unrestricted pool-size recipe.
Presence pools use any category annotation, including crowd; negatives have no category
annotation. Counting uses noncrowd instances, 1–4; category/image combinations with crowd
regions are excluded from counting. Broccoli is excluded from counting because boxes
can group florets into ambiguous units; this rule was fixed during annotation-only
inspection before training/predictions. It remains eligible for presence. No filtering
depends on predictions.

All development images are disjoint from all final-test images, across suites AND caption
development; train2014 is training only. Training images may recur between curriculum stages.
For simpler auditing, selected natural pairs also use distinct images within each partition.
Grounding evaluation is split evenly between presence and counting.

Inspect `evidence/qualitative.html` and the manifest's grounding references independently
of predictions before interpreting results: COCO absence is annotation absence and can
miss visible objects. The gallery's selection rule is fixed before training: first three
sorted pair IDs per suite/type, including successes and failures without cherry-picking.
The starter supplies evidence and CSVs; your report still needs your own label inspection
and interpretation of model behavior. The annotated review gallery is created during prepare.

## Evaluation and evidence

Development: before training, every 500 global updates, and endpoints 2250/3750/4500.
Caption reference loss includes termination; VQA reference NLL excludes termination.
Both VQA suites use correct, complementary-swap, and no-image inputs. No-image removes
visual tokens and rebuilds masks/positions while keeping the text unchanged.

Final: only the completed Stage 3 model, greedy, 16 new tokens, batch 8; correct, swap,
fixed unrelated mismatch, no-image. Original questions and original references remain
fixed under all conditions. Mismatch excludes BOTH images of the original pair and uses
another pair from the same suite. Final data never selects a checkpoint.

| Required evidence | Saved location |
|---|---|
| Loss, LRs, sampling counts, AMP skips, speed/memory per update | `training.jsonl`, `evidence/training.csv` |
| Dev caption loss, answer NLL, swap penalties | `evaluations/dev_*.json`, `evidence/development.csv`, figures |
| Four-condition/type-level final scores and complete-pair 95% intervals | `evaluations/final_summary.json`, `evidence/final_results.csv` |
| Original references, predictions, image IDs, per-example scores/NLL/time | `evaluations/final_examples.jsonl`, `evaluations/batches/` |
| Pair accuracy, identical/empty rates, partner-follow/unsupported outputs | Final tables and figures |
| Correct-minus-swap accuracy; swap-minus-correct NLL | `correct_advantage_over_swap` rows, with matched-pair intervals |
| Aligned complementary images, questions, references, all condition responses | `evidence/qualitative.html`, `qualitative.csv`, copied JPEGs |
| Stage parameters, training runtime, peak GPU memory | `resources.json`, `cost_summary.json`, `evidence/resources.csv` |
| Feature-cache cost/config/model commit | `prepared/features/complete.json` |
| GPU utilization, memory, power sampling | `gpu_samples.jsonl`, `evidence/gpu_samples.csv` |
| Package versions, model configs/commit, seeds, selected IDs | environment/provenance/config JSONs and manifest |
| Stage connector and LoRA exports | `exports/stage_1`, `stage_2`, `stage_3` |

Grounding accuracy is normalized exact match, separated into presence/counting. Natural
accuracy is the ten-reference leave-one-annotator-out soft consensus formula (not simply
`min(matches/3,1)`), separated into yes/no, number, other. Pair accuracy requires both
canonical answers exactly. Empty outputs remain in denominators. All final scores are
local subset results. Confidence intervals use 4,000 complete-pair bootstrap draws, with
identical sampled pair IDs for differences. Values in CSVs are fractions, not percentages.

`partner_follow_rate` means a prediction equals the partner's canonical answer; interpret
it particularly under swaps. `unsupported_rate` means it matches neither original nor
partner canonical answer, not a claim of independently verified visual impossibility.
Generation seconds/answer are synchronized batch generation wall time divided by batch
size, including embedding preparation/decoding but excluding separate reference-NLL work.

## Recovery, storage, and downloads

Rerun the same command to recover. Atomic checkpoints every 250 global updates and at
stage endpoints include trainable weights, scale, optimizer, scheduler position, scaler,
sampler state/position, stage progress, and Python/NumPy/CPU/CUDA RNG. All required saves
are retained. The frozen backbone is reloaded from the original pretrained checkpoint.
Orphan update logs after the last committed checkpoint are archived, not used as evidence.
Incomplete final JSONL tails are repaired; atomic batch files are the recovery authority.
Unsaved training work since the last checkpoint must run again. No automatic endless retries.

The `.run.lock` file prevents concurrent launchers. A hard kill can leave it behind.
Check its PID with `cat outputs/assignment/.run.lock` and inspect the process; only after
confirming it stopped, remove that one lock file and relaunch. Never delete outputs to resume.
Changing config requires a new output directory. Numeric CUDA kernels are not guaranteed
bitwise deterministic across different GPUs or library versions; resume restores all RNG state.

Budget at least 12 GiB free at startup; actual use depends on image sizes and dependencies.
The launcher checks free space. It avoids downloading the ~20GB full image archives.
It keeps images/features/checkpoints so interrupted work can resume. Use a new disposable
output for smoke testing; do not let large repeated test runs consume your small instance disk.

At successful completion, automatically created and verified:

```text
outputs/assignment/downloads/task2_results.zip
outputs/assignment/downloads/task2_models.zip
outputs/assignment/downloads/SHA256.json
```

Results include evidence, raw evaluations, manifest/config/provenance, and source code.
Models include stage connector/adapter exports and tokenizers, not duplicated frozen
Qwen/SigLIP weights. These adapters need the recorded original Qwen model plus the saved
connector/scale and cached or identically preprocessed SigLIP features. Recovery checkpoints
and full feature/image caches are excluded from download archives; download them separately
if you need exact recovery elsewhere. Packaging models uses ZIP_STORED.

Download and verify results before stopping/destroying the provider instance. The Python
process completing does not stop billing. The launcher does not destroy your instance.

## Other commands

```bash
python run.py --mode plan           # no ML imports/network required
python run.py --mode prepare        # download/select/cache, then exit
python run.py --mode preflight      # prepare + short GPU verification, then exit
python run.py --mode smoke          # separate tiny DATA/BUDGET, real models; not evidence
python run.py --mode plots          # rebuild all plots/tables; no model load
python run.py --mode package        # rebuild archives after training
python run.py --mode status
```

Optional compression is not run by default. To do it, copy `config.json`, change only
`visual_tokens` to 49, and use `--config config49.json --output outputs/compression49`.
It repeats the whole recipe from a fresh connector/adapters with 2×2 mean pooled patches.
Keep its evidence separate and compare time/memory/grounding afterward.

## Sources and attribution

The pasted assignment is the experimental source of truth. Assisted implementation:
review/understand it and disclose material code assistance as your course requires.

- [Qwen checkpoint and non-thinking chat template](https://huggingface.co/Qwen/Qwen3-0.6B)
- [SigLIP implementation, including final post-layernorm](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/siglip/modeling_siglip.py)
- [Official VQA downloads and complementary-pair format](https://visualqa.org/download.html)
- [Official VQA normalization source](https://github.com/GT-Vision-Lab/VQA/blob/master/PythonEvaluationTools/vqaEvaluation/vqaEval.py)

The contraction mapping is extracted as data from that normalization source; its URL and
SHA256 are recorded in `task2/normalization_source.json`. Every answer/reference is always
normalized consistently, including unanimous reference sets, per the assignment.
