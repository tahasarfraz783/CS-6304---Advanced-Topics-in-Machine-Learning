"""Final Task 3 target evaluation. Run only after the study and source diagnostics."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix

from .pacs import CLASSES
from .dg_diagnostics import freeze_protocol, runs, file_hash, write_lock, load_model
from .final_evaluation import extract


def evaluate_sketch(root):
    root = Path(root)
    lock = freeze_protocol(root)  # All five completed checkpoints/configurations fixed first.
    out = root / 'Task 3/results/final_evaluation'
    summary = pd.read_csv(out / 'source_diagnostics.csv')
    if set(summary.method) != set(runs(root)):
        raise ValueError('Complete all source diagnostics before opening Sketch.')
    data = root / 'data/PACS'
    target, rejected = [], []
    folder = data / 'sketch'
    if sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.')) != list(CLASSES):
        raise ValueError('Unexpected Sketch classes.')
    for label, name in enumerate(CLASSES):
        for path in sorted((folder / name).rglob('*')):
            if not path.is_file() or path.suffix.lower() not in {'.jpg','.jpeg','.png','.bmp'}:
                continue
            try:
                with Image.open(path) as im:
                    im.convert('RGB').load()
            except (OSError, ValueError) as exc:
                rejected.append(dict(path=path.relative_to(data).as_posix(), reason=str(exc)))
                continue
            target.append(dict(path=path.relative_to(data).as_posix(), label=label, domain='sketch'))
    if set(r['label'] for r in target) != set(range(7)):
        raise ValueError('Missing target classes.')
    write_lock(out / 'target_inventory.json', [dict(r, sha256=file_hash(data / r['path'])) for r in target])
    write_lock(out / 'rejected_target_images.json', rejected)
    print(f'Final Sketch evaluation: {len(target)} images, {len(rejected)} decoding failures.',flush=True)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    truth = np.array([r['label'] for r in target])
    predictions, classes, confusions, scores = [], [], [], []
    for name, run in runs(root).items():
        print(f'Sketch: {name}',flush=True)
        model = load_model(run / 'best.pt',device)
        _,logits = extract(model,data,target,device)
        pred=logits.argmax(1)
        scores.append(dict(method=name,sketch_accuracy=accuracy_score(truth,pred),
                           sketch_macro_f1=f1_score(truth,pred,labels=range(7),average='macro',zero_division=0)))
        cm=confusion_matrix(truth,pred,labels=range(7))
        for k,c in enumerate(CLASSES):
            wrong=cm[k].copy(); wrong[k]=0
            classes.append(dict(method=name,class_name=c,count=int(cm[k].sum()),accuracy=cm[k,k]/cm[k].sum(),
                                dominant_confusion=CLASSES[wrong.argmax()] if wrong.sum() else '',
                                dominant_confusion_count=int(wrong.max())))
            for j,pc in enumerate(CLASSES):
                confusions.append(dict(method=name,true_class=c,predicted_class=pc,count=int(cm[k,j])))
        predictions.extend(dict(method=name,path=r['path'],label=r['label'],predicted_label=int(p),
                                correct=bool(p==r['label'])) for r,p in zip(target,pred))
        del model
    summary=summary.merge(pd.DataFrame(scores),on='method',validate='one_to_one')
    baseline=summary.loc[summary.method=='ERM','sketch_accuracy'].iloc[0]
    summary['sketch_accuracy_change_pp']=100*(summary.sketch_accuracy-baseline)
    per_class=pd.DataFrame(classes)
    base=per_class[per_class.method=='ERM'].set_index('class_name').accuracy
    per_class['accuracy_change_pp']=100*(per_class.accuracy-per_class.class_name.map(base))
    predictions=pd.DataFrame(predictions)
    base_pred=predictions[predictions.method=='ERM'].set_index('path')
    predictions['baseline_correct']=predictions.path.map(base_pred.correct)
    predictions['baseline_prediction']=predictions.path.map(base_pred.predicted_label)
    cases=predictions[predictions.correct!=predictions.baseline_correct].copy()
    cases['class_name']=cases.label.map(dict(enumerate(CLASSES)))
    cases['change']=np.where(cases.correct,'corrected','introduced_error')
    cases=cases.groupby(['method','class_name','change'],sort=False).head(3)
    study=summary[summary.method.str.startswith('DAN-DG')].copy()
    study.insert(1,'lambda_dg',study.method.map({'DAN-DG':1.,'DAN-DG lambda=0.1':0.1,'DAN-DG lambda=10':10.}))
    study=study.sort_values('lambda_dg')
    for filename,table in [('comparison.csv',summary),('main_comparison.csv',summary[summary.method.isin(['ERM','DAN-DG','SAM'])]),
                           ('per_class.csv',per_class),('target_predictions.csv',predictions),
                           ('confusions.csv',pd.DataFrame(confusions)),('selected_cases.csv',cases),('controlled_study.csv',study)]:
        table.to_csv(out / filename,index=False)
    # Read Task 2 target results only after every Task 3 decision and evaluation is fixed.
    t2=root / 'Task 2/results/final_evaluation'
    if (t2 / 'comparison.csv').exists():
        previous=pd.read_csv(t2 / 'comparison.csv')
        previous=previous[previous.method.isin(['Source-only','DAN'])].copy()
        previous.to_csv(out / 'task2_reference.csv',index=False)
        prior_classes=pd.read_csv(t2 / 'per_class.csv')
        prior_classes[prior_classes.method.isin(['Source-only','DAN'])].to_csv(out / 'task2_per_class_reference.csv',index=False)
        old_inventory=json.loads((t2 / 'image_manifest.json').read_text())
        old_targets={r['path'] for r in old_inventory if r['domain']=='sketch'}
        old_lock=json.loads((t2 / 'evaluation_lock.json').read_text())
        check=dict(same_target_paths=old_targets=={r['path'] for r in target},
                   same_erm_checkpoint=old_lock['runs']['Source-only']['checkpoint_sha256']==lock['runs']['ERM']['sha256'],
                   same_split=old_lock['split_sha256']==lock['split_sha256'])
        (out / 'task2_comparison_verification.json').write_text(json.dumps(check,indent=2))
        if not all(check.values()):
            raise ValueError('Task 2 reference comparability checks failed.')
    return summary,per_class,cases
