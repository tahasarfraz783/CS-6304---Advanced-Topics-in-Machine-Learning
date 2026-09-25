"""Loaded by Recommended Structure recovery notebooks into their definition namespace.

Model, objectives, data, training and metric functions come exclusively from the
Recommended Structure notebooks. No legacy shared Python modules are imported.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd
import numpy as np
import torch

RECOVERY_RUNS = {
    'dann': (2, 'dann', 'DANN', {}),
    'cdan': (2, 'cdan', 'CDAN', {}),
    'dan_lambda_10': (2, 'dan', 'DAN lambda=10', {'lambda_mmd': 10.0, 'backbone_learning_rate': 1e-6}),
    'dan_dg': (3, 'dan_dg', 'DAN-DG', {'lambda_dg': 1.0}),
    'dan_dg_lambda_10': (3, 'dan_dg', 'DAN-DG lambda=10', {'lambda_dg': 10.0, 'backbone_learning_rate': 1e-6}),
}


def recovery_task_dir(task):
    return RECOVERY_PA1 / f'Task {task}' / f'task{task}'


def recovery_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def recovery_recipe(run):
    task, method, _, overrides = RECOVERY_RUNS[run]
    folder = recovery_task_dir(task)
    base = folder / ('configs/base.yaml' if task == 2 else 'configs/erm.yaml')
    cfg = json.loads(base.read_text())
    cfg.update(json.loads((folder / f'configs/{method}.yaml').read_text()))
    cfg.update(json.loads((folder / 'configs/recovery_v1.yaml').read_text()))
    cfg.update(overrides)
    cfg['initial_checkpoint'] = str(recovery_task_dir(2) / 'results/source_only/best.pt')
    return method, cfg, folder / 'results/recovery_v1' / run


def train_recovery_run(run):
    if RECOVERY_RUNS[run][0] != RECOVERY_TASK:
        raise ValueError('Use the matching task training notebook.')
    method, cfg, out = recovery_recipe(run)
    print('Run:', run, '\nOutput:', out, '\nSettings:', json.dumps(cfg, indent=2))
    if out.exists() and any(out.iterdir()):
        if not (out / 'completion.json').is_file():
            raise RuntimeError(f'Interrupted run preserved at {out}; choose a new recovery version before retrying.')
        saved = json.loads((out / 'config.json').read_text())
        if saved['method'] != method or any(saved['config'].get(k) != v for k, v in cfg.items()):
            raise ValueError('Saved recipe differs; use a new recovery version.')
        if saved['split_sha256'] != split_hash(SPLIT_PATH):
            raise ValueError('Source split changed.')
        if saved['config']['initial_checkpoint_sha256'] != recovery_hash(cfg['initial_checkpoint']):
            raise ValueError('Initialization checkpoint changed.')
        print('Loaded completed recovery run.')
    else:
        model, _, _ = train_pacs(DATA_ROOT, SPLIT_PATH, out, cfg, method=method)
        del model
        if torch.cuda.is_available(): torch.cuda.empty_cache()
    history = pd.read_csv(out / 'history.csv')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for col in ['classification_loss', 'weighted_mmd_loss', 'domain_loss']:
        if col in history: axes[0].plot(history.epoch, history[col], label=col)
    for col in ['mean_val_accuracy', 'mean_val_macro_f1']:
        axes[1].plot(history.epoch, history[col], label=col)
    axes[2].plot(history.epoch, history.mean_gradient_norm_before_clip, label='Gradient norm before clipping')
    for ax in axes:
        ax.set_xlabel('Epoch'); ax.legend(); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(out / 'training_curves.png', dpi=150)
    plt.show(); plt.close(fig)
    return pd.read_csv(out / 'source_validation.csv')


def review_recovery_sources():
    rows = []
    for run, (task, _, _, _) in RECOVERY_RUNS.items():
        _, _, out = recovery_recipe(run)
        if not (out / 'completion.json').exists():
            rows.append(dict(task=task, run=run, status='not completed'))
            continue
        metrics = pd.read_csv(out / 'source_validation.csv')
        counts = pd.read_csv(out / 'source_validation_predictions.csv').prediction.value_counts()
        done = json.loads((out / 'completion.json').read_text())
        rows.append(dict(task=task, run=run, status='completed', source_accuracy=metrics.accuracy.mean(),
                         source_macro_f1=metrics.macro_f1.mean(), predicted_classes=len(counts),
                         dominant_prediction_share=counts.max()/counts.sum(), collapsed=len(counts) == 1,
                         best_epoch=done['best_epoch']))
    table = pd.DataFrame(rows)
    for task in (2, 3):
        out = recovery_task_dir(task) / 'results/recovery_v1'
        out.mkdir(parents=True, exist_ok=True)
        table[table.task == task].to_csv(out / 'source_review.csv', index=False)
    return table


def evaluate_recovery_runs():
    """Lock all five runs, then evaluate using only Recommended Structure references."""
    from torch.utils.data import DataLoader
    split = json.loads(SPLIT_PATH.read_text())
    lock = dict(experiment='recovery_v1_followup', split_sha256=split_hash(SPLIT_PATH), runs={})
    for run, (task, method, _, _) in RECOVERY_RUNS.items():
        _, cfg, out = recovery_recipe(run)
        if not (out / 'completion.json').exists():
            raise RuntimeError(f'Complete all five runs before final evaluation: missing {run}.')
        info = json.loads((out / 'config.json').read_text())
        if info['method'] != method or info['split_sha256'] != lock['split_sha256'] or info['class_to_idx'] != split['class_to_idx']:
            raise ValueError(f'Provenance mismatch: {run}')
        if any(info['config'].get(k) != v for k, v in cfg.items()):
            raise ValueError(f'Recipe mismatch: {run}')
        if info['config']['initial_checkpoint_sha256'] != recovery_hash(cfg['initial_checkpoint']):
            raise ValueError('Initialization checkpoint changed.')
        lock['runs'][run] = dict(checkpoint_sha256=recovery_hash(out / 'best.pt'), metadata=info)
    # Check both locks before writing either; a changed run needs a new version.
    for task in (2, 3):
        path = recovery_task_dir(task) / 'results/recovery_v1/final_evaluation/evaluation_lock.json'
        if path.exists() and json.loads(path.read_text()) != lock:
            raise ValueError('Evaluation lock differs. Choose a new recovery version.')
    for task in (2, 3):
        out = recovery_task_dir(task) / 'results/recovery_v1/final_evaluation'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'evaluation_lock.json').write_text(json.dumps(lock, indent=2))
    reference = recovery_task_dir(2) / 'results/final_evaluation/target_predictions.csv'
    inventory = pd.read_csv(reference)
    inventory = inventory[inventory.method == 'Source-only'][['path', 'label']]
    if inventory.empty or inventory.path.duplicated().any() or set(inventory.label) != set(range(7)):
        raise ValueError('Invalid Recommended Structure target inventory.')
    records = inventory.to_dict('records'); truth = inventory.label.to_numpy()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    loaders = {d: DataLoader(PACSSource(DATA_ROOT, split['domains'][d]['val']), batch_size=64,
                            shuffle=False, num_workers=0) for d in SOURCES}
    rows, predictions, classes = [], [], []
    for run, (task, method, old_name, _) in RECOVERY_RUNS.items():
        _, _, out = recovery_recipe(run)
        print('Evaluating:', run, flush=True)
        saved = torch.load(out / 'best.pt', map_location='cpu', weights_only=True)
        info = lock['runs'][run]['metadata']
        if saved['method'] != method or relocated_recovery_config(saved['config']) != info['config'] or saved['split_sha256'] != info['split_sha256']:
            raise ValueError('Checkpoint metadata mismatch.')
        model = make_model(pretrained=False).to(device)
        model.load_state_dict(saved['model_state']); model.eval()
        metrics, _ = evaluate(model, loaders, device)
        previous_source = pd.read_csv(out / 'source_validation.csv').set_index('domain')
        if not np.allclose(metrics.set_index('domain').loc[list(SOURCES), 'accuracy'], previous_source.loc[list(SOURCES), 'accuracy']):
            raise ValueError(f'Source accuracy failed recomputation: {run}')
        _, logits = extract(model, DATA_ROOT, records, device)
        pred = logits.argmax(1); acc = float(np.mean(pred == truth))
        previous = pd.read_csv(recovery_task_dir(task) / 'results/final_evaluation/comparison.csv')
        column = 'target_accuracy' if task == 2 else 'sketch_accuracy'
        old_acc = float(previous.loc[previous.method == old_name, column].iloc[0])
        counts = np.bincount(pred, minlength=7)
        rows.append(dict(task=task, run=run, old_sketch_accuracy=old_acc, sketch_accuracy=acc,
                         change_pp=100*(acc-old_acc), source_accuracy=metrics.accuracy.mean(),
                         predicted_classes=int((counts > 0).sum()), dominant_prediction_share=float(counts.max()/len(pred)),
                         best_epoch=saved['epoch']))
        predictions.extend(dict(task=task, run=run, path=r['path'], label=r['label'],
                                predicted_label=int(p), correct=bool(p == r['label'])) for r, p in zip(records, pred))
        for i, name in enumerate(CLASSES):
            classes.append(dict(task=task, run=run, class_name=name, count=int((truth == i).sum()),
                                accuracy=float(np.mean(pred[truth == i] == i))))
        if recovery_hash(out / 'best.pt') != lock['runs'][run]['checkpoint_sha256']:
            raise ValueError('Checkpoint changed during evaluation.')
        del model, saved
    tables = {}
    for task in (2, 3):
        out = recovery_task_dir(task) / 'results/recovery_v1/final_evaluation'
        for name, records_ in [('comparison', rows), ('target_predictions', predictions), ('per_class', classes)]:
            frame = pd.DataFrame(records_)
            frame[frame.task == task].to_csv(out / f'{name}.csv', index=False)
        (out / 'verification.json').write_text(json.dumps(dict(source_accuracies_recomputed=True,
            checkpoints_unchanged=True, target_count=len(inventory), target_inventory_sha256=recovery_hash(reference)), indent=2))
        tables[task] = pd.DataFrame(rows).query('task == @task').reset_index(drop=True)
    return tables


def relocated_recovery_config(config):
    """Normalize historical paths while preserving checkpoint bytes."""
    config = dict(config)
    value = config.get('initial_checkpoint')
    if value:
        for task in range(1, 5):
            value = value.replace(f'Task {task} - Recommended Structure', f'Task {task}')
        config['initial_checkpoint'] = value
    return config
