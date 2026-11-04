# PA3 Task 1: one launcher, five training runs

**Batched evaluation:** read `BATCHING_UPDATE.md` for the A100-80GB setup. Select evaluation
batch 32 during preflight using `PA3_EVAL_BATCH_SIZE=32`; it is recorded separately and
reused automatically. The old forced-single-question generation loop has been removed.

**Monitoring update:** see `MONITORING_UPDATE.md`. The runner now prints real answer/update
counts, emits 15-second heartbeats, saves each generated answer, reuses completed benchmark
results, and writes `progress.txt`, `progress.json`, and `pipeline_status.json` under the
output folder. Use `python monitor.py` or `python run.py --mode status` to inspect progress.
Use the short `--mode verify-eval` check when resuming the prepared cloud instance.
Training retains the four prescribed recovery checkpoints and also saves a single rotating
extra checkpoint every 100 updates. Newer saves replace obsolete rolling recovery states;
required checkpoints remain available. See the monitoring guide for resume details.

This is an educational starter implementation, not a finished experiment or report.
`run.py` coordinates the five independent runs and saves evidence as it becomes available.
The actual Qwen/data/evaluation path still needs validation on the training GPU. All five
training methods and exact OPLoRA resume have passed a tiny offline CUDA test, but no
assignment-scale training or benchmark numbers have been generated in this workspace.
See `METHODOLOGY_AUDIT.md` for the requirement-by-requirement review and remaining checks.

## Start here

Read `WALKTHROUGH.md` before running the full experiment. First inspect the plan; this needs
only Python and downloads nothing:

```powershell
cd "D:\LUMS GAMING\6. 2026 Fall\CS 6304\Programming Assignments\PA 3\task1_starter"
python run.py --mode plan
```

The project is portable: copy this directory to your GPU machine, change into it, and use the
same relative commands. Linux/WSL is a useful training environment; the scripts also use
portable Python paths and subprocesses for Windows.

## Directory map

```text
task1_starter/
  run.py                    # the ONE file you launch
  config.json               # prescribed settings in one place
  requirements.txt
  README.md
  WALKTHROUGH.md            # learning guide, read in order
  inputs/
    README.md
    first_plot_questions.yaml  # YOU supply the original course file
    qualitative.json           # inspected normalization of its 24 prompts
  task1/
    common.py               # files, configuration, schedules
    data.py                 # filtering, tokenization, response-only labels, probe IDs
    model.py                # readable LoRA/OPLoRA and merge operations
    training.py             # the training loop, logging, recovery checkpoints
    diagnostics.py          # shared bases/activations; rho, eta, R(z)
    evaluation.py           # stock lm-eval tasks + qualitative generations
    plots.py                # SVG plots, CSV tables, local evidence index
  tests/
    test_starter.py         # offline orchestration/evidence checks
    test_torch_core.py      # actual adapter/loss checks once torch is installed
  outputs/                  # generated, gitignored
    assignment/
      resolved_config.json
      environment.json
      stage_times.csv
      prepared/             # frozen starting model, selected examples/IDs, bases, probes
      runs/
        full_ft/            # likewise l2sp, lora4, lora16, oplora16
          training.csv
          resources.json
          checkpoints/
            update_0312.pt
            update_0625.pt
            update_0937.pt
            update_1250.pt
      evaluations/
        baseline_0000/
        full_ft_0625/
        full_ft_1250/       # plus the other four final conditions
          scores.json
          *_samples.jsonl
          qualitative.jsonl
          weights.csv
          activations.csv
      evidence/
        index.html          # open this to browse current evidence
        *.svg               # loss, LR, benchmarks, updates, activations, resources
        benchmarks.csv
        resources.csv
        annotation_template.csv
        responses_by_question.txt
      logs/
```

Not every file exists immediately: loss curves appear during training; scores appear after
evaluation; diagnostic plots appear after their checkpoint measurements. The baseline has
no update diagnostics. Full FT has no adapter export or merge check.

## Hardware and installation

Your detected RTX 4050 laptop GPU has 6 GB VRAM. Use it to read/debug small pieces; the full
prescribed Full FT setup is expected to exceed this memory. Roughly 0.6 billion parameters
times 16 bytes (FP32 weights + gradients + two Adam moments) is already about 9.6 GB before
activations, temporary computations, or CUDA overhead. L2-SP needs additional temporaries.
Aim for a GPU with around 24 GB or more and preferably at least 32 GB system RAM; exact
peak usage must be measured. This code does not silently lower batch size, quantize, or
offload optimizer states to make a different experiment fit.

Create a dedicated environment with Python 3.11 or 3.12. Install the CUDA-enabled PyTorch
build appropriate to the machine using https://pytorch.org/get-started/locally/, then:

```text
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python run.py --mode check
```

The package pins are a proposed starting environment, not a GPU-tested lockfile. The runner
saves actual package versions, Python/CUDA versions, GPU, model commit, dataset fingerprints,
and harness task configurations in results. Preserve those files and freeze the working
environment before official runs. Do not upgrade libraries partway through the experiment.

