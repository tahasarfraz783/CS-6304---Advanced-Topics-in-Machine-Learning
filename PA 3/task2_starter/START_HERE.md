# Start Task 2 on your A100

1. Upload/extract `task2_starter_upload.zip` at your instance's Jupyter root.
2. In a terminal, enter the extracted `task2_starter` directory.
3. Reuse the working CUDA environment from Task 1, then run:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python run.py --mode check
nohup python -u run.py --mode run > task2.log 2>&1 &
python monitor.py
```

The **one experiment launcher is `run.py --mode run`**. It reuses the locally verified
selection manifest (9,404 images, correct quotas, no evaluation leakage), downloads JPEGs,
caches image features, runs a disposable throughput preflight, then completes the
three training stages, evaluations, and download archives. No manual stage handoffs.

Watch `task2.log` and open `outputs/assignment/evidence/index.html` in Jupyter.
The dashboard is created after baseline evaluation. Before that, downloads/cache/preflight
have terminal counters and 15-second heartbeats. The label-review gallery appears during
preparation at `outputs/assignment/evidence/label_review/index.html`.

The preflight measures the real model on your GPU. It automatically chooses a measured
likelihood batch; it preserves mandatory training 8×2 and final generation batch 8.
Fresh official weights/RNG are recreated after the disposable preflight.

To resume, run the same `nohup` command once the old process has stopped. If a hard kill
left `.run.lock`, inspect its recorded PID and remove that one lock only after confirming
the process stopped. Do not start two launchers against the same output directory.

After completion, download both ZIPs and `SHA256.json` from
`outputs/assignment/downloads/`, verify them, then stop the instance yourself.
Read `README.md` for evidence paths, methodology, storage, and recovery details.

Local verification covers numeric/model/protocol/plot/recovery tests, not a completed
A100 run. Actual A100 throughput and peak VRAM are deliberately measured by preflight;
no fixed runtime or near-full-VRAM promise is made.
