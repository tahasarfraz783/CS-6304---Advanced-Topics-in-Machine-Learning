"""Plots and evidence tables for the completed Task 3 experiments."""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from .pacs import CLASSES
from .dg_diagnostics import runs


def make_figures(root):
    root=Path(root); out=root / 'Task 3/results/final_evaluation'
    summary=pd.read_csv(out/'comparison.csv')
    main=summary[summary.method.isin(['ERM','DAN-DG','SAM'])]
    study=pd.read_csv(out/'controlled_study.csv')
    classes=pd.read_csv(out/'per_class.csv')
    cases=pd.read_csv(out/'selected_cases.csv')
    fig,axes=plt.subplots(1,3,figsize=(15,4))
    x=np.arange(len(main)); width=.25
    for i,(column,label) in enumerate([('mean_source_accuracy','Mean source'),('worst_source_accuracy','Worst source'),('sketch_accuracy','Sketch')]):
        axes[0].bar(x+(i-1)*width,100*main[column],width,label=label)
    axes[0].set(xticks=x,xticklabels=main.method,ylabel='Accuracy (%)',ylim=(0,105)); axes[0].legend(fontsize=8)
    axes[1].bar(main.method,100*main.source_domain_separability)
    axes[1].axhline(100/3,color='black',ls='--',label='Chance (33.3%)')
    axes[1].set(ylabel='Source domain probe accuracy (%)',ylim=(0,105)); axes[1].legend(fontsize=8)
    axes[2].bar(main.method,main.sharpness); axes[2].set(ylabel='Validation CE increase',title='Common sharpness proxy (radius 0.05)')
    fig.tight_layout(); fig.savefig(out/'main_comparison.png',dpi=160); plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for column,label in [('mean_source_accuracy','Mean source'),('worst_source_accuracy','Worst source'),('sketch_accuracy','Sketch')]:
        axes[0].plot(study.lambda_dg,100*study[column],marker='o',label=label)
    axes[0].set(xscale='log',xlabel='DAN-DG lambda',ylabel='Accuracy (%)'); axes[0].legend()
    axes[1].plot(study.lambda_dg,100*study.source_domain_separability,marker='o')
    axes[1].axhline(100/3,color='black',ls='--'); axes[1].set(xscale='log',xlabel='DAN-DG lambda',ylabel='Source domain probe accuracy (%)')
    fig.tight_layout(); fig.savefig(out/'controlled_study.png',dpi=160); plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(15,8))
    for ax,(name,folder) in zip(axes.flat,runs(root).items()):
        h=pd.read_csv(folder/'history.csv')
        column='classification_loss' if 'classification_loss' in h else 'train_loss'
        ax.plot(h.epoch,h[column],label='Classification CE')
        if 'mmd_loss' in h:
            ax.plot(h.epoch,h.mmd_loss,label='Mean pairwise MMD')
            ax.plot(h.epoch,h.train_loss,label='Total objective')
        if 'perturbed_classification_loss' in h:
            ax.plot(h.epoch,h.perturbed_classification_loss,label='Perturbed CE')
        ax.set(title=name,xlabel='Epoch',ylabel='Loss'); ax.legend(fontsize=8)
    axes.flat[-1].axis('off'); fig.tight_layout(); fig.savefig(out/'all_training_curves.png',dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4)); x=np.arange(7)
    for i,name in enumerate(['DAN-DG','SAM']):
        values=classes[classes.method==name].set_index('class_name').loc[list(CLASSES)]
        ax.bar(x+(i-.5)*.35,values.accuracy_change_pp,.35,label=name)
    ax.axhline(0,color='black',lw=.8); ax.set(xticks=x,xticklabels=CLASSES,ylabel='Sketch accuracy change vs ERM (pp)'); ax.legend()
    fig.tight_layout(); fig.savefig(out/'per_class_changes.png',dpi=160); plt.close(fig)
    conf=pd.read_csv(out/'confusions.csv')
    fig,axes=plt.subplots(1,3,figsize=(16,5))
    for ax,name in zip(axes,['ERM','DAN-DG','SAM']):
        cm=conf[conf.method==name].pivot(index='true_class',columns='predicted_class',values='count').loc[list(CLASSES),list(CLASSES)].to_numpy()
        normalized=cm/cm.sum(1,keepdims=True)
        ax.imshow(normalized,vmin=0,vmax=1,cmap='Blues')
        for i in range(7):
            for j in range(7): ax.text(j,i,str(cm[i,j]),ha='center',va='center',fontsize=7,color='white' if normalized[i,j]>.5 else 'black')
        ax.set(title=name,xticks=range(7),xticklabels=CLASSES,yticks=range(7),yticklabels=CLASSES,xlabel='Predicted',ylabel='True')
        ax.tick_params(axis='x',rotation=60)
    fig.tight_layout(); fig.savefig(out/'sketch_confusions.png',dpi=160); plt.close(fig)
    # Choose deterministic examples from classes with largest improvement/degradation.
    selected=[]
    for name in ['DAN-DG','SAM']:
        values=classes[classes.method==name]
        for change,ascending in [('corrected',False),('introduced_error',True)]:
            ranked=values.sort_values('accuracy_change_pp',ascending=ascending).class_name
            for c in ranked:
                subset=cases[(cases.method==name)&(cases.change==change)&(cases.class_name==c)]
                if len(subset):
                    selected.extend(subset.head(2).to_dict('records')); break
    if selected:
        cols=4; rows=(len(selected)+cols-1)//cols
        fig,axes=plt.subplots(rows,cols,figsize=(14,3.8*rows),squeeze=False)
        for ax in axes.flat: ax.axis('off')
        for ax,r in zip(axes.flat,selected):
            with Image.open(root/'data/PACS'/r['path']) as im: ax.imshow(im.convert('RGB'))
            ax.set_title(f"{r['method']}: {r['change']}\nTrue: {r['class_name']} | ERM: {CLASSES[int(r['baseline_prediction'])]}\nNew: {CLASSES[int(r['predicted_label'])]}",fontsize=9)
        fig.tight_layout(); fig.savefig(out/'selected_failures.png',dpi=150); plt.close(fig)
        pd.DataFrame(selected).to_csv(out/'illustrated_cases.csv',index=False)
    previous=pd.read_csv(out/'task2_reference.csv')
    t2classes=pd.read_csv(out/'task2_per_class_reference.csv')
    dan=previous[previous.method=='DAN'].iloc[0]
    baseline=main[main.method=='ERM'].iloc[0]
    cross=pd.DataFrame([dict(method='Task 2 DAN (target-aware)',sketch_accuracy=dan.target_accuracy,
                             sketch_macro_f1=dan.target_macro_f1,sketch_accuracy_change_pp=100*(dan.target_accuracy-baseline.sketch_accuracy)),
                        dict(method='Task 3 DAN-DG (source-only)',**main[main.method=='DAN-DG'][['sketch_accuracy','sketch_macro_f1','sketch_accuracy_change_pp']].iloc[0].to_dict())])
    cross.to_csv(out/'dan_vs_dan_dg.csv',index=False)
    t2=t2classes[t2classes.method=='DAN'][['class_name','accuracy']].rename(columns={'accuracy':'task2_dan_accuracy'})
    t3=classes[classes.method=='DAN-DG'][['class_name','accuracy']].rename(columns={'accuracy':'task3_dan_dg_accuracy'})
    t2.merge(t3,on='class_name').to_csv(out/'dan_vs_dan_dg_per_class.csv',index=False)
    return main,study,cross