## Course prompts (now included)

The supplied `inputs/first_plot_questions.yaml` is included unchanged, with a generated
`inputs/qualitative.json`. Regenerate it with:

```text
python prepare_prompts.py
```

The loader verifies the generated JSON against the YAML on every load. It preserves all
24 prompts in source order, including the SYSTEM message in the JSON variants. The first
and last plain questions (`what_is_your_wish`, `enough_of_my_husband`) are automatically
flagged in all three formats, producing the required 42-response annotation subset across
seven conditions. No manual transcription is needed.

The YAML's original 100-sample and GPT-4o judge settings are NOT executed. PA3 requires one
greedy generation per prompt per condition and your own qualitative annotations.

## Commands, in the order you will actually use them

```text
python run.py --mode plan
python run.py --mode check
python run.py --mode prepare
python run.py --mode timing --method full_ft
python run.py --mode timing --method lora16
python run.py --mode smoke
python run.py --mode cleanup-tests
python run.py --mode run
```

- `plan`: print the experiment without ML dependencies or downloads.
- `check`: verify imports, CUDA, and the qualitative prompt files. Warn on small VRAM.
- `prepare`: download/freeze the base model and prepare the shared training data/probe IDs.
- `timing`: 20 real training updates on 640 eligible examples, in `outputs/timing/`.
  The maximum sequence length remains 2048. The first five updates are excluded from the
  estimate. Use separate `--output` directories for independent repeat timing measurements.
  It estimates ONE method's training time; it does not time the complete evaluation workload.
- `smoke`: reduced 128-example/four-update runs, two examples per benchmark, and 32-token
  generation caps, in `outputs/smoke/`. Still uses the real Qwen model, all target matrices,
  exact SVD/probes, and original course prompts. This is NOT a lightweight 6 GB Full FT test
  and is NOT reportable assignment evidence. It checks the entire path on the target GPU.
- `run`: the full five-run experiment with all seven required evaluations.
- `plots`: rebuild plots/tables from existing logs without loading models.
- `cleanup-tests`: explicitly remove only the default disposable smoke/timing output
  directories, after validating their test-run markers. Save any test logs you want first.
  The official assignment directory is never removed by this command.
- `package`: rebuild verified download archives after a completed official run, without a GPU.

**Disk space:** timing and smoke checkpoints include full Adam states despite their short
training length. Keeping both complete test runs plus the official run can exceed a 95 GB
disk. The official launcher refuses to proceed while default test checkpoints remain; run
`cleanup-tests` after the smoke test succeeds. Official recovery checkpoints are retained.

**Downloads:** the official run exports standalone FP16 Hugging Face inference models for
the five finals and Full FT midpoint, then automatically builds:

```text
outputs/assignment/downloads/task1_results.zip
outputs/assignment/downloads/task1_models.zip
outputs/assignment/downloads/SHA256.json
```

The results ZIP contains raw benchmark outputs, qualitative responses/annotation template,
plots/tables, configuration/provenance, and source code. The models ZIP contains six model
directories with their tokenizers; projected adapters are already merged. Both archives are
verified internally and SHA256 hashes are provided for checking the downloaded copies.
Models use ZIP_STORED to avoid spending GPU rental time trying to compress floating-point weights.
Recovery optimizer checkpoints are NOT included in these archives; download the runs folder
separately if you also want exact recovery states/FP32 master weights. Final effective adapter
factors remain available separately in runs/lora4, runs/lora16, and runs/oplora16.

Archives need additional disk space. If packaging runs out of room, the measured results and
exported model folders remain intact; download the folders directly instead. The launcher
does not stop or destroy any cloud instance. Finishing the Python process does not stop GPU
billing. Download and verify your files, then stop/destroy the instance through the provider.
Destroying an instance deletes its local data, so verify the downloads first.

`python run.py --mode run` is the single command for the full workflow after setup. The five
methods run sequentially, so only one training model occupies the GPU at a time. The Full FT
training worker exits at midpoint, evaluation runs separately, then a new training worker
resumes the saved optimizer/scheduler/scaler/RNG/data position. All other methods evaluate at
final only. Diagnostic preparation happens once, before looking at trained model results.

Rerun the same command to resume. Completed evaluations and completed training segments are
reused. Unsaved work after the latest recovery checkpoint is retrained. Any orphaned log rows
are retained in an `interrupted_after_*.csv` file and excluded from active curves. There is
no automatic retry of out-of-memory failures. Change hardware rather than secretly changing
the assignment recipe. Use a NEW `--output` directory if you change the configuration.

## What is saved automatically?

