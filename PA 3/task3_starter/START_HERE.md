# Start Task 3 on your A100 80 GB

Upload and extract `task3_starter_upload.zip` at the Jupyter root. Reuse the working CUDA Python environment from Task 2. In `task3_starter`, run:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
nohup python -u run.py --mode run > task3.log 2>&1 &
python monitor.py
```

One launcher downloads the five supplied Parquet files, checks joins/token alignment, saves the splits and answer groups, runs all 250 controlled GPU calls, completes offline/adaptive analyses, then builds plots, tables, examples, report notes, and a verified download archive.

Open `outputs/assignment/evidence/index.html` through Jupyter for the dashboard. It exists from startup. `python monitor.py` shows stage counters, detail, heartbeat age, and estimated stage time remaining. During generation, the detail advances every 32 tokens. See `task3.log` for errors. GPU utilization/memory/power samples are recorded every 15 seconds when `nvidia-smi` is available.

The live experiment **must use batch size 1, FP16, no quantization**. The launcher preserves this. It uses PyTorch SDPA attention, KV caching, inference mode, GPU-resident weights, one model load, and a disposable warm-up and measured 64-token throughput preflight. The preflight saves measured generation throughput and peak memory in live/preflight.json. Offline analysis uses eight processes with one BLAS thread each. Increasing VRAM occupation would not itself improve this workload.

Resume with the identical launcher command after confirming the prior process has stopped. Completed question analyses and live calls are reused. If a hard kill left `.run.lock`, check its recorded PID before removing that specific lock. Never run two launchers on the same output folder. Code/config/input changes require a new output folder.

Download `outputs/assignment/downloads/task3_results.zip` and `SHA256.json` after completion. No trained model is produced or needed. Stop the rental instance yourself after verifying downloads.

The lightweight upload downloads about 419 MB of supplied Parquet data. If Drive is unavailable, use `task3_starter_with_data.zip` instead; it contains the same code plus all five files. Keep roughly 12 GB free before starting for model/cache/results headroom. The listed rental disk has about 14 GB free, so inspect free space before launch and reuse existing Hugging Face caches where possible.

Local verification does not establish A100 runtime or live accuracy. Those are measured by the actual GPU experiment. Any locally generated offline evidence is labeled separately from live results.
