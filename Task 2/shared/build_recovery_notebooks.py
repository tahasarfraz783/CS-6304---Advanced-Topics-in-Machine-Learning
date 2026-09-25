"""Install opt-in recovery in the Recommended Structure notebooks only."""
import json
from pathlib import Path

PA1 = Path(__file__).resolve().parents[2]
T2 = PA1 / 'Task 2'
T3 = PA1 / 'Task 3'


def source(cell):
    return ''.join(cell['source'])


def replace(s, old, new):
    if old not in s:
        raise ValueError(f'Missing edit anchor: {old[:90]}')
    return s.replace(old, new)


for task, repo in [(2, T2), (3, T3)]:
    path = repo / f'task{task}/train.ipynb'
    nb = json.loads(path.read_text(encoding='utf-8'))
    cell = next(c for c in nb['cells'] if c['cell_type'] == 'code' and 'def train_pacs(' in source(c))
    s = source(cell)
    if 'initial_checkpoint_sha256' in s:
        continue
    s = replace(s, 'import platform', 'import platform\nimport hashlib')
    s = replace(s, '    model = make_model().to(device)', '''    initial_path = cfg.get('initial_checkpoint')
    model = make_model(pretrained=not bool(initial_path)).to(device)
    if initial_path:
        initial = torch.load(initial_path, map_location='cpu', weights_only=True)
        if initial.get('method') != 'source_only' or initial['split_sha256'] != split_hash(split_path):
            raise ValueError('Recovery requires the matching source-only checkpoint.')
        if initial['class_to_idx'] != splits['class_to_idx']:
            raise ValueError('Initialization class mapping mismatch.')
        model.load_state_dict(initial['model_state'])
        cfg['initial_checkpoint_sha256'] = hashlib.sha256(Path(initial_path).read_bytes()).hexdigest()
        del initial
    if cfg.get('freeze_batchnorm_affine', False):
        for layer in model.modules():
            if isinstance(layer, nn.modules.batchnorm._BatchNorm):
                layer.requires_grad_(False)''')
    groups = '''    if 'backbone_learning_rate' in cfg:
        head_ids = {id(p) for p in model.fc.parameters()}
        groups = [dict(params=[p for p in model.parameters() if p.requires_grad and id(p) not in head_ids],
                       lr=cfg['backbone_learning_rate']),
                  dict(params=list(model.fc.parameters()), lr=cfg['learning_rate'])]
'''
    if task == 2:
        groups += '''        if discriminator is not None:
            groups.append(dict(params=list(discriminator.parameters()), lr=cfg['discriminator_learning_rate']))
'''
    groups += '''        optimizer = torch.optim.AdamW(groups, weight_decay=cfg['weight_decay'])
    else:
        optimizer = torch.optim.AdamW(parameters, lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])'''
    s = replace(s, "    optimizer = torch.optim.AdamW(parameters, lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])", groups)
    s = replace(s, '        total_perturbed = 0.0', '        total_perturbed = 0.0\n        weighted_total, ramp_total, gradient_total = 0.0, 0.0, 0.0')
    s = replace(s, '            optimizer.zero_grad(set_to_none=True)', '''            optimizer.zero_grad(set_to_none=True)
            ramp_epochs = cfg.get('alignment_ramp_epochs', 0)
            ramp = min(1., ((epoch - 1)*steps + step + 1)/(ramp_epochs*steps)) if ramp_epochs else 1.
            ramp_total += ramp
            step_cfg = dict(cfg)
            for key in ('lambda_mmd', 'lambda_dg', 'max_grl_strength'):
                if key in step_cfg:
                    step_cfg[key] *= ramp''')
    if task == 2:
        s = replace(s, 'discriminator, cfg, progress, discriminator_cpu_rng)', 'discriminator, step_cfg, progress, discriminator_cpu_rng)')
        s = replace(s, '            total_alignment += alignment.item() * len(y)', '            total_alignment += alignment.item() * len(y)\n            weighted_total += (loss - classification).item() * len(y)')
        s = replace(s, '            loss.backward(); optimizer.step()', '''            loss.backward()
            if cfg.get('gradient_clip_norm') is not None:
                gradient_total += float(torch.nn.utils.clip_grad_norm_(parameters, cfg['gradient_clip_norm'], error_if_nonfinite=True))
            optimizer.step()''')
        s = replace(s, "weighted_mmd_loss=cfg['lambda_mmd'] * total_alignment/count", 'weighted_mmd_loss=weighted_total/count')
    else:
        s = replace(s, 'dan_dg_objective(model, x, y, cfg)', 'dan_dg_objective(model, x, y, step_cfg)')
        s = replace(s, '                total_alignment += alignment.item() * len(y)', '                total_alignment += alignment.item() * len(y)\n                weighted_total += (loss - classification).item() * len(y)')
        s = replace(s, '                loss.backward(); optimizer.step()', '''                loss.backward()
                if cfg.get('gradient_clip_norm') is not None:
                    gradient_total += float(torch.nn.utils.clip_grad_norm_(parameters, cfg['gradient_clip_norm'], error_if_nonfinite=True))
                optimizer.step()''')
        s = replace(s, "weighted_mmd_loss=cfg['lambda_dg'] * total_alignment/count", 'weighted_mmd_loss=weighted_total/count')
    s = replace(s, "        for item in metrics.to_dict('records'):", '''        if cfg.get('alignment_ramp_epochs', 0):
            row['mean_alignment_ramp'] = ramp_total / steps
        if cfg.get('gradient_clip_norm') is not None:
            row['mean_gradient_norm_before_clip'] = gradient_total / steps
        for item in metrics.to_dict('records'):''')
    s = replace(s, '        if score > best:', "        eligible = epoch >= cfg.get('selection_start_epoch', 1)\n        if eligible and score > best:")
    s = replace(s, '        else:\n            stale += 1', '        elif eligible:\n            stale += 1')
    cell['source'] = s.splitlines(True)
    cell['outputs'] = []; cell['execution_count'] = None
    nb['cells'][0]['source'] = [f'# Task {task} training\nOriginal defaults are retained. For the five revised runs, use `train_recovery_v1.ipynb`.\n']
    path.write_text(json.dumps(nb, indent=1), encoding='utf-8')

