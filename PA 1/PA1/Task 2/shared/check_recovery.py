"""Synthetic integration tests using only Recommended Structure definitions."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import pandas as pd
import torch
from torch import nn
from torch.utils.data import Dataset

PA1 = Path(__file__).resolve().parents[2]
torch.set_num_threads(1)


class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.feature_layer = nn.Linear(512, 512)
        self.bn = nn.BatchNorm1d(512)
        self.fc = nn.Linear(512, 7)

    def features(self, x):
        return self.bn(self.feature_layer(x))

    def forward(self, x):
        return self.fc(self.features(x))


class Images(Dataset):
    def __init__(self, root, records, training=False): self.records = records
    def __len__(self): return len(self.records)
    def __getitem__(self, i):
        seed = sum(map(ord, self.records[i]['path'])) + i
        return torch.randn(512, generator=torch.Generator().manual_seed(seed)), self.records[i]['label']


def load(task):
    notebook = PA1 / f'Task {task}/task{task}/train_recovery_v1.ipynb'
    nb = json.loads(notebook.read_text())
    ns = {'__name__': '__test__'}
    exec(compile(''.join(nb['cells'][1]['source']), str(notebook), 'exec'), ns)
    return ns


namespaces = {task: load(task) for task in (2, 3)}
# Validate the actual recommended baseline/split against the actual revised config.
real = namespaces[3]
_, cfg, _ = real['recovery_recipe']('dan_dg')
real['validate_config'](cfg, 'dan_dg')
assert 'Task 2' in cfg['initial_checkpoint']
print('PASS actual Recommended Structure baseline and revised Task 3 validation')

with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='test_recovery_') as temp:
    root = Path(temp)
    for task in (2, 3):
        repo = root / f'Task {task}'
        configs = repo / ('task2' if task == 2 else '.') / f'configs'
        configs.mkdir(parents=True)
        original = PA1 / f'Task {task}/task{task}/configs'
        for file in original.glob('*.yaml'):
            data = json.loads(file.read_text())
            if file.name == 'recovery_v1.yaml':
                data.update(epochs=2, alignment_ramp_epochs=2, selection_start_epoch=2)
            (configs / file.name).write_text(json.dumps(data))
    records = [dict(path=f'target/{i}.png', label=i % 7) for i in range(8)]
    ns = namespaces[2]
    splits = dict(class_to_idx={c: i for i, c in enumerate(ns['CLASSES'])},
                  domains={d: dict(train=[dict(path=f'{d}/{i}', label=i % 7) for i in range(8)],
                                   val=[dict(path=f'{d}/{i}', label=i % 7) for i in range(8)]) for d in ns['SOURCES']})
    split = root / 'Task 2/shared/splits/pacs_sketch_seed6304.json'
    split.parent.mkdir(parents=True); split.write_text(json.dumps(splits))
    baseline = root / 'Task 2/task2/results/source_only/best.pt'
    baseline.parent.mkdir(parents=True)
    initial = Tiny()
    torch.save(dict(model_state=initial.state_dict(), method='source_only', config=namespaces[3]['CONFIG'],
                    split_sha256=ns['split_hash'](split), class_to_idx=splits['class_to_idx']), baseline)
    for ns in namespaces.values():
        ns.update(RECOVERY_PA1=root, SPLIT_PATH=split, BASELINE=baseline, DATA_ROOT=root / 'data/PACS',
                  prepare_splits=lambda *a: splits, make_model=lambda **kw: Tiny(),
                  PACSSource=Images, UnlabeledSketch=lambda *a: Images(None, records),
                  forward_features=lambda model, x: model.features(x), tqdm=lambda x, **kw: x)
    with patch('torch.cuda.is_available', return_value=False):
        for run, (task, method, _, _) in namespaces[2]['RECOVERY_RUNS'].items():
            ns = namespaces[task]
            _, cfg, out = ns['recovery_recipe'](run)
            model, metrics, history = ns['train_pacs'](ns['DATA_ROOT'], split, out, cfg, method)
            saved = torch.load(out / 'best.pt', weights_only=True)
            assert saved['epoch'] == 2
            assert torch.equal(model.bn.weight, initial.bn.weight)
            assert torch.equal(model.bn.running_mean, initial.bn.running_mean)
            assert not torch.equal(model.fc.weight, initial.fc.weight)
            assert not torch.equal(model.feature_layer.weight, initial.feature_layer.weight)
            assert history.mean_alignment_ramp.tolist() == [.5, 1.]
            assert history.mean_gradient_norm_before_clip.gt(0).all()
            if 'mmd_loss' in history:
                weight = cfg.get('lambda_mmd', cfg.get('lambda_dg'))
                assert torch.allclose(torch.tensor(history.weighted_mmd_loss.to_numpy()),
                                      torch.tensor((history.mmd_loss * history.mean_alignment_ramp * weight).to_numpy()), atol=1e-6)
            try:
                ns['train_pacs'](ns['DATA_ROOT'], split, out, cfg, method)
            except FileExistsError: pass
            else: raise AssertionError('Overwrote existing checkpoint')
            print('PASS Recommended Structure training:', run)
        ns = namespaces[3]
        for task in (2, 3):
            out = ns['recovery_task_dir'](task) / 'results/final_evaluation'
            out.mkdir(parents=True)
            pd.DataFrame([dict(method=name, target_accuracy=.1, sketch_accuracy=.1)
                          for t, _, name, _ in ns['RECOVERY_RUNS'].values() if t == task]).to_csv(out / 'comparison.csv', index=False)
        pd.DataFrame([dict(method='Source-only', **r) for r in records]).to_csv(
            ns['recovery_task_dir'](2) / 'results/final_evaluation/target_predictions.csv', index=False)

        def extract(model, root, recs, device):
            dataset = Images(root, recs)
            x = torch.stack([dataset[i][0] for i in range(len(dataset))])
            with torch.no_grad(): return model.features(x).numpy(), model(x).numpy()

        ns['extract'] = extract
        tables = ns['evaluate_recovery_runs']()
        assert [len(tables[t]) for t in (2, 3)] == [3, 2]
        for task in (2, 3):
            out = ns['recovery_task_dir'](task) / 'results/recovery_v1/final_evaluation'
            pred = pd.read_csv(out / 'target_predictions.csv')
            for run, group in pred.groupby('run'):
                assert group.correct.mean() == tables[task].set_index('run').loc[run, 'sketch_accuracy']
            assert json.loads((out / 'verification.json').read_text())['source_accuracies_recomputed']
        print('PASS Recommended Structure evaluation: source recomputation, five locks, separate task tables')

for task in (2, 3):
    folder = PA1 / f'Task {task}/task{task}'
    for file in [folder / 'train.ipynb', folder / 'train_recovery_v1.ipynb'] + ([folder / 'review_recovery_v1.ipynb'] if task == 3 else []):
        for cell in json.loads(file.read_text())['cells']:
            if cell['cell_type'] == 'code': compile(''.join(cell['source']), str(file), 'exec')
print('PASS notebook syntax')
