# Batched evaluation update

The original wrapper forced generation through one question at a time. On the user's
A100-80GB, 16 questions in 132 seconds projected nearly three more hours for baseline
GSM8K alone. Low GPU memory use did not justify a promise of a short evaluation. The
serial wrapper was an implementation throughput limitation, not a PA requirement.

The new wrapper sends batches to the unmodified pinned HFLM generation implementation.
For this A100-80GB instance, select batch size 32 for evaluation. The training microbatch,
gradient accumulation, optimizer updates, and scientific recipe remain unchanged.

## Apply after stopping the instance

Upload `task1_batching_update.zip` at the Jupyter root, then extract over the existing code:

```bash
python -m zipfile -e /task1_batching_update.zip /home
cd /home/task1_starter
PA3_EVAL_BATCH_SIZE=32 python run.py --mode verify-eval
```

The short preflight uses 32 simple requests capped at eight new tokens. It checks:

- Real-model batch execution with sorted/left-padded prompts and repeated prompts.
- Exact response parity with the stock HFLM at the SAME batch size.
- Cache reuse and candidate-likelihood scoring.

It is not a full GSM8K run or a reliable performance benchmark. If preflight fails or runs
out of memory, do not start the official run; preserve the error for diagnosis.

The chosen batch size is saved in `outputs/assignment/evaluation_runtime.json`. Later
workers read it automatically. No edit to the prepared-data configuration is required,
so the existing dataset and bases can be reused. The batch size is frozen to keep all
seven evaluation conditions consistent. If an old runtime file already froze a different
size, the script refuses to change it silently. Do not hand-edit that file to bypass this.

After successful preflight:

```bash
nohup python -u run.py --mode run > experiment_v3.log 2>&1 &
python monitor.py
```

The monitor should display `EVALUATION BATCH SIZE: 32`, a list of current question IDs,
batch decode steps, and completed answers increasing when each batch is saved. The first
batches contain the longest prompts. The measured phase ETA can change as lengths vary.

## Preserved requirements and limitations

- Same four benchmark tasks, complete splits, fixed prompts, zero-shot configuration,
  non-thinking template, greedy decoding, and 1024-new-token GSM8K cap.
- Stock HFLM stopping, answer filtering, and returned response postprocessing stay intact.
- Each generated row is matched back to its question using masked prompt token IDs.
  Early EOS/stop completion is distinguished from batch padding when logging token counts.
- Response order is restored to the original request order before harness scoring.
- Checkpointing and all five training methods are unchanged by this batching update.
- FP16 arithmetic can vary slightly with batch size. Old batch-one answer caches remain
  on disk but are not mixed into the new batched evaluations. New cache filenames and
  keys include the batch setting/version. The first small number of answers must rerun.
- Generation outputs are cached after each completed batch; an interruption can lose
  only the active unfinished batch, not all completed batches.
- Do not project an exact speedup from batching: measure the first few completed batches.
  Padding, answer lengths, model kernels, and CPU overhead still affect runtime.

## Local verification

Tests use the actual pinned HFLM with a small random Qwen model and local tokenizer. They
compare stock/traced answers at matching batch sizes, verify original output order,
unequal padding lengths, repeated prompts, per-row EOS/stop/cap metadata, saved-answer
recovery, and freezing runtime batch settings. Cloud memory/speed must still be checked
by the real-model preflight; tiny tests do not establish production throughput.
