import copy
import math
import os
import random
import time
import numpy as np
import torch
from .common import read, write, rows, jsonl, repair_jsonl
from .data import Sampler
from .evaluation import evaluate_dev, evaluate_final


def lr_factor(step, total, warmup=.05, floor=.1):
    warm = max(1, round(total*warmup))
    if step <= warm:
        return step/warm
    ratio = (step-warm)/max(1, total-warm)
    return floor+(1-floor)*.5*(1+math.cos(math.pi*ratio))


def rng_state():
    return dict(python=random.getstate(), numpy=np.random.get_state(), torch=torch.get_rng_state(), cuda=torch.cuda.get_rng_state_all())


def restore_rng(state):
    random.setstate(state['python'])
    np.random.set_state(state['numpy'])
    torch.set_rng_state(state['torch'])
    torch.cuda.set_rng_state_all(state['cuda'])


def save_checkpoint(path, model, optimizer, scaler, sampler, stage, local, update, cfg, resources):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(weights=model.trainable_state(), visual_scale=model.visual_scale.detach().cpu(),
        optimizer=optimizer.state_dict(), scaler=scaler.state_dict(), sampler=sampler.state_dict(),
        rng=rng_state(), stage=stage, local=local, update=update, has_lora=model.has_lora,
        scheduler=dict(local_step=local, total=cfg['stage_updates'][stage-1], warmup=cfg['warmup_fraction'], floor=cfg['lr_floor']),
        config=cfg, resources=resources)
    tmp = path.with_suffix('.tmp')
    torch.save(payload, tmp)
    os.replace(tmp, path)


def optimizer_for(model, cfg, stage):
    groups = [dict(params=list(model.connector.parameters()), lr=cfg['connector_lr'][stage-1])]
    if stage > 1:
        groups.append(dict(params=[p for p in model.lm.parameters() if p.requires_grad], lr=cfg['lora_lr'][stage-1]))
    return torch.optim.AdamW(groups, weight_decay=cfg['weight_decay'], fused=True)


def check_interface(model, store, manifest, root):
    model.train()
    batch = manifest['train']['captions'][:2]
    features = store.batch(batch)
    with torch.autocast('cuda', dtype=torch.float16):
        inputs, labels = model.pack(batch, features)
        loss = model.losses(batch, features).mean()
    loss.backward()
    grad = sum(p.grad.float().square().sum().item() for p in model.connector.parameters() if p.grad is not None)**.5
    assert grad > 0 and math.isfinite(grad)
    assert all(p.grad is None and not p.requires_grad for p in model.lm.parameters())
    assert inputs['inputs_embeds'].shape[:2] == labels.shape == inputs['attention_mask'].shape
    assert all(p.dtype == torch.float32 for p in model.connector.parameters())
    model.zero_grad(set_to_none=True)
    write(root/'prepared'/'interface_check.json', dict(feature_shape=list(features.shape), connector_gradient_norm=grad,
        loss=loss.item(), backbone_frozen=True, matching_masks=True, trainable_fp32=True,
        policy='Autograd enabled through frozen Qwen; supervised-position projection; per-example mean loss.'))