path = T3 / 'task3/selection/source_validation.ipynb'
nb = json.loads(path.read_text())
cell = next(c for c in nb['cells'] if c['cell_type'] == 'code' and 'def validate_config' in source(c))
s = source(cell)
if 'recovery_keys' not in s:
    s = replace(s, '    for key, value in CONFIG.items():', '''    recovery_keys = {'epochs', 'patience', 'learning_rate', 'batchnorm'} if cfg.get('experiment') == 'recovery_v1' else set()
    for key, value in CONFIG.items():
        if key in recovery_keys:
            continue''')
    cell['source'] = s.splitlines(True)
    path.write_text(json.dumps(nb, indent=1))

settings = dict(experiment='recovery_v1', experiment_note='Follow-up after original target-result inspection',
                epochs=20, patience=8, learning_rate=1e-5, backbone_learning_rate=1e-5,
                discriminator_learning_rate=1e-5, max_grl_strength=0.1,
                freeze_batchnorm_affine=True, batchnorm='frozen_pretrained_running_stats_and_affine',
                gradient_clip_norm=1.0, alignment_ramp_epochs=5, selection_start_epoch=5)
for task, repo in [(2, T2), (3, T3)]:
    (repo / f'task{task}/configs/recovery_v1.yaml').write_text(json.dumps(settings, indent=2))


def md(s):
    return dict(cell_type='markdown', metadata={}, source=s.splitlines(True))


def code(s):
    return dict(cell_type='code', metadata={}, execution_count=None, outputs=[], source=s.splitlines(True))


def write(path, cells):
    for i, c in enumerate(cells): c['id'] = f'cell-{i}'
    path.write_text(json.dumps(dict(nbformat=4, nbformat_minor=5, cells=cells, metadata=dict(
        kernelspec=dict(name='pa1_env', display_name='Python (pa1_env)', language='python'),
        language_info=dict(name='python', version='3.10.21'))), indent=1))


def setup(task):
    return f'''from pathlib import Path
import os, json
from IPython.display import display
RECOVERY_PA1 = next(p for p in (Path.cwd(), *Path.cwd().parents)
                    if (p / 'Task 2/task2/train.ipynb').is_file())
RECOVERY_TASK = {task}
repo = RECOVERY_PA1 / 'Task {task}'
# Load only setup and training definitions, never the original run cell.
previous_cwd = Path.cwd()
try:
    os.chdir(repo)
    document = json.loads((repo / 'task{task}/train.ipynb').read_text())
    for cell in document['cells'][1:3]:
        exec(compile(''.join(cell['source']), 'recommended_training_definitions', 'exec'), globals())
finally:
    os.chdir(previous_cwd)
helper = RECOVERY_PA1 / 'Task 2/shared/recovery_support.py'
exec(compile(helper.read_text(), str(helper), 'exec'), globals())
print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')
print('All checkpoints and results use Recommended Structure folders.')
'''

for task, repo, runs in [(2, T2, ['dann', 'cdan', 'dan_lambda_10']), (3, T3, ['dan_dg', 'dan_dg_lambda_10'])]:
    cells = [md(f'# Task {task}: recovery v1\nUse pa1_env. Restart the kernel, then Run All. Results save automatically under `task{task}/results/recovery_v1/`. Only Recommended Structure notebooks/checkpoints are used.\n'), code(setup(task))]
    for run in runs:
        cells += [md(f'## {run}'), code(f"display(train_recovery_run('{run}'))\n")]
    cells += [code('display(review_recovery_sources())\n')]
    write(repo / f'task{task}/train_recovery_v1.ipynb', cells)

# Use Task 3 definitions for the common model/evaluate helper. The extraction
# definitions come directly from the Recommended Structure evaluation notebook.
write(T3 / 'task3/review_recovery_v1.ipynb', [md('# Review all five revised runs\nRun after both recovery training notebooks complete. Only Recommended Structure results are read and written.\n'),
    code(setup(3)), code('display(review_recovery_sources())\n'),
    code('''evaluation_nb = RECOVERY_PA1 / 'Task 3/task3/evaluate_sketch.ipynb'
document = json.loads(evaluation_nb.read_text())
extraction = next(c for c in document['cells'] if c['cell_type'] == 'code' and 'def extract(' in ''.join(c['source']))
exec(compile(''.join(extraction['source']), str(evaluation_nb), 'exec'), globals())
tables = evaluate_recovery_runs()
for task, table in tables.items():
    print(f'Task {task}: accuracy (%)')
    shown = table.copy()
    for col in ['old_sketch_accuracy', 'sketch_accuracy', 'source_accuracy']:
        shown[col] *= 100
    display(shown.round(2))
''')])
