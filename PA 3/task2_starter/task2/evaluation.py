import time
import torch
from .common import rows, jsonl, write, repair_jsonl
from .scoring import normalize, vqa_score, summarize


def evaluate_dev(model, store, manifest, cfg, root, update, progress):
    dest = root/'evaluations'/f'dev_{update:04d}.json'
    if dest.exists():
        return
    start = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    model.eval()
    result = dict(update=update)
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
        for suite in ['captions', 'grounding', 'natural']:
            examples = manifest['dev'][suite]
            if suite != 'captions':
                examples = [r for pair in examples for r in pair]
            for condition in (['correct'] if suite == 'captions' else ['correct', 'swap', 'none']):
                losses = []
                progress.emit(f'dev {update} {suite} {condition}', 0, len(examples))
                for first in range(0, len(examples), cfg['likelihood_batch']):
                    batch = examples[first:first+cfg['likelihood_batch']]
                    features = None if condition == 'none' else store.batch(batch, condition)
                    nll = model.losses(batch, features, condition, include_end=suite == 'captions')
                    losses.extend(nll.float().cpu().tolist())
                    progress.emit(completed=len(losses))
                result[suite+'_'+condition+'_nll'] = sum(losses)/len(losses)
                # Per-example NLL is retained for auditing, not just the average.
                write(root/'evaluations'/f'dev_{update:04d}_{suite}_{condition}.json',
                      [dict(id=r['id'], image_id=r['image_id'], target=r['target'], nll=v) for r, v in zip(examples, losses)])
            if suite != 'captions':
                result[suite+'_swap_penalty'] = result[suite+'_swap_nll']-result[suite+'_correct_nll']
    result['seconds'] = time.perf_counter()-start
    result['peak_gpu_bytes'] = torch.cuda.max_memory_allocated()
    write(dest, result)


def evaluate_final(model, store, manifest, cfg, root, progress):
    path = root/'evaluations'/'final_examples.jsonl'
    repair_jsonl(path)
    from .common import read
    recovered = [r for p in sorted((root/'evaluations'/'batches').glob('*.json')) for r in read(p)]
    saved = {(r['suite'], r['condition'], r['id']): r for r in recovered}
    model.eval()
    for suite in ['grounding', 'natural']:
        examples = [r for p in manifest['test'][suite] for r in p]
        mismatch = manifest['mismatches'][suite]
        for condition in ['correct', 'swap', 'mismatched', 'none']:
            progress.emit(f'final {suite} {condition}', 0, len(examples))
            torch.cuda.reset_peak_memory_stats()
            for first in range(0, len(examples), cfg['generation_batch']):
                batch = examples[first:first+cfg['generation_batch']]
                missing = [r for r in batch if (suite, condition, r['id']) not in saved]
                if missing:
                    # Cache resumes at completed batch boundaries, preserving prescribed batches.
                    if len(missing) != len(batch):
                        raise RuntimeError('Partial generation batch; restore batch JSONL or use a new output')
                    features = None if condition == 'none' else store.batch(batch, condition, mismatch)
                    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
                        torch.cuda.synchronize()
                        begin = time.perf_counter()
                        predictions = model.generate(batch, features, condition)
                        torch.cuda.synchronize()
                        seconds = (time.perf_counter()-begin)/len(batch)
                        nll_start = time.perf_counter()
                        nlls = model.losses(batch, features, condition, include_end=False).float().cpu().tolist()
                        nll_seconds = (time.perf_counter()-nll_start)/len(batch)
                    completed = []
                    for r, pred, nll in zip(batch, predictions, nlls):
                        row = dict(r, prediction=pred, condition=condition, nll=nll,
                            input_image_id=(None if condition == 'none' else r['partner_image_id'] if condition == 'swap' else mismatch[r['id']] if condition == 'mismatched' else r['image_id']),
                            generation_seconds=seconds, nll_seconds=nll_seconds, peak_gpu_bytes=torch.cuda.max_memory_allocated(),
                            exact=normalize(pred) == r['canonical'], partner_match=normalize(pred) == r['partner_canonical'],
                            score=vqa_score(pred, r['answers']) if suite == 'natural' else float(normalize(pred) == r['canonical']))
                        completed.append(row)
                    # Atomic per-batch file is the recovery authority; JSONL rebuilt below.
                    batchfile = root/'evaluations'/'batches'/f'{suite}_{condition}_{first:04d}.json'
                    write(batchfile, completed)
                    for row in completed:
                        saved[(suite, condition, row['id'])] = row
                progress.emit(completed=first+len(batch))
            from .common import read
            allrows = [r for f in sorted((root/'evaluations'/'batches').glob('*.json')) for r in read(f)]
            path.write_text(''.join(__import__('json').dumps(r, ensure_ascii=False)+'\n' for r in allrows), encoding='utf-8')
    final = rows(path)
    write(root/'evaluations'/'final_summary.json', summarize(final, cfg['bootstrap_resamples'], cfg['seed']))
