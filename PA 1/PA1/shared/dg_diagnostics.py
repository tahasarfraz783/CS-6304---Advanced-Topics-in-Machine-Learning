"""Task 3 source-only metrics, domain probe, and common local sharpness."""
import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .pacs import SOURCES, CLASSES, SEED, PACSSource, split_hash
from .source_erm import make_model, seed_everything
from .dan import forward_features


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runs(root):
    root = Path(root)
    return {'ERM': root / 'Task 2/results/source_only',
            'DAN-DG': root / 'Task 3/results/dan_dg',
            'SAM': root / 'Task 3/results/sam',
            'DAN-DG lambda=0.1': root / 'Task 3/results/dan_dg_lambda_0p1',
            'DAN-DG lambda=10': root / 'Task 3/results/dan_dg_lambda_10'}


def freeze_protocol(root):
    root = Path(root)
    split = root / 'shared/splits/pacs_sketch_seed6304.json'
    source = json.loads(split.read_text())
    mapping = {c: i for i, c in enumerate(CLASSES)}
    if source['class_to_idx'] != mapping or set(source['domains']) != set(SOURCES):
        raise ValueError('Unexpected split protocol.')
    metadata = {}
    base = json.loads((runs(root)['ERM'] / 'config.json').read_text())['config']
    for name, folder in runs(root).items():
        completion = json.loads((folder / 'completion.json').read_text())
        saved = torch.load(folder / 'best.pt', map_location='cpu', weights_only=True)
        if saved['split_sha256'] != split_hash(split) or saved['class_to_idx'] != mapping:
            raise ValueError(f'{name}: split/class mismatch.')
        if any(saved['config'].get(k) != v for k, v in base.items()):
            raise ValueError(f'{name}: shared configuration mismatch.')
        expected_method = 'source_only' if name == 'ERM' else ('sam' if name == 'SAM' else 'dan_dg')
        if saved.get('method', 'source_only') != expected_method:
            raise ValueError(f'{name}: unexpected method.')
        if name.startswith('DAN-DG'):
            expected = {'DAN-DG': 1.0, 'DAN-DG lambda=0.1': 0.1, 'DAN-DG lambda=10': 10.0}[name]
            if saved['config']['lambda_dg'] != expected or saved['config']['kernel_scales'] != [0.5, 1.0, 2.0]:
                raise ValueError('Unexpected controlled setting.')
        if name == 'SAM' and (saved['config']['rho'] != 0.05 or saved['config']['adaptive']):
            raise ValueError('Unexpected SAM setting.')
        if saved['epoch'] != completion['best_epoch']:
            raise ValueError('Checkpoint selection metadata mismatch.')
        metadata[name] = dict(checkpoint=str((folder / 'best.pt').relative_to(root)),
                              sha256=file_hash(folder / 'best.pt'), config=saved['config'], completion=completion)
        del saved
    plan = root / 'Task 3/results/controlled_study/pre_analysis_plan.json'
    lock = dict(seed=SEED, split_sha256=split_hash(split), runs=metadata, study_plan_sha256=file_hash(plan),
                probe=dict(C=1.0, solver='lbfgs', objective='multinomial', max_iter=5000,
                           scaling='StandardScaler fit only on probe training features',
                           split='domain-stratified 70/30', subset='equal count per source'),
                sharpness=dict(radius=0.05, count_per_source=32, mode='eval', norm='global L2',
                               objective='cross-entropy', perturbations=1))
    out = root / 'Task 3/results/final_evaluation'
    out.mkdir(parents=True, exist_ok=True)
    write_lock(out / 'evaluation_lock.json', lock)
    return lock


def write_lock(path, value):
    if path.exists() and json.loads(path.read_text()) != value:
        raise ValueError(f'Locked protocol or inventory changed: {path}')
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def load_model(checkpoint, device):
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    model = make_model(pretrained=False).to(device)
    model.load_state_dict(saved['model_state'], strict=True)
    model.eval()
    return model


@torch.no_grad()
def source_features(model, root, records, device):
    loader = DataLoader(PACSSource(root, records), batch_size=64, shuffle=False, num_workers=0)
    features, logits = [], []
    for x, _ in loader:
        f = forward_features(model, x.to(device))
        features.append(f.cpu().numpy())
        logits.append(model.fc(f).cpu().numpy())
    features, logits = np.concatenate(features), np.concatenate(logits)
    if not np.isfinite(features).all() or not np.isfinite(logits).all():
        raise RuntimeError('Non-finite source features/logits.')
    return features, logits


