"""ONE entry point. python run.py --mode run resumes the entire experiment."""
import argparse
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import zipfile
from task2.common import read, write, digest, Progress, jsonl

HERE = Path(__file__).resolve().parent


def package(root):
    from task2.plots import build_evidence
    build_evidence(root)
    dest = root/'downloads'
    dest.mkdir(exist_ok=True)
    archives = {}
    import hashlib
    for name, folders in [('task2_results.zip', ['evidence', 'evaluations', 'prepared']), ('task2_models.zip', ['exports'])]:
        path = dest/name
        with zipfile.ZipFile(str(path)+'.tmp', 'w', zipfile.ZIP_DEFLATED if 'results' in name else zipfile.ZIP_STORED) as z:
            for folder in folders:
                for f in sorted((root/folder).rglob('*')):
                    if f.is_file() and 'features' not in f.relative_to(root).parts:
                        z.write(f, f.relative_to(root))
            if 'results' in name:
                for f in root.iterdir():
                    if f.is_file() and f.suffix in {'.json', '.jsonl'}:
                        z.write(f, f.name)
                for f in HERE.rglob('*'):
                    if f.is_file() and not any(p in {'outputs', '.venv', '__pycache__', '.git'} for p in f.relative_to(HERE).parts) and f.suffix in {'.py', '.json', '.md', '.txt', '.sh'}:
                        z.write(f, Path('code')/f.relative_to(HERE))
        Path(str(path)+'.tmp').replace(path)
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
        sha = hashlib.sha256()
        with open(path, 'rb') as f:
            while b := f.read(8*1024*1024):
                sha.update(b)
        archives[name] = dict(bytes=path.stat().st_size, sha256=sha.hexdigest())
    write(dest/'SHA256.json', archives)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['plan', 'check', 'prepare', 'preflight', 'run', 'smoke', 'plots', 'status', 'package'], default='plan')
    parser.add_argument('--config', type=Path, default=HERE/'config.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = read(args.config)
    if args.mode == 'smoke':
        cfg.update(stage_updates=[3, 3, 3], caption_images=16, caption_dev_images=4,
                   ground_dev_pairs=4, ground_test_pairs=4, natural_train_counts=[4, 4, 4],
                   natural_dev_counts=[2, 2, 2], natural_test_counts=[2, 2, 2], checkpoint_every=1,
                   dev_every=3, bootstrap_resamples=100)
    root = (args.output or HERE/'outputs'/('smoke' if args.mode == 'smoke' else 'assignment')).resolve()
    if args.mode == 'plan':
        print('Task 2: select/download -> cache SigLIP -> disposable preflight -> baseline dev -> 2250/1500/750 updates -> four-condition final -> plots/tables/archives.\n'+json.dumps(cfg, indent=2))
        print('One full-run command: python -u run.py --mode run\nDashboard: outputs/assignment/evidence/index.html\nLive status: python monitor.py\nFinal-test batch 8 is mandatory. No full-run speed claim until preflight. Optional 49-token run requires a NEW output directory.')
        return
    if args.mode == 'status':
        p = root/'progress.json'
        print(json.dumps(read(p), indent=2) if p.exists() else 'No run status yet')
        return
    if args.mode == 'plots':
        from task2.plots import build_evidence
        build_evidence(root)
        return
    if args.mode == 'package':
        package(root)
        return
    import torch
    from task2.common import seed_all
    from task2.data import prepare, download_images, label_review
    from task2.model import cache_features, FeatureStore, VLM
    from task2.preflight import preflight
    from task2.training import train
    from task2.telemetry import Telemetry
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required; no accidental CPU training')
    assert cfg['microbatch'] == 8 and cfg['accumulation'] == 2 and cfg['generation_batch'] == 8
    assert cfg['visual_tokens'] in [196, 49]
    root.mkdir(parents=True, exist_ok=True)
    if args.mode == 'check':
        print(torch.cuda.get_device_name(), torch.cuda.get_device_properties(0).total_memory/2**30, 'GiB')
        for name in ['torch', 'transformers', 'peft', 'numpy', 'Pillow', 'matplotlib']:
            print(name, importlib.metadata.version(name))
        print('Free disk GiB:', shutil.disk_usage(root).free/2**30)
        return
    config_path = root/'resolved_config.json'
    if config_path.exists() and read(config_path) != cfg:
        raise ValueError('Configuration changed. Use a NEW --output directory; never mix experiments.')
    write(config_path, cfg)
    if shutil.disk_usage(root).free < 12*2**30:
        raise RuntimeError('Need at least 12 GiB free for selected images, annotations, caches, checkpoints and packaging. Inspect disk before proceeding.')
    lock = root/'.run.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f'Another run may be active. Inspect {lock}; remove it only after confirming the recorded process has stopped.')
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    progress = Progress(root)
    telemetry = Telemetry(root)
    session_start = time.perf_counter()
    session_status = 'failed'
    try:
        environment = dict(python=sys.version, platform=platform.platform(),
            packages={n:importlib.metadata.version(n) for n in ['torch', 'transformers', 'peft', 'numpy', 'Pillow', 'matplotlib']},
            cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(), total_gpu_bytes=torch.cuda.get_device_properties(0).total_memory)
        write(root/'environment.json', environment)
        jsonl(root/'environment_history.jsonl', dict(timestamp=time.time(), **environment))
        seed_all(cfg['seed'])
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.set_num_threads(min(8, os.cpu_count() or 1))
        manifest = prepare(root, cfg, progress)
        download_images(root, manifest, cfg, progress)
        progress.emit('render independent grounding label review')
        label_review(root, manifest)
        cache_features(root, manifest, cfg, progress)
        if args.mode == 'prepare':
            session_status = 'prepared'
            progress.close('prepared')
            return
        # Resident feature cache is only a few GiB and avoids thousands of CPU/GPU copies.
        store = FeatureStore(root, cfg, device='cuda')
        if args.mode in ['run', 'preflight'] and not (root/'preflight.json').exists() and not list((root/'checkpoints').glob('*.pt')):
            seed_all(cfg['seed'])
            revision_path = root/'base_revision.json'
            revision = read(revision_path)['revision'] if revision_path.exists() else None
            model = VLM(cfg, revision)
            write(revision_path, dict(model=cfg['language_model'], revision=getattr(model.lm.config, '_commit_hash', None)))
            result = preflight(root, cfg, model, store, manifest, progress)
            print('Measured training-only estimate:', round(result['training_only_estimate_seconds']/60, 1), 'minutes; dev/generation/cache excluded.', flush=True)
            del model
            gc.collect()
            torch.cuda.empty_cache()
        if args.mode == 'preflight':
            session_status = 'preflight complete'
            progress.close('preflight complete')
            return
        runtime = root/'evaluation_runtime.json'
        if runtime.exists():
            cfg['likelihood_batch'] = read(runtime)['likelihood_batch']
        write(root/'effective_config.json', cfg)
        seed_all(cfg['seed'])
        revision_path = root/'base_revision.json'
        revision = read(revision_path)['revision'] if revision_path.exists() else None
        model = VLM(cfg, revision)
        write(revision_path, dict(model=cfg['language_model'], revision=getattr(model.lm.config, '_commit_hash', None)))
        write(root/'model_provenance.json', dict(language_config=model.lm.config.to_dict(),
            language_commit=getattr(model.lm.config, '_commit_hash', None),
            attention='torch SDPA', frozen_dtype='float16', trainable_dtype='float32',
            checkpointing='nonreentrant', thinking=False, quantization=None))
        train(root, cfg, model, store, manifest, progress)
        write(root/'wall_time_before_packaging.json', dict(seconds=time.perf_counter()-session_start, includes='This invocation: preparation, disposable preflight if needed, training/evaluation, saves and plots; excludes subsequent packaging. See run_sessions.jsonl for previous attempts.'))
        if args.mode != 'smoke':
            progress.emit('package evidence and model weights')
            package(root)
        progress.close('complete')
        session_status = 'complete'
        from task2.plots import build_evidence
        build_evidence(root)
    except BaseException as exc:
        progress.emit(error=repr(exc))
        progress.close('failed')
        raise
    finally:
        jsonl(root/'run_sessions.jsonl', dict(mode=args.mode, status=session_status, seconds=time.perf_counter()-session_start, timestamp=time.time()))
        telemetry.close()
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
