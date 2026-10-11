"""Explicit follow-up recipes; originals and their evaluation locks are preserved."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .source_erm import CONFIG, train_pacs, make_model, evaluate
from .pacs import CLASSES, SOURCES, PACSSource, split_hash
from .final_evaluation import file_hash, extract

RECIPES = {
    'dann': (2, 'dann', {'max_grl_strength': 0.1}),
    'cdan': (2, 'cdan', {'max_grl_strength': 0.1}),
    'dan_lambda_10': (2, 'dan', {'lambda_mmd': 10.0}),
    'dan_dg': (3, 'dan_dg', {'lambda_dg': 1.0}),
    'dan_dg_lambda_10': (3, 'dan_dg', {'lambda_dg': 10.0}),
}
OLD_NAMES = {'dann': 'DANN', 'cdan': 'CDAN', 'dan_lambda_10': 'DAN lambda=10',
             'dan_dg': 'DAN-DG', 'dan_dg_lambda_10': 'DAN-DG lambda=10'}


def recipe(root, run):
    root = Path(root).resolve()
    task, method, settings = RECIPES[run]
    cfg = dict(CONFIG)
    cfg.update(epochs=20, patience=8, learning_rate=1e-5,
               backbone_learning_rate=1e-6 if settings.get('lambda_mmd', settings.get('lambda_dg')) == 10 else 1e-5,
               discriminator_learning_rate=1e-5, gradient_clip_norm=1.0,
               alignment_ramp_epochs=5, selection_start_epoch=5,
               freeze_batchnorm_affine=True,
               batchnorm='frozen_pretrained_running_stats_and_affine',
               initial_checkpoint=str(root / 'Task 2/results/source_only/best.pt'),
               initialization='trained_source_only_checkpoint',
               experiment='recovery_v1_after_inspection_of_original_target_results',
               kernel_scales=[0.5, 1.0, 2.0], target_batch_size=24,
               domain_loss_weight=1.0, max_grl_strength=0.1,
               discriminator_hidden=256, discriminator_dropout=0.5,
               mmd_estimator='biased_including_diagonals')
    cfg.update(settings)
    return method, cfg, root / f'Task {task}/results/recovery_v1' / run


def train_run(root, run):
    """Safe to rerun completed cells. Interrupted folders require a new version."""
    root = Path(root).resolve()
    method, cfg, out = recipe(root, run)
    split = root / 'shared/splits/pacs_sketch_seed6304.json'
    if not split.is_file() or not Path(cfg['initial_checkpoint']).is_file():
        raise FileNotFoundError('The existing source split and source-only checkpoint are required.')
    if out.exists() and any(out.iterdir()):
        if not (out / 'completion.json').is_file():
            raise RuntimeError(f'Interrupted run preserved at {out}. Choose a fresh recovery version before retrying.')
        info = json.loads((out / 'config.json').read_text())
        if info['method'] != method or any(info['config'].get(k) != v for k, v in cfg.items()):
            raise ValueError('Saved recipe differs; use a new recovery version.')
        if info['split_sha256'] != split_hash(split):
            raise ValueError('Source split changed.')
        if info['config']['initial_checkpoint_sha256'] != file_hash(cfg['initial_checkpoint']):
            raise ValueError('Initialization checkpoint changed.')
        print('Loaded completed run:', out)
    else:
        model, _, _ = train_pacs(root / 'data/PACS', split, out, cfg, method)
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    plot_run(out)
    return pd.read_csv(out / 'source_validation.csv')


def plot_run(out):
    import matplotlib.pyplot as plt
    history = pd.read_csv(out / 'history.csv')
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for key in ['classification_loss', 'weighted_mmd_loss', 'domain_loss']:
        if key in history:
            axes[0].plot(history.epoch, history[key], label=key)
    axes[0].set_title('Training losses')
    axes[1].plot(history.epoch, history.mean_val_accuracy, label='Source accuracy')
    axes[1].plot(history.epoch, history.mean_val_macro_f1, label='Source macro-F1')
    axes[1].set_title('Source validation')
    axes[2].plot(history.epoch, history.mean_gradient_norm_before_clip, label='Gradient norm before clipping')
    axes[2].set_title('Gradient diagnostics')
    for ax in axes:
        ax.set_xlabel('Epoch'); ax.legend(); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(out / 'training_curves.png', dpi=150)
    plt.show(); plt.close(fig)


def review_sources(root):
    """No target labels or target accuracy accessed here."""
    rows = []
    for run, (task, _, _) in RECIPES.items():
        _, _, out = recipe(root, run)
        if not (out / 'completion.json').exists():
            rows.append(dict(task=task, run=run, status='not completed'))
            continue
        metrics = pd.read_csv(out / 'source_validation.csv')
        pred = pd.read_csv(out / 'source_validation_predictions.csv')
        counts = pred.prediction.value_counts()
        done = json.loads((out / 'completion.json').read_text())
        rows.append(dict(task=task, run=run, status='completed',
                         source_accuracy=metrics.accuracy.mean(), source_macro_f1=metrics.macro_f1.mean(),
                         predicted_classes=len(counts), dominant_prediction_share=counts.max()/len(pred),
                         collapsed=len(counts) == 1, best_epoch=done['best_epoch']))
    result = pd.DataFrame(rows)
    for task in (2, 3):
        out = Path(root) / f'Task {task}/results/recovery_v1'
        out.mkdir(parents=True, exist_ok=True)
        result[result.task == task].to_csv(out / 'source_review.csv', index=False)
    return result


def evaluate_recovery(root):
    """Lock all five completed runs before computing new source/Sketch accuracies."""
    from torch.utils.data import DataLoader
    root = Path(root).resolve()
    split_path = root / 'shared/splits/pacs_sketch_seed6304.json'
    split = json.loads(split_path.read_text())
    lock = {'experiment': 'follow_up_after_original_target_inspection',
            'split_sha256': split_hash(split_path), 'runs': {}}
    for run, (task, method, _) in RECIPES.items():
        _, cfg, out = recipe(root, run)
        if not (out / 'completion.json').exists():
            raise RuntimeError(f'Complete all five training runs first; missing {run}.')
        info = json.loads((out / 'config.json').read_text())
        if info['method'] != method or info['split_sha256'] != lock['split_sha256'] or info['class_to_idx'] != split['class_to_idx']:
            raise ValueError(f'Provenance mismatch: {run}')
        if any(info['config'].get(k) != v for k, v in cfg.items()):
            raise ValueError(f'Recipe mismatch: {run}')
        lock['runs'][run] = dict(checkpoint_sha256=file_hash(out / 'best.pt'), config=info)
    # Validate both existing locks before writing either one.
    for task in (2, 3):
        dest = root / f'Task {task}/results/recovery_v1/final_evaluation'
        path = dest / 'evaluation_lock.json'
        if path.exists() and json.loads(path.read_text()) != lock:
            raise ValueError('Evaluation already locked to different runs. Use a new version.')
    for task in (2, 3):
        dest = root / f'Task {task}/results/recovery_v1/final_evaluation'
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'evaluation_lock.json').write_text(json.dumps(lock, indent=2))
    # Reuse the exact previously evaluated target inventory, only AFTER locking.
    original = pd.read_csv(root / 'Task 2/results/final_evaluation/target_predictions.csv')
    target = original[original.method == 'Source-only'][['path', 'label']]
    if target.empty or target.path.duplicated().any():
        raise ValueError('Invalid original target inventory.')
    records = target.to_dict('records')
    truth = target.label.to_numpy()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    loaders = {d: DataLoader(PACSSource(root / 'data/PACS', split['domains'][d]['val']),
                            batch_size=64, shuffle=False, num_workers=0) for d in SOURCES}
    rows, predictions, per_class = [], [], []
    for run, (task, method, _) in RECIPES.items():
        _, _, out = recipe(root, run)
        print('Evaluating:', run, flush=True)
        saved = torch.load(out / 'best.pt', map_location='cpu', weights_only=True)
        if saved['method'] != method or saved['config'] != lock['runs'][run]['config']['config']:
            raise ValueError('Checkpoint metadata does not match saved configuration.')
        model = make_model(pretrained=False).to(device)
        model.load_state_dict(saved['model_state']); model.eval()
        metrics, _ = evaluate(model, loaders, device)
        prior = pd.read_csv(out / 'source_validation.csv').set_index('domain')
        if not np.allclose(metrics.set_index('domain').loc[list(SOURCES), 'accuracy'], prior.loc[list(SOURCES), 'accuracy']):
            raise ValueError(f'Source accuracy failed recomputation: {run}')
        _, logits = extract(model, root / 'data/PACS', records, device)
        pred = logits.argmax(1)
        old = pd.read_csv(root / f'Task {task}/results/final_evaluation/comparison.csv')
        old_acc = float(old.loc[old.method == OLD_NAMES[run], 'target_accuracy' if task == 2 else 'sketch_accuracy'].iloc[0])
        acc = float(np.mean(pred == truth))
        counts = np.bincount(pred, minlength=7)
        rows.append(dict(task=task, run=run, old_sketch_accuracy=old_acc, sketch_accuracy=acc,
                         change_pp=100*(acc-old_acc), mean_source_accuracy=metrics.accuracy.mean(),
                         predicted_classes=int((counts > 0).sum()), dominant_prediction_share=float(counts.max()/len(pred)),
                         best_epoch=saved['epoch']))
        predictions.extend(dict(task=task, run=run, path=r['path'], label=r['label'],
                                predicted_label=int(p), correct=bool(p == r['label'])) for r, p in zip(records, pred))
        for i, name in enumerate(CLASSES):
            per_class.append(dict(task=task, run=run, class_name=name,
                                  count=int((truth == i).sum()), accuracy=float(np.mean(pred[truth == i] == i))))
        if file_hash(out / 'best.pt') != lock['runs'][run]['checkpoint_sha256']:
            raise ValueError('Checkpoint changed during evaluation.')
        del model, saved
    result = pd.DataFrame(rows)
    for task in (2, 3):
        dest = root / f'Task {task}/results/recovery_v1/final_evaluation'
        for name, table in [('comparison', result), ('target_predictions', pd.DataFrame(predictions)),
                            ('per_class', pd.DataFrame(per_class))]:
            table[table.task == task].to_csv(dest / f'{name}.csv', index=False)
        (dest / 'verification.json').write_text(json.dumps(dict(
            source_accuracies_recomputed=True, checkpoints_unchanged=True,
            target_count=len(records), target_inventory='original Task 2 Source-only predictions'), indent=2))
    return result
