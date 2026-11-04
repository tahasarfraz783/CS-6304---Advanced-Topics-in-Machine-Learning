import statistics
import time
import torch
from .common import write, seed_all
from .data import Sampler
from .training import optimizer_for, check_interface


def preflight(root, cfg, model, store, manifest, progress):
    """Disposable real-model throughput check; caller recreates model before official run."""
    seed_all(cfg['seed'])
    calibration = model.calibrate(manifest['train']['captions'][:64], store)
    check_interface(model, store, manifest, root)
    sampler = Sampler(manifest, cfg['seed'])
    result = dict(calibration=calibration, gpu=torch.cuda.get_device_name(),
                  total_gpu_bytes=torch.cuda.get_device_properties(0).total_memory, stages=[])
    for stage in range(1, 4):
        if stage > 1:
            model.enable_lora()
        model.train()
        optimizer = optimizer_for(model, cfg, stage)
        scaler = torch.amp.GradScaler('cuda')
        torch.cuda.reset_peak_memory_stats()
        durations, skipped = [], 0
        progress.emit(f'preflight stage {stage}', 0, 20)
        for step in range(20):
            batch, _ = sampler.batch(stage)
            torch.cuda.synchronize()
            start = time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            for first in [0, 8]:
                micro = batch[first:first+8]
                with torch.autocast('cuda', dtype=torch.float16):
                    loss = model.losses(micro, store.batch(micro)).mean()/2
                scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.)
            old = scaler.get_scale()
            scaler.step(optimizer)
            scaler.update()
            skipped += scaler.get_scale() < old
            if not torch.isfinite(loss) or not torch.isfinite(norm):
                if step >= 5:
                    raise FloatingPointError('AMP remains unstable after preflight warmup')
            torch.cuda.synchronize()
            durations.append(time.perf_counter()-start)
            progress.emit(completed=step+1)
        if skipped > 5:
            raise RuntimeError(f'Preflight AMP skipped {skipped}/20 updates; inspect scaler/gradients')
        seconds = statistics.median(durations[5:])
        result['stages'].append(dict(stage=stage, median_seconds_per_update=seconds,
            examples_per_second=16/seconds, projected_training_seconds=seconds*cfg['stage_updates'][stage-1],
            peak_gpu_bytes=torch.cuda.max_memory_allocated(), parameters=model.parameter_counts(), amp_skips=skipped))
        del optimizer
    model.eval()
    examples = [r for p in manifest['dev']['natural'] for r in p][:8]
    torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
        preds = model.generate(examples, store.batch(examples))
        no_image = model.generate(examples, None, 'none')
        nll = model.losses(examples, store.batch(examples), include_end=False)
    assert len(preds) == len(examples) == len(no_image) and torch.isfinite(nll).all()
    torch.cuda.synchronize()
    result.update(generation_test_seconds=time.perf_counter()-start,
        generation_batch=cfg['generation_batch'], likelihood_batch=cfg['likelihood_batch'],
        training_only_estimate_seconds=sum(r['projected_training_seconds'] for r in result['stages']),
        note='Disposable training, excludes preparation/dev/final/packaging; estimates from 15 post-warmup updates per stage. Not scientific evidence.')
    # Exercise the actual larger NLL batch, including no-image and swap.
    for condition in ['correct', 'swap', 'none']:
        batch = [r for p in manifest['dev']['natural'] for r in p][:cfg['likelihood_batch']]
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
            nll = model.losses(batch, None if condition == 'none' else store.batch(batch, condition), condition, False)
            assert torch.isfinite(nll).all()
    # Tune only teacher-forced evaluation batching: it does not alter the
    # mandated training microbatch or final greedy decoding batch.
    candidates = []
    captions = manifest['dev']['captions']
    for size in [8, 16, 32, 64]:
        batch = (captions*((size+len(captions)-1)//len(captions)))[:size]
        try:
            features = store.batch(batch)
            times = []
            torch.cuda.reset_peak_memory_stats()
            for trial in range(3):
                torch.cuda.synchronize()
                start = time.perf_counter()
                with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
                    value = model.losses(batch, features)
                torch.cuda.synchronize()
                assert torch.isfinite(value).all()
                if trial:
                    times.append((time.perf_counter()-start)/size)
            peak = torch.cuda.max_memory_allocated()
            if peak < .9*result['total_gpu_bytes']:
                candidates.append(dict(batch=size, seconds_per_example=statistics.median(times), peak_gpu_bytes=peak))
            progress.emit('tune likelihood batch', size, 64)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            break
    if not candidates:
        raise RuntimeError('No teacher-forced evaluation batch fits with memory headroom')
    chosen = min(candidates, key=lambda r:r['seconds_per_example'])['batch']
    result.update(likelihood_batch_candidates=candidates, chosen_likelihood_batch=chosen)
    write(root/'evaluation_runtime.json', dict(likelihood_batch=chosen, selection_rule='Lowest median seconds/example; 2 timed trials after 1 warmup; caption dev data; <90% allocated VRAM. Final decoding remains batch 8.'))
    write(root/'preflight.json', result)
    return result
