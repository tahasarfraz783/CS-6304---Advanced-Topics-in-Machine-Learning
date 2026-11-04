import argparse,json,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'outputs'/'assignment');p.add_argument('--once',action='store_true');a=p.parse_args()
while True:
    path=a.output/'progress.json'
    if path.exists():
        s=json.loads(path.read_text());age=time.time()-s['heartbeat']
        eta=s.get('eta_seconds');eta=s.get('eta_note','estimating') if eta is None else f'~{eta/60:.1f} min'
        print(f"{s['stage']:24} {s['done']:5}/{s['total']:<5} | {s.get('detail','')} | ETA {eta} | heartbeat {age:.0f}s ago",flush=True)
        if age>60:print('Heartbeat stale: inspect task3.log and process status.',flush=True)
        if s['stage'] in ('complete','failed'):break
    else:print('Waiting for launcher progress...',flush=True)
    if a.once:break
    time.sleep(5)
