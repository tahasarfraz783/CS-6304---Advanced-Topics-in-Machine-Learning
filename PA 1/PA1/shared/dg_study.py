"""Fixed source-only DAN-DG study, recorded before final target analysis."""
import json
from pathlib import Path

from .dan_dg import train_dan_dg


def run_study(root):
    root = Path(root)
    out = root / 'Task 3/results/controlled_study'
    out.mkdir(parents=True, exist_ok=True)
    plan = dict(method='DAN-DG', values=[0.1, 1.0, 10.0], main_lambda=1.0,
                main_sam_rho=0.05, seed=6304,
                hypothesis='Lower alignment weight may preserve source classification; higher weight '
                'may reduce source-domain separability while removing class information. '
                'Sketch accuracy may peak at intermediate alignment rather than improve monotonically. '
                'Low separability alone is not evidence of useful invariance.',
                selection='Mean source validation macro-F1 only; no target-based winner replaces main settings.')
    path = out / 'pre_analysis_plan.json'
    if path.exists() and json.loads(path.read_text()) != plan:
        raise ValueError('Preserve the existing study plan.')
    path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    for weight, folder in [(0.1, 'dan_dg_lambda_0p1'), (1.0, 'dan_dg'), (10.0, 'dan_dg_lambda_10')]:
        destination = root / 'Task 3/results' / folder
        if (destination / 'completion.json').exists():
            info = json.loads((destination / 'config.json').read_text())
            if info['method'] != 'dan_dg' or info['config']['lambda_dg'] != weight:
                raise ValueError('Existing study run has different settings.')
            print(f'Reusing lambda={weight}', flush=True)
            continue
        print(f'Training DAN-DG lambda={weight}', flush=True)
        train_dan_dg(root / 'data/PACS', root / 'shared/splits/pacs_sketch_seed6304.json',
                     destination, root / 'Task 2/results/source_only/best.pt', lambda_dg=weight)
