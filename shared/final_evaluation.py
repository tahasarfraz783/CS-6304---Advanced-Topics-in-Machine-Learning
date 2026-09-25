"""Task 2 final analysis only: target labels must not feed back into training."""
import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
import torch
from torch.utils.data import DataLoader, Dataset
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .pacs import SOURCES, CLASSES, SEED, image_transform, split_hash
from .source_erm import make_model
from .dan import forward_features


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class EvaluationImages(Dataset):
    def __init__(self, root, records):
        self.root, self.records = Path(root), records
        self.transform = image_transform(False)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        r = self.records[index]
        with Image.open(self.root / r['path']) as im:
            return self.transform(im.convert('RGB')), r['label']


@torch.no_grad()
def extract(model, root, records, device):
    loader = DataLoader(EvaluationImages(root, records), batch_size=64, shuffle=False, num_workers=0)
    features, logits = [], []
    for images, _ in loader:
        f = forward_features(model, images.to(device))
        z = model.fc(f)
        if not torch.isfinite(f).all() or not torch.isfinite(z).all():
            raise RuntimeError('Non-finite evaluation features/logits; inspect the training run.')
        features.append(f.cpu().numpy()); logits.append(z.cpu().numpy())
    return np.concatenate(features), np.concatenate(logits)


def final_evaluation(data_root, split_path, runs, output_dir, *, decisions_locked=False):
    """runs maps display names to completed run directories, including Step 6.

    The user must fix every method/setting/checkpoint before setting the flag.
    Logistic regression uses train-only standardization, C=1, class_weight=balanced,
    and a shared domain-stratified 70/30 split. Target object labels are not used
    to choose the probe subset or split. Features are unnormalized 512-D vectors.
    """
    if not decisions_locked:
        raise RuntimeError('Fix all Task 2 settings/checkpoints, including Step 6, before target evaluation.')
    required = {'Source-only', 'DAN', 'DANN', 'CDAN'}
    if not required.issubset(runs):
        raise ValueError('Provide completed Source-only, DAN, DANN, and CDAN runs.')
    root, out = Path(data_root), Path(output_dir)
    splits = json.loads(Path(split_path).read_text(encoding='utf-8'))
    checkpoints, metadata = {}, {}
    for name, folder in runs.items():
        folder = Path(folder)
        if not (folder / 'completion.json').exists():
            raise FileNotFoundError(f'{name} is not a completed run: {folder}')
        info = json.loads((folder / 'config.json').read_text())
        if info['split_sha256'] != split_hash(split_path) or info['class_to_idx'] != splits['class_to_idx']:
            raise ValueError(f'{name} uses a different split or class mapping.')
        checkpoints[name] = folder / 'best.pt'
        metadata[name] = dict(checkpoint_sha256=file_hash(checkpoints[name]), config=info['config'],
                              completion=json.loads((folder / 'completion.json').read_text()))
    out.mkdir(parents=True, exist_ok=True)
    lock = dict(seed=SEED, split_sha256=split_hash(split_path), runs=metadata,
                probe=dict(C=1.0, class_weight='balanced', train_fraction=0.7,
                           scaling='StandardScaler fit on probe training only', max_iter=5000))
    lock_path = out / 'evaluation_lock.json'
    if lock_path.exists() and json.loads(lock_path.read_text()) != lock:
        raise ValueError('Checkpoints/settings differ from the saved evaluation lock; preserve the original analysis.')
    lock_path.write_text(json.dumps(lock, indent=2), encoding='utf-8')

    source = [dict(r, domain=d) for d in SOURCES for r in splits['domains'][d]['val']]
    target, rejected = [], []
    if not (root / 'sketch').is_dir():
        raise FileNotFoundError('Missing Sketch directory.')
    actual_classes = sorted(p.name for p in (root / 'sketch').iterdir() if p.is_dir() and not p.name.startswith('.'))
    if actual_classes != list(CLASSES):
        raise ValueError('Sketch class folders do not match the source class mapping.')
    for label, name in enumerate(CLASSES):
        for path in sorted((root / 'sketch' / name).rglob('*')):
            if not path.is_file() or path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.bmp'}:
                continue
            relative = path.relative_to(root).as_posix()
            try:
                with Image.open(path) as im:
                    im.convert('RGB').load()
            except (OSError, ValueError) as exc:
                rejected.append(dict(path=relative, reason=str(exc)))
                continue
            target.append(dict(path=relative, label=label, domain='sketch'))
    if not target or any(not any(r['label'] == k for r in target) for k in range(7)):
        raise ValueError('Every target class must have decodable images.')
    # Compare image identities, not target labels, to the adaptation manifests.
    target_paths = {r['path'] for r in target}
    for name, folder in runs.items():
        manifest = Path(folder) / 'target_manifest.json'
        if name != 'Source-only':
            if not manifest.exists():
                raise FileNotFoundError(f'Missing adaptation manifest for {name}')
            if set(json.loads(manifest.read_text())['accepted']) != target_paths:
                raise ValueError(f'{name} adaptation and final target image sets differ.')
    records = source + target
    inventory = [dict(r, bytes=(root / r['path']).stat().st_size,
                      mtime_ns=(root / r['path']).stat().st_mtime_ns) for r in records]
    inventory_path = out / 'image_manifest.json'
    if inventory_path.exists() and json.loads(inventory_path.read_text()) != inventory:
        raise ValueError('Evaluation image inventory changed since the saved analysis.')
    inventory_path.write_text(json.dumps(inventory, indent=2))
    (out / 'rejected_target_images.json').write_text(json.dumps(rejected, indent=2))
    print(f'Evaluation: {len(source)} source-validation, {len(target)} target images; {len(rejected)} target decoding failures.')

    rng = np.random.default_rng(SEED)
    n = min(len(source), len(target))
    # Equal total source and target counts, with pooled source-validation sampling.
    source_ids = rng.choice(len(source), n, replace=False)
    target_ids = len(source) + rng.choice(len(target), n, replace=False)
    probe_ids = np.concatenate((source_ids, target_ids))
    domain_labels = np.concatenate((np.zeros(n, dtype=int), np.ones(n, dtype=int)))
    train_ids, test_ids = train_test_split(np.arange(2*n), test_size=0.3,
                                         random_state=SEED, stratify=domain_labels)
    pd.DataFrame([dict(path=records[int(index)]['path'], domain_label=int(domain_labels[i]),
                       split='train' if i in set(train_ids) else 'test')
                  for i, index in enumerate(probe_ids)]).to_csv(out / 'probe_split.csv', index=False)
    truth = np.array([r['label'] for r in records])
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    cache = out / 'features'; cache.mkdir(exist_ok=True)
    rows, class_rows, predictions, confusion_rows = [], [], [], []
    for number, (name, checkpoint) in enumerate(checkpoints.items()):
        print(f'Evaluating {name}...', flush=True)
        signature = hashlib.sha256((metadata[name]['checkpoint_sha256'] + file_hash(inventory_path)
                                    + 'resize256-center224-imagenet-v1').encode()).hexdigest()
        feature_path = cache / f'{signature}.npz'
        if feature_path.exists():
            with np.load(feature_path) as saved:
                features, logits = saved['features'], saved['logits']
        else:
            saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
            if saved['split_sha256'] != lock['split_sha256'] or saved['class_to_idx'] != splits['class_to_idx']:
                raise ValueError(f'{name} checkpoint metadata mismatch.')
            if saved['epoch'] != metadata[name]['completion']['best_epoch']:
                raise ValueError(f'{name} checkpoint epoch mismatch.')
            model = make_model(pretrained=False).to(device)
            model.load_state_dict(saved['model_state']); model.eval(); model.requires_grad_(False)
            features, logits = extract(model, root, records, device)
            np.savez_compressed(feature_path, features=features, logits=logits)
            del model, saved
        pred = logits.argmax(axis=1)
        result = dict(method=name)
        source_acc, source_f1 = [], []
        for d in SOURCES:
            ids = np.array([i for i, r in enumerate(source) if r['domain'] == d])
            acc = accuracy_score(truth[ids], pred[ids])
            f1 = f1_score(truth[ids], pred[ids], labels=range(7), average='macro', zero_division=0)
            result[f'{d}_accuracy'], result[f'{d}_macro_f1'] = acc, f1
            source_acc.append(acc); source_f1.append(f1)
        t = slice(len(source), None)
        result.update(mean_source_accuracy=np.mean(source_acc), mean_source_macro_f1=np.mean(source_f1),
                      target_accuracy=accuracy_score(truth[t], pred[t]),
                      target_macro_f1=f1_score(truth[t], pred[t], labels=range(7), average='macro', zero_division=0))
        probe = make_pipeline(StandardScaler(), LogisticRegression(C=1, class_weight='balanced',
                                                                   max_iter=5000, random_state=SEED))
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            probe.fit(features[probe_ids[train_ids]], domain_labels[train_ids])
        result['domain_separability'] = accuracy_score(domain_labels[test_ids], probe.predict(features[probe_ids[test_ids]]))
        result['probe_train_count'], result['probe_test_count'] = len(train_ids), len(test_ids)
        rows.append(result)
        cm = confusion_matrix(truth[t], pred[t], labels=range(7))
        for k, c in enumerate(CLASSES):
            wrong = cm[k].copy(); wrong[k] = 0
            class_rows.append(dict(method=name, class_name=c, count=int(cm[k].sum()),
                                   accuracy=float(cm[k,k]/cm[k].sum()),
                                   dominant_confusion=CLASSES[int(wrong.argmax())] if wrong.sum() else '',
                                   dominant_confusion_count=int(wrong.max())))
            for j, predicted_class in enumerate(CLASSES):
                confusion_rows.append(dict(method=name, true_class=c, predicted_class=predicted_class, count=int(cm[k,j])))
        predictions.extend(dict(method=name, path=r['path'], label=r['label'],
                                predicted_label=int(p), correct=bool(r['label']==p))
                           for r, p in zip(target, pred[t]))
    summary, per_class = pd.DataFrame(rows), pd.DataFrame(class_rows)
    baseline = summary.loc[summary.method=='Source-only', 'target_accuracy'].iloc[0]
    summary['target_accuracy_change_pp'] = 100*(summary.target_accuracy-baseline)
    base_class = per_class[per_class.method=='Source-only'].set_index('class_name').accuracy
    per_class['accuracy_change_pp'] = 100*(per_class.accuracy-per_class.class_name.map(base_class))
    prediction_table = pd.DataFrame(predictions)
    base_pred = prediction_table[prediction_table.method=='Source-only'].set_index('path')
    prediction_table['baseline_correct'] = prediction_table.path.map(base_pred.correct)
    prediction_table['baseline_prediction'] = prediction_table.path.map(base_pred.predicted_label)
    changes = []
    for name in runs:
        if name == 'Source-only':
            continue
        subset = per_class[per_class.method==name]
        for kind, idx in [('largest_change', subset.accuracy_change_pp.idxmax()),
                          ('smallest_change', subset.accuracy_change_pp.idxmin())]:
            row = subset.loc[idx].to_dict(); row['selection'] = kind; changes.append(row)
    # Deterministic examples: up to 3 corrections/regressions for each method/class.
    cases = prediction_table[prediction_table.correct != prediction_table.baseline_correct].copy()
    cases['class_name'] = cases.label.map(dict(enumerate(CLASSES)))
    cases['change'] = np.where(cases.correct, 'corrected', 'introduced_error')
    cases = cases.groupby(['method','class_name','change'], sort=False).head(3)
    for filename, table in [('comparison.csv',summary), ('per_class.csv',per_class),
                             ('target_predictions.csv',prediction_table), ('confusions.csv',pd.DataFrame(confusion_rows)),
                             ('largest_class_changes.csv',pd.DataFrame(changes)), ('selected_cases.csv',cases)]:
        table.to_csv(out / filename, index=False)
    return summary, per_class, cases
