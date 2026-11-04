import argparse
import json
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'outputs'/'assignment')
p.add_argument('--once', action='store_true')
args = p.parse_args()
while True:
    path = args.output/'progress.json'
    if path.exists():
        try:
            s = json.loads(path.read_text(encoding='utf-8'))
            age = time.time()-s['timestamp']
            print(f"{s['status']} | {s['phase']} | {s['completed']}/{s['total']} | snapshot age {age:.0f}s | activity age {s.get('activity_age_seconds', 0)+age:.0f}s | ETA {s.get('phase_eta_seconds')}s", flush=True)
            if age > 45:
                print('STALE status: inspect process/log; this is not proof of a running worker.', flush=True)
            if s['status'] in ['complete', 'failed', 'prepared', 'preflight complete']:
                break
        except (OSError, json.JSONDecodeError):
            print('Status is being replaced; retrying.')
    else:
        print('Waiting for progress.json', flush=True)
    if args.once:
        break
    time.sleep(5)
