"""Task 3 ERM checkpoint reuse and source-only validation."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import torch
from torch.utils.data import DataLoader

from .pacs import CLASSES, SOURCES, SEED, PACSSource, split_hash
from .source_erm import CONFIG, evaluate, make_model, seed_everything


def evaluate_erm(root):
    root = Path(root)
    checkpoint = root / 'Task 2/results/source_only/best.pt'
    split_path = root / 'shared/splits/pacs_sketch_seed6304.json'
    # Read the immutable Task 2 split; never generate a replacement.
    splits = json.loads(split_path.read_text(encoding='utf-8'))
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    expected_classes = {name: i for i, name in enumerate(CLASSES)}
    if saved['split_sha256'] != split_hash(split_path):
        raise ValueError('Checkpoint and source split hashes differ.')
    if saved['class_to_idx'] != expected_classes or splits['class_to_idx'] != expected_classes:
        raise ValueError('Unexpected class mapping.')
    if splits['seed'] != SEED or set(splits['domains']) != set(SOURCES):
        raise ValueError('Unexpected source split protocol.')
    if saved.get('method', 'source_only') != 'source_only':
        raise ValueError('Expected the Task 2 source-only checkpoint.')
    if any(saved['config'].get(key) != value for key, value in CONFIG.items()):
        raise ValueError('Checkpoint configuration differs from the shared ERM protocol.')
    for domain in SOURCES:
        for record in splits['domains'][domain]['val']:
            path = Path(record['path'])
            if path.is_absolute() or '..' in path.parts or path.parts[0] != domain:
                raise ValueError('Invalid source validation path.')
    seed_everything(SEED)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    # No ImageNet download or training: every parameter comes from best.pt.
    model = make_model(pretrained=False).to(device)
    model.load_state_dict(saved['model_state'], strict=True)
    loaders = {domain: DataLoader(
        PACSSource(root / 'data/PACS', splits['domains'][domain]['val']),
        batch_size=64, shuffle=False, num_workers=0) for domain in SOURCES}
    metrics, predictions = evaluate(model, loaders, device)
    summary = metrics[['domain', 'accuracy', 'macro_f1']].copy()
    summary = pd.concat([summary, pd.DataFrame([
        dict(domain='mean_source', accuracy=metrics.accuracy.mean(), macro_f1=metrics.macro_f1.mean()),
        dict(domain='worst_source', accuracy=metrics.accuracy.min(), macro_f1=metrics.macro_f1.min()),
    ])], ignore_index=True)
    out = root / 'Task 3/results/erm'
    out.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out / 'source_validation.csv', index=False)
    predictions.to_csv(out / 'source_validation_predictions.csv', index=False)
    summary.to_csv(out / 'source_validation_summary.csv', index=False)
    provenance = dict(
        checkpoint=str(checkpoint.relative_to(root)),
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        split_sha256=split_hash(split_path), best_epoch=saved['epoch'],
        selected_mean_source_macro_f1=saved['best_source_macro_f1'],
        recomputed_mean_source_macro_f1=float(metrics.macro_f1.mean()),
        config=saved['config'], device=str(device), torch_version=str(torch.__version__),
        worst_accuracy_domain=metrics.loc[metrics.accuracy.idxmin(), 'domain'],
        worst_macro_f1_domain=metrics.loc[metrics.macro_f1.idxmin(), 'domain'],
        retrained=False, sketch_loaded=False)
    (out / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return summary, provenance
