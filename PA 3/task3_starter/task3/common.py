import contextlib
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import subprocess


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''): h.update(b)
    return h.hexdigest()


class Progress:
    def __init__(self,root):
        self.root=Path(root);self.state={'stage':'starting','done':0,'total':0,'started':time.time()}
        self.lock=threading.Lock();self.stop=threading.Event()
    def update(self,stage,done,total,detail=''):
        with self.lock:
            if self.state['stage']!=stage:self.state['stage_started']=time.time()
            self.state.update(stage=stage,done=int(done),total=int(total),detail=detail)
            self.flush()
    def flush(self):
        now=time.time();elapsed=now-self.state.get('stage_started',now)
        done=self.state['done'];total=self.state['total']
        tail=done<total and total>=100 and total-done<=max(1,int(total*.01))
        write(self.root/'progress.json',dict(self.state,heartbeat=now,pid=os.getpid(),
              stage_elapsed_seconds=elapsed,eta_seconds=elapsed*(total-done)/done if done and not tail else None,
              eta_note='tail work has variable duration' if tail else 'average completed work'))
    def beat(self):
        while not self.stop.wait(15):
            with self.lock:
                self.flush()
                s=self.state
                print(f"[{s['stage']}] {s['done']}/{s['total']} {s.get('detail','')}",flush=True)
            try:
                result=subprocess.run(['nvidia-smi','--query-gpu=timestamp,utilization.gpu,memory.used,memory.total,power.draw','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4)
                if result.returncode==0:
                    with (self.root/'gpu_telemetry.csv').open('a',encoding='utf-8') as f:f.write(result.stdout)
            except (OSError,subprocess.TimeoutExpired):pass
    def __enter__(self):
        self.thread=threading.Thread(target=self.beat,daemon=True);self.thread.start();return self
    def __exit__(self,*args):
        self.stop.set();self.thread.join()


@contextlib.contextmanager
def run_lock(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);p=root/'.run.lock'
    try: fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise RuntimeError(f'{p} exists. Check its PID before removing a stale lock.')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try: yield
    finally: p.unlink(missing_ok=True)