| Required evidence | Location |
|---|---|
| Per-update SFT loss, LR, gradient norm, AMP scale/skips | `runs/*/training.csv` |
| L2-SP omega, weighted penalty, total objective | L2-SP training CSV and separate objective plots |
| Full-model displacement at required checkpoints | `runs/*/displacement_*.json` |
| All four benchmarks and percentage-point changes | `evidence/benchmarks.csv` and SVGs |
| Raw accuracy alongside normalized accuracy | Benchmark table + original harness results |
| Per-example likelihoods, responses, stock answer extraction, cap/truncation flags | `evaluations/*/*_samples.jsonl` |
| Shared task definitions/configurations | `evaluations/*/harness_*.json` |
| Weight-space and per-probe activation diagnostics | Evaluation CSVs + combined evidence CSVs/SVGs |
| Projected OPLoRA adapter exports and numerical constraint checks | `runs/oplora16/` and diagnostic CSVs |
| Merged/unmerged adapter logit verification | `evaluations/*/merge_check.json` |
| Parameters, training time, GPU memory, checkpoint sizes | `runs/*/resources.json`, combined CSV/SVGs |
| Shared SVD/basis preparation overhead | `prepared/diagnostics_ready.json` |
| Adapter export time/storage | `runs/*/export_*.json` |
| End-to-end stage time, including loading and stage work | `stage_times.csv` |
| 168 responses grouped by question/format | `evidence/qualitative_grouped.jsonl`, readable TXT |
| Fixed 42-response annotation subset | `evidence/annotation_template.csv` |

Copy `annotation_template.csv` to `annotations.csv` before adding your judgments. Refreshes
replace the template but never touch `annotations.csv`. The runner does not automate your
interpretation or write your report. The assignment prohibits AI-written report text.

## Timing: calculate instead of guessing

Each method uses 1250 update attempts. After the short timing run:

```text
one method's training hours ~= measured seconds per update * 1250 / 3600
```

For illustration ONLY, 5 seconds/update means 1.74 hours for that method's training, and
20 seconds/update means 6.94 hours. These are arithmetic examples, not predictions for your
hardware. Measure methods separately: their learning rates, projections, and reference
transfers differ. Later batches have different sequence lengths, so a short prefix is only
an estimate. Evaluation also generates up to 1319 * 1024 GSM8K tokens per condition and
scores all retention splits; seven evaluations can add substantial time.

## Implementation choices to understand and review

- No old-task data is used for training or replay. GSM8K test questions are used only for
  prescribed leakage exclusion, evaluation, and fixed diagnostic probes.
- Text normalization is explicit: Unicode NFKC + case folding + whitespace collapse,
  preserving punctuation. Save/justify this policy if the course specifies another one.
- Qwen's non-thinking generation prefix is shared between training and generation.
  Supplied responses and `<|im_end|>` contribute to training loss; prompts/padding do not.
- FP16 autocast and dynamic scaling are used for training. Full FT parameters and optimizer
  moments are FP32. Adapter parameters/projection bases are FP32; frozen backbone is FP16.
- L2-SP references live in CPU memory, are transferred for the penalty, and are counted once
  per unique parameter. This favors a readable implementation over faster specialized code;
  transfer overhead is explicitly logged. Full FT keeps a CPU reference for displacement.
- The original FP32 starting snapshot is frozen locally. Evaluation uses FP16 copies.
- OPLoRA bases are computed with exact FP32 SVD once for all targeted matrices. Diagnostics
  reuse those same bases. Shared setup time must be shown separately and charged appropriately
  when discussing OPLoRA overhead; it is not hidden inside optimizer-step timing.
- Probe forwards, cached activations, SVD, and local diagnostic calculations use FP32.
  Benchmark/qualitative evaluation remains FP16, as required separately by the assignment.
- Stock harness tasks, stopping rules, and answer filters are retained. GSM8K uses non-thinking
  chat and greedy generation; retention benchmarks use completion prompts without chat.
- Merge verification uses two fixed probe prompts, logs absolute/relative logit differences,
  and stops on a relative L2 error above 0.02. Inspect the actual errors; FP16 merging introduces
  rounding, and this engineering threshold is not an assignment-specified tolerance.
- Full FT and L2-SP have a different learning rate from adapters, as prescribed. Equal examples
  do not imply equal compute, and these comparisons do not isolate every possible confound.
- Recovery checkpoints are large: full runs save weights AND FP32 Adam states four times.
  Ensure ample local disk space. Do not commit raw data, model snapshots, or checkpoints.

## Attribution / sources for this starter

This starter was written with LLM coding assistance. Review and understand it before using it;
attribute materially reused assisted code in your submitted README as required by PA3.

The model/dataset/evaluator APIs follow these primary references:

- Qwen model and non-thinking template: https://huggingface.co/Qwen/Qwen3-0.6B
- MetaMathQA source: https://huggingface.co/datasets/meta-math/MetaMathQA
- Harness Python API: https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/python-api.md
- Stock GSM8K task: https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/gsm8k/gsm8k-cot.yaml
- PyTorch AMP: https://pytorch.org/docs/stable/amp.html

PA3.pdf is the source of experiment requirements; Fine Tuning Notes.pdf supplies the conceptual
framework. This README is implementation documentation, not prose for the submitted PDF report.