def sharpness(model, x, y, radius=0.05):
    """One global gradient-ascent perturbation; restore every parameter exactly."""
    model.eval()
    parameters = [p for p in model.parameters() if p.requires_grad]
    clean = nn.functional.cross_entropy(model(x), y)
    grads = torch.autograd.grad(clean, parameters)
    norm = torch.stack([g.norm(2) for g in grads]).norm(2)
    if not torch.isfinite(norm) or not torch.isfinite(clean):
        raise RuntimeError('Non-finite sharpness gradient/loss.')
    originals = [p.detach().clone() for p in parameters]
    try:
        with torch.no_grad():
            for p, g in zip(parameters, grads):
                p.add_(radius * g / norm.clamp_min(1e-12))
            perturbed = nn.functional.cross_entropy(model(x), y)
    finally:
        with torch.no_grad():
            for p, original in zip(parameters, originals):
                p.copy_(original)
    if not torch.isfinite(perturbed):
        raise RuntimeError('Non-finite perturbed sharpness loss.')
    return dict(sharpness=float(perturbed-clean.detach()), sharpness_clean_loss=float(clean.detach()),
                sharpness_perturbed_loss=float(perturbed), sharpness_gradient_norm=float(norm))


def source_diagnostics(root):
    root = Path(root)
    seed_everything(SEED)
    lock = freeze_protocol(root)
    out = root / 'Task 3/results/final_evaluation'
    splits = json.loads((root / 'shared/splits/pacs_sketch_seed6304.json').read_text())
    records = [dict(r, domain=d) for d in SOURCES for r in splits['domains'][d]['val']]
    inventory = [dict(r, sha256=file_hash(root / 'data/PACS' / r['path'])) for r in records]
    write_lock(out / 'source_inventory.json', inventory)
    rng = np.random.default_rng(SEED)
    count = min(sum(r['domain'] == d for r in records) for d in SOURCES)
    probe_ids = np.concatenate([rng.choice([i for i,r in enumerate(records) if r['domain']==d], count, replace=False)
                                for d in SOURCES])
    labels = np.repeat(np.arange(3), count)
    train, test = train_test_split(np.arange(len(probe_ids)), test_size=0.3, random_state=SEED, stratify=labels)
    train_set = set(train)
    pd.DataFrame([dict(path=records[int(i)]['path'], domain=records[int(i)]['domain'],
                       domain_label=int(labels[j]), split='train' if j in train_set else 'test')
                  for j,i in enumerate(probe_ids)]).to_csv(out / 'source_probe_split.csv', index=False)
    rng = np.random.default_rng(SEED)
    sharp_ids = np.concatenate([rng.choice([i for i,r in enumerate(records) if r['domain']==d],32,replace=False)
                                for d in SOURCES])
    sharp_records = [records[int(i)] for i in sharp_ids]
    write_lock(out / 'sharpness_batch.json', sharp_records)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    x,y = next(iter(DataLoader(PACSSource(root / 'data/PACS', sharp_records), batch_size=96, shuffle=False)))
    x,y = x.to(device),y.to(device)
    rows = []
    for name,folder in runs(root).items():
        print(f'Source diagnostics: {name}', flush=True)
        model = load_model(folder / 'best.pt', device)
        features, logits = source_features(model, root / 'data/PACS', records, device)
        truth = np.array([r['label'] for r in records]); pred = logits.argmax(1)
        result = dict(method=name)
        accs,f1s=[],[]
        for d in SOURCES:
            ids = np.array([r['domain']==d for r in records])
            acc=accuracy_score(truth[ids],pred[ids]); f1=f1_score(truth[ids],pred[ids],labels=range(7),average='macro',zero_division=0)
            result[f'{d}_accuracy']=acc; result[f'{d}_macro_f1']=f1
            accs.append(acc); f1s.append(f1)
        result.update(mean_source_accuracy=np.mean(accs), mean_source_macro_f1=np.mean(f1s),
                      worst_source_accuracy=min(accs), worst_source_macro_f1=min(f1s))
        probe = make_pipeline(StandardScaler(), LogisticRegression(C=1, solver='lbfgs', max_iter=5000, random_state=SEED))
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            probe.fit(features[probe_ids[train]], labels[train])
        result.update(source_domain_separability=accuracy_score(labels[test],probe.predict(features[probe_ids[test]])),
                      probe_train_count=len(train),probe_test_count=len(test),probe_per_domain=count)
        result.update(sharpness(model,x,y))
        rows.append(result)
        pd.DataFrame(rows).to_csv(out / 'source_diagnostics.csv', index=False)
        del model
    return pd.DataFrame(rows)