def train(root, cfg, model, store, manifest, progress, timing=False):
    from .plots import build_evidence
    checkpoint_dir = root/'checkpoints'
    checkpoints = sorted(checkpoint_dir.glob('update_*.pt')) if checkpoint_dir.exists() else []
    saved = torch.load(checkpoints[-1], map_location='cpu', weights_only=False) if checkpoints else None
    sampler = Sampler(manifest, cfg['seed'])
    current, resume_stage, resume_local = 0, 1, 0
    resources = {}
    if saved:
        assert saved['config'] == cfg
        if saved['has_lora']:
            model.enable_lora()
        model.load_trainable(saved['weights'])
        model.visual_scale.copy_(saved['visual_scale'].cuda())
        sampler.load_state_dict(saved['sampler'])
        current, resume_stage, resume_local = saved['update'], saved['stage'], saved['local']
        resources = saved['resources']
    else:
        calibration = model.calibrate(manifest['train']['captions'][:64], store)
        write(root/'prepared'/'calibration.json', calibration)
        state = rng_state()
        check_interface(model, store, manifest, root)
        restore_rng(state)
    log = root/'training.jsonl'
    if log.exists():
        history = rows(log)
        orphan = [r for r in history if r['update'] > current]
        if orphan:
            write(root/f'interrupted_after_{current:04d}_{int(time.time())}.json', orphan)
        log.write_text(''.join(__import__('json').dumps(r)+'\n' for r in history if r['update'] <= current), encoding='utf-8')
    if not timing and (current == 0 or current % cfg['dev_every'] == 0 or current in np.cumsum(cfg['stage_updates'])):
        state = rng_state()
        evaluate_dev(model, store, manifest, cfg, root, current, progress)
        restore_rng(state)
        build_evidence(root)
    for stage in range(resume_stage, 4):
        if stage > 1:
            model.enable_lora()
        optimizer = optimizer_for(model, cfg, stage)
        scaler = torch.amp.GradScaler('cuda')
        local_start = resume_local if stage == resume_stage else 0
        if saved and stage == resume_stage:
            optimizer.load_state_dict(saved['optimizer'])
            scaler.load_state_dict(saved['scaler'])
            restore_rng(saved['rng'])
        saved = None
        total = cfg['stage_updates'][stage-1]
        params = [p for p in model.parameters() if p.requires_grad]
        counts = model.parameter_counts()
        resource = resources.setdefault(str(stage), dict(training_seconds=0., updates=0, peak_gpu_bytes=0, **counts))
        torch.cuda.reset_peak_memory_stats()
        progress.emit(f'stage {stage} training', local_start, total, global_update=current)
        for local in range(local_start+1, total+1):
            torch.cuda.synchronize()
            start = time.perf_counter()
            batch, mixture = sampler.batch(stage, cfg['microbatch']*cfg['accumulation'])
            factor = lr_factor(local, total, cfg['warmup_fraction'], cfg['lr_floor'])
            for group, peak in zip(optimizer.param_groups, [cfg['connector_lr'][stage-1], cfg['lora_lr'][stage-1]]):
                group['lr'] = peak*factor
            model.train()
            optimizer.zero_grad(set_to_none=True)
            value = 0.
            for first in range(0, len(batch), cfg['microbatch']):
                micro = batch[first:first+cfg['microbatch']]
                features = store.batch(micro)
                with torch.autocast('cuda', dtype=torch.float16):
                    loss = model.losses(micro, features).mean()/cfg['accumulation']
                scaler.scale(loss).backward()
                value += loss.detach().float().item()
            scaler.unscale_(optimizer)
            grad = torch.nn.utils.clip_grad_norm_(params, cfg['clip_norm'])
            scale_before = scaler.get_scale()
            scaler.step(optimizer)
            scaler.update()
            skipped = scaler.get_scale() < scale_before
            if not math.isfinite(value):
                raise FloatingPointError('Non-finite loss; stop and inspect instead of wasting updates')
            current += 1
            torch.cuda.synchronize()
            seconds = time.perf_counter()-start
            peak = torch.cuda.max_memory_allocated()
            resource['training_seconds'] += seconds
            resource['updates'] += 1
            resource['peak_gpu_bytes'] = max(resource['peak_gpu_bytes'], peak)
            jsonl(log, dict(update=current, stage=stage, stage_update=local, loss=value, grad_norm=float(grad),
                lr_connector=optimizer.param_groups[0]['lr'], lr_lora=optimizer.param_groups[1]['lr'] if stage > 1 else 0,
                seconds=seconds, examples_per_second=len(batch)/seconds, peak_gpu_bytes=peak,
                allocated_gpu_bytes=torch.cuda.memory_allocated(), reserved_gpu_bytes=torch.cuda.memory_reserved(),
                amp_scale=scaler.get_scale(), skipped=skipped, mixture=mixture))
            progress.emit(f'stage {stage} training', local, total, global_update=current, loss=round(value, 4), examples_per_second=round(len(batch)/seconds, 2), gpu_GB=round(peak/2**30, 2))
            if current % cfg['checkpoint_every'] == 0 or local == total:
                save_checkpoint(checkpoint_dir/f'update_{current:04d}.pt', model, optimizer, scaler, sampler, stage, local, current, cfg, resources)
                progress.emit(checkpoint=f'update_{current:04d}.pt')
            if local == total:
                dest = root/'exports'/f'stage_{stage}'
                dest.mkdir(parents=True, exist_ok=True)
                torch.save(dict(connector=model.connector.state_dict(), visual_scale=model.visual_scale.cpu(), config=cfg), dest/'connector.pt')
                if model.has_lora:
                    model.lm.save_pretrained(dest/'adapter')
                model.tokenizer.save_pretrained(dest/'tokenizer')
            if not timing and (current % cfg['dev_every'] == 0 or local == total):
                state = rng_state()
                evaluate_dev(model, store, manifest, cfg, root, current, progress)
                restore_rng(state)
                build_evidence(root)
            if current % 50 == 0 or local == total:
                write(root/'resources.json', resources)
                build_evidence(root, live=True)
        # Re-create stage exports even when recovering a checkpoint taken immediately
        # before its endpoint export (the training loop can be empty on resume).
        dest = root/'exports'/f'stage_{stage}'
        dest.mkdir(parents=True, exist_ok=True)
        torch.save(dict(connector=model.connector.state_dict(), visual_scale=model.visual_scale.detach().cpu(), config=cfg), dest/'connector.pt')
        if model.has_lora:
            model.lm.save_pretrained(dest/'adapter')
        model.tokenizer.save_pretrained(dest/'tokenizer')
        del optimizer
    write(root/'resources.json', resources)
    if not timing:
        evaluate_final(model, store, manifest, cfg, root, progress)
    final_rows = rows(root/'evaluations'/'final_examples.jsonl')
    dev_rows = [read(p) for p in (root/'evaluations').glob('dev_*.json') if p.stem[4:].isdigit()]
    feature_cost = read(root/'prepared'/'features'/'complete.json')
    write(root/'cost_summary.json', dict(
        training_seconds=sum(r['training_seconds'] for r in resources.values()),
        development_seconds=sum(r['seconds'] for r in dev_rows),
        final_generation_seconds=sum(r['generation_seconds'] for r in final_rows),
        final_reference_nll_seconds=sum(r.get('nll_seconds', 0.) for r in final_rows),
        final_peak_gpu_bytes=max((r['peak_gpu_bytes'] for r in final_rows), default=0),
        feature_cache_seconds=feature_cost['seconds'], feature_cache_peak_gpu_bytes=feature_cost['peak_gpu_bytes'],
        note='Component times exclude downloads/model load/saves/plots. run_sessions.jsonl records wall time including overhead and failed sessions.'))
    build_evidence(root)
