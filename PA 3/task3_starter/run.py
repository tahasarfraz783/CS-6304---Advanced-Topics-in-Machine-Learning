"""One launcher for download -> validate/prepare -> live GPU -> offline CPU -> evidence -> archive."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
import concurrent.futures
from task3.common import read,write,sha,Progress,run_lock

HERE=Path(__file__).resolve().parent


def package(root):
    dest=root/'downloads';dest.mkdir(exist_ok=True);target=dest/'task3_results.zip'
    with zipfile.ZipFile(str(target)+'.tmp','w',zipfile.ZIP_DEFLATED) as z:
        for folder in ['evidence','offline','splits','live','validation']:
            for f in sorted((root/folder).rglob('*')):
                if f.is_file():z.write(f,f.relative_to(root))
        for f in root.glob('*.json'):z.write(f,f.name)
        for f in root.glob('*.csv'):z.write(f,f.name)
        for f in HERE.rglob('*'):
            rel=f.relative_to(HERE)
            if f.is_file() and not any(p in {'outputs','downloads','__pycache__','.git'} for p in rel.parts) and f.suffix in {'.py','.md','.json','.txt','.MD','.reference'}:
                z.write(f,Path('code')/rel)
    Path(str(target)+'.tmp').replace(target)
    with zipfile.ZipFile(target) as z:assert z.testzip() is None
    write(dest/'SHA256.json',{target.name:dict(bytes=target.stat().st_size,sha256=sha(target))})


def check():
    from task3.data import input_manifest
    manifest=input_manifest(HERE/'inputs')
    print('Input files validated:',len(manifest))
    import torch
    print('CUDA available:',torch.cuda.is_available())
    if torch.cuda.is_available():print(torch.cuda.get_device_name(),torch.cuda.get_device_properties(0).total_memory/2**30,'GiB')
    print('Disk free:',shutil.disk_usage(HERE).free/2**30,'GiB')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['plan','check','prepare','offline','live','run','plots','package','status'],default='plan')
    p.add_argument('--output',type=Path,default=HERE/'outputs'/'assignment')
    p.add_argument('--workers',type=int,default=8)
    a=p.parse_args();root=a.output.resolve()
    if a.workers<1:raise ValueError('workers must be positive')
    if a.mode=='plan':
        print(__doc__+'\nLive protocol: pinned Qwen2.5-3B, FP16, batch 1, SDPA, KV cache.\nCPU: 8 processes by default.\nStart: python -u run.py --mode run\nStatus: python monitor.py\nDashboard: outputs/assignment/evidence/index.html');return
    if a.mode=='status':print(read(root/'progress.json') if (root/'progress.json').exists() else 'Not started');return
    if a.mode=='check':check();return
    # Keep child BLAS libraries single threaded to avoid oversubscribing 32 vCPUs.
    for var in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[var]='1'
    from task3.evidence import build,dashboard
    with run_lock(root),Progress(root) as progress:
        try:
            if a.mode=='plots':build(root);return
            if a.mode=='package':package(root);return
            if a.mode in ('run','live'):
                import torch
                if not torch.cuda.is_available():raise RuntimeError('CUDA is required for the live comparison. Run this mode on the rental GPU; prepare/offline modes can run on CPU.')
            cfg=read(HERE/'config.json')
            from task3.live import MODEL,REVISION
            expected=dict(seed=6304,workers=8,model=MODEL,revision=REVISION,live_batch_size=1,
                          live_dtype='float16',quantization=False,bootstrap_resamples=1000,orders=10)
            if cfg!=expected:raise ValueError('This assignment protocol is fixed; config.json differs from the validated protocol. Use --workers for CPU concurrency.')
            identity={'config':cfg,'source':{f.relative_to(HERE).as_posix():sha(f) for f in sorted(HERE.rglob('*.py')) if not any(x in {'outputs','downloads','__pycache__'} for x in f.relative_to(HERE).parts)}}
            old=root/'run_identity.json'
            if old.exists() and read(old)!=identity:raise RuntimeError('Code/config changed: use a new --output directory')
            write(old,identity)
            write(root/'environment.json',dict(python=sys.version,platform=platform.platform(),workers=a.workers,
                  packages={n:importlib.metadata.version(n) for n in ['numpy','pandas','pyarrow','scipy','math-verify']}))
            dashboard(root)
            if a.mode in ('run','prepare'):
                progress.update('download',0,5)
                subprocess.run([sys.executable,str(HERE/'download_data.py')],check=True)
                from task3.data import prepare
                if a.mode=='run':
                    # Network/model caching overlaps CPU preparation, never live timing.
                    from huggingface_hub import snapshot_download
                    with concurrent.futures.ThreadPoolExecutor(1) as cache_pool:
                        cached=cache_pool.submit(snapshot_download,repo_id=MODEL,revision=REVISION,
                              allow_patterns=['*.json','*.safetensors','tokenizer*','merges.txt','vocab.json','*.model'],max_workers=4)
                        prepare(HERE/'inputs',root,a.workers,progress)
                        progress.update('finish model cache',0,1,'pinned weights; no model loading or GPU timing yet')
                        cached.result()
                else:prepare(HERE/'inputs',root,a.workers,progress)
            if a.mode in ('run','live') and not (root/'live_complete.json').exists():
                from task3.live import run_live
                run_live(root,progress)
            if a.mode in ('run','offline'):
                from task3.offline import run_offline
                run_offline(root,a.workers,progress)
            build(root)
            if a.mode=='run':
                progress.update('packaging',0,1)
                write(root/'complete.json',dict(time=time.time(),live=(root/'live_complete.json').exists(),offline=(root/'offline_complete.json').exists()))
                package(root)
            progress.update('complete',1,1,a.mode+' complete')
        except BaseException as e:
            progress.update('failed',0,1,str(e))
            write(root/'failure.json',dict(error=repr(e),traceback=traceback.format_exc()))
            raise


if __name__=='__main__':main()
