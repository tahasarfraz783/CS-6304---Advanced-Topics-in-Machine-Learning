import html
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .common import read,write
from .data import DATASETS,load_question
from .core import quality

STYLE='''body{font:16px system-ui;margin:30px auto;max-width:1250px;background:#101725;color:#e5eaf4;padding:0 24px}a{color:#80d8ff}table{border-collapse:collapse;font-size:13px;display:block;overflow:auto}td,th{padding:7px 10px;border-bottom:1px solid #344258;text-align:left}img{max-width:100%;background:white;border-radius:8px}pre{white-space:pre-wrap;background:#1c293c;padding:18px}section{margin:32px 0}.cards{display:flex;flex-wrap:wrap;gap:12px}.card{background:#1c293c;padding:20px;border-radius:12px}small{color:#a7b6cc}'''


def dashboard(root):
    out=root/'evidence';out.mkdir(parents=True,exist_ok=True)
    body=['<h1>Task 3 · test-time compute</h1><div id="progress">Waiting for status</div>']
    if (out/'qualitative.html').exists():body.append('<p><a href="qualitative.html">Aligned failure cases</a> · <a href="report.md">Evidence-based report notes</a></p>')
    else:body.append('<p>Plots, tables, and aligned examples will appear here after analysis. Refresh to load newly completed evidence.</p>')
    for name in ['method_comparison.csv','paired_bootstrap.csv','live_summary.csv','signal_summary.csv','confidence_vision_question_summary.csv']:
        path=out/name
        if path.exists():
            table=pd.read_csv(path)
            if name=='method_comparison.csv':table=table[(table.split=='eval')&(table.N==32)]
            if name=='paired_bootstrap.csv':table=table[table.N==32]
            if name=='confidence_vision_question_summary.csv':table=table.groupby('dataset').agg(question_count=('sample_id','count'),mean_correlation=('confidence_vision_correlation','mean'),mean_covariance=('covariance','mean')).reset_index()
            body.append('<section><h2>'+html.escape(name)+'</h2><a href="'+name+'">Download full CSV</a>'+table.to_html(index=False,float_format=lambda x:f'{x:.4f}')+'</section>')
    if (out/'adaptive_summary.json').exists():
        body.append('<section><h2>Adaptive policies</h2>'+pd.DataFrame(read(out/'adaptive_summary.json')).to_html(index=False)+'</section>')
    for image in sorted(out.glob('*.png')):body.append(f'<section><h2>{html.escape(image.stem)}</h2><img src="{image.name}"></section>')
    script='''<script>async function update(){try{let r=await fetch('../progress.json?t='+Date.now());let s=await r.json();let age=(Date.now()/1000-s.heartbeat).toFixed(0);document.getElementById('progress').textContent=s.stage+' · '+s.done+'/'+s.total+' · '+s.detail+' · heartbeat '+age+'s ago';}catch(e){document.getElementById('progress').textContent='Open through Jupyter for live status; use python monitor.py for terminal status.'}}update();setInterval(update,5000);</script>'''
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Task 3</title><style>'+STYLE+'</style>'+''.join(body)+script,encoding='utf-8')


def savefig(fig,out,name):
    fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=180);fig.savefig(out/(name+'.pdf'));plt.close(fig)


def build(root):
    out=root/'evidence';out.mkdir(exist_ok=True)
    path=out/'method_comparison.csv'
    if not path.exists():dashboard(root);return
    df=pd.read_csv(path);ev=df[df.split=='eval']
    for dataset in DATASETS:
        d=ev[ev.dataset==dataset]
        fig,axes=plt.subplots(1,2,figsize=(13,5))
        colors=plt.cm.tab20(np.linspace(0,1,d.method.nunique()))
        for color,(method,g) in zip(colors,d.groupby('method')):
            for ax,x in zip(axes,['N','tokens']):ax.plot(g[x],g.correct,marker='D' if method.endswith('_RWC') else 'o',linestyle='--' if method.endswith('_RWC') else '-',color=color,label=method,markersize=3)
        oracle=d[d.method=='SC']
        for ax,x in zip(axes,['N','tokens']):
            ax.plot(oracle[x],oracle.oracle,'k--',label='Oracle coverage')
            ax.set(xlabel='Candidates' if x=='N' else 'Retained generated tokens',ylabel='Answer accuracy / coverage',title=dataset)
            ax.grid(alpha=.25)
        axes[1].legend(fontsize=7,bbox_to_anchor=(1.02,1));savefig(fig,out,dataset+'_accuracy_cost')
        fig,axes=plt.subplots(1,2,figsize=(12,4))
        axes[0].plot(oracle.N,oracle.distinct,'o-');axes[0].set(xlabel='Candidates',ylabel='Distinct answer groups',title='Diversity · '+dataset)
        for method in ['FirstAns','SC','certainty_RWC']+(['visconf_RWC'] if dataset=='MathVista' else []):
            g=d[d.method==method];axes[1].plot(g.N,g.selection_failure,'o-',label=method)
        axes[1].plot(oracle.N,oracle.sampling_failure,'k--',label='No correct candidate')
        axes[1].set(xlabel='Candidates',ylabel='Fraction of questions / orders',title='Failure decomposition');axes[1].legend(fontsize=8)
        savefig(fig,out,dataset+'_diversity_failures')
    signal=pd.read_csv(out/'signal_per_question.csv')
    signal_summary=signal.groupby(['dataset','score']).mean(numeric_only=True).reset_index()
    signal_summary.to_csv(out/'signal_summary.csv',index=False)
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    for ax,(dataset,g) in zip(axes,signal_summary.groupby('dataset')):
        ax.barh(g.score,g.top_minus_bottom);ax.axvline(0,color='black',linewidth=.8)
        ax.set(title=dataset+' · within-question score quartiles',xlabel='Top minus bottom correctness')
    savefig(fig,out,'signal_quartile_associations')
    cv=pd.read_csv(out/'confidence_vision_per_rollout.csv')
    if not cv.empty:
        cv.groupby(['dataset','sample_id'])[['confidence_vision_correlation','covariance']].mean().reset_index().to_csv(out/'confidence_vision_question_summary.csv',index=False)
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        question=cv.groupby('sample_id')[['confidence_vision_correlation','covariance']].mean()
        axes[0].hist(question.confidence_vision_correlation.dropna(),bins=30);axes[0].set(title='Within-rollout confidence–vision correlation',xlabel='Question mean Pearson r')
        axes[1].hist(question.covariance.dropna(),bins=30);axes[1].set(title='Tokenwise minus rollout fusion',xlabel='Question mean covariance')
        savefig(fig,out,'confidence_vision')
    adaptive=read(out/'adaptive_summary.json')
    for dataset in DATASETS:
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        fixed=ev[(ev.dataset==dataset)&(ev.method=='SC')]
        axes[0].plot(fixed.tokens,fixed.correct,'o-',label='Fixed-N SC')
        for a in adaptive:
            if a['dataset']!=dataset:continue
            axes[0].scatter(a['eval_tokens'],a['eval_accuracy'],label=a['family'],s=80)
            distribution=a['stopping_distribution'];axes[1].plot(list(map(int,distribution)),list(distribution.values()),'o-',label=a['family'])
        axes[0].set(title=dataset+' adaptive accuracy–cost',xlabel='Retained tokens',ylabel='Accuracy');axes[0].legend()
        axes[1].set(title='Stopping distribution',xlabel='Rollouts consumed',ylabel='Fraction');axes[1].legend()
        savefig(fig,out,dataset+'_adaptive')
    qualitative(root)
    report(root,ev,adaptive)
    dashboard(root)


def qualitative(root):
    out=root/'evidence';sections=['<h1>Aligned examples</h1><p>Selection rule: lexicographically first held-out IDs meeting each stated predicate, using order 0. Up to two examples per dataset and category. Trajectories use the first two MathVista evaluation IDs and rollout IDs 0 and 1, chosen without labels.</p>']
    chosen=[]
    for dataset in DATASETS:
        ids=sorted(read(root/'splits'/f'{dataset}.json')['eval'])
        counts={'selection disagreement':0,'recoverable early stop':0}
        for sid in ids:
            obj=read(root/'offline'/dataset/(sid.replace(':','_')+'.json'))
            rows={r['method']:r for r in obj['rows'] if r['N']==32 and r['order']==0}
            categories=[]
            if rows['SC']['answer']!=rows['certainty_RWC']['answer']:categories.append('selection disagreement')
            stopping_rows=[]
            for family in ['agreement','quality']:
                setting=read(root/'frozen_policies.json')[dataset][family]
                matches=[r for r in obj['policies'] if r['order']==0 and r['family']==family and r['tau']==setting['tau'] and r['gamma']==setting['gamma']]
                if matches:
                    stopping_rows.append(matches[0])
                    if matches[0]['premature_recoverable']:categories.append('recoverable early stop')
            for category in set(categories):
                if counts[category]>=2:continue
                counts[category]+=1;q=load_question(root,dataset,sid)
                sections.append(f'<h2>{dataset} · {html.escape(sid)} · {category}</h2><pre>'+html.escape(q['question'])+'</pre><p>Gold (retrospective): '+html.escape(str(q['gold']))+'</p>')
                table=[dict(rollout=c['id'],group=c['answer'],extracted=c['extracted'],correct=c['correct'],tokens=c['tokens'],L=c['L'],K=c['K']) for c in q['candidates']]
                sections.append(pd.DataFrame(table).to_html(index=False))
                if stopping_rows:sections.append('<h3>Selected policy at order 0</h3>'+pd.DataFrame(stopping_rows).to_html(index=False))
                sections.append('<pre>'+html.escape(json.dumps(rows,indent=2))+'</pre>')
                # Aligned complete candidate text for all answers chosen by compared selectors.
                for answer in dict.fromkeys(r['answer'] for r in rows.values()):
                    c=next(c for c in q['candidates'] if c['answer']==answer)
                    sections.append('<details><summary>Rollout '+str(c['id'])+' · '+html.escape(str(c['extracted']))+'</summary><pre>'+html.escape(c['text'])+'</pre></details>')
                chosen.append(dict(dataset=dataset,sample_id=sid,category=category,order=0))
    ids=read(root/'splits'/'MathVista.json')['eval'][:2]
    for qi,sid in enumerate(ids):
        q=load_question(root,'MathVista',sid);cs=q['candidates']
        lo,hi=np.quantile(np.concatenate([c['kl'] for c in cs]),[.05,.95],method='linear')
        fig,axes=plt.subplots(2,1,figsize=(12,6))
        for ax,c in zip(axes,cs[:2]):
            conf=np.clip((c['kl']-lo)/max(hi-lo,1e-8),0,1)
            ax.plot(conf,label='Calibrated self-certainty');ax.plot(c['v'],label='Visual engagement',alpha=.8)
            ax.set(title=f'{sid} · rollout {c["id"]}',xlabel='Retained generated token',ylabel='Signal');ax.legend()
        savefig(fig,out,f'fixed_trajectory_{qi}')
    if (out/'live_per_question.csv').exists():
        live=pd.read_csv(out/'live_per_question.csv');ref=live[live.strategy=='refinement']
        for column in ['wrong_to_correct','correct_to_wrong']:
            for sid in sorted(ref[ref[column]].sample_id.astype(str))[:2]:
                qi=read(root/'splits'/'MATH.json')['live'].index(sid)
                sections.append('<h2>Revision '+column+' · '+html.escape(sid)+'</h2>')
                for name in ['parallel_0','revision']:
                    call=read(root/'live'/'calls'/f'{qi:02d}_{name}.json')
                    sections.append('<h3>'+name+'</h3><pre>'+html.escape(call['response'])+'</pre>')
                chosen.append(dict(dataset='MATH',sample_id=sid,category=column))
    write(out/'example_selection.json',chosen)
    (out/'qualitative.html').write_text('<!doctype html><meta charset="utf-8"><title>Task 3 cases</title><style>'+STYLE+'</style>'+''.join(sections),encoding='utf-8')


def report(root,ev,adaptive):
    lines=['# Task 3: evidence-based report notes','',
           'This file inserts measured summaries. Interpret the saved qualitative cases before finalizing causal or qualitative claims.',
           '', '## 1. Exploration and selection']
    for dataset in DATASETS:
        rows=ev[(ev.dataset==dataset)&(ev.method=='SC')].set_index('N');a=rows.loc[1];b=rows.loc[32]
        lines.append(f'{dataset}: SC accuracy {a.correct:.3%} → {b.correct:.3%}; oracle coverage {a.oracle:.3%} → {b.oracle:.3%}; distinct groups {a.distinct:.2f} → {b.distinct:.2f}. At 32, no-correct-candidate failures {b.sampling_failure:.3%}, available-but-missed failures {b.selection_failure:.3%}.')
    lines+=['','## 2. Evidence and consensus','Use method_comparison.csv and paired_bootstrap.csv to compare fixed scores under different aggregators. signal_summary.csv gives within-question top-minus-bottom accuracy and length/correctness associations. confidence_vision_question_summary.csv averages rollout correlations within questions; undefined constant-signal correlations are omitted. These associations do not establish causal visual grounding.','',
            '## 3. Breadth and refinement']
    path=root/'evidence'/'live_summary.csv'
    if path.exists():
        for r in pd.read_csv(path).to_dict('records'):
            lines.append(f"{r['strategy']}: accuracy {r['accuracy']:.3%}; mean output tokens {r['output_tokens']:.1f}, input tokens {r['input_tokens']:.1f}, runtime {r['seconds']:.2f}s; truncation rate {r['truncation_rate']:.3%}. Wrong→correct {r['wrong_to_correct']}, correct→wrong {r['correct_to_wrong']} relative to shared initial response.")
    else:lines.append('LIVE GENERATION PENDING. No GPU results are asserted.')
    lines+=['','## 4. Adaptive allocation']
    for r in adaptive:
        lines.append(f"{r['dataset']} {r['family']}: dev-frozen tau={r['tau']}, gamma={r['gamma']}; held-out accuracy {r['eval_accuracy']:.3%}, mean cost {r['eval_tokens']:.1f} tokens, {r['eval_rollouts']:.2f} rollouts. Recoverable incorrect early stops {r['recoverable_early_stop_rate']:.3%}.")
    lines+=['','## 5. Compute and reliability','Compare the adaptive points with fixed-N SC in the accuracy–cost plots; candidate counts alone do not capture variable response lengths. Offline token cost excludes prefill and scoring. Live strategy costs include all calls and charge the shared initial call to both parallel and refinement. The two datasets use different models and tasks; their differences cannot identify a causal effect of vision.','',
            'Intervals use 1,000 paired question bootstrap resamples after averaging ten orders. Full per-question/order records, input hashes, saved splits, call seeds, raw responses, scorer version, and policy settings accompany these notes.']
    limits=root/'validation'/'scorer_timeouts.csv'
    if limits.exists():
        counts=pd.read_csv(limits);affected=counts[counts.timeout_count>0]
        lines.append(f'Scorer resource limits: {int(counts.timeout_count.sum())} parse/verify timeout or memory-limit events across {len(affected)} questions. These comparisons were treated as non-equivalent under the frozen scorer; inspect validation/scorer_timeouts.csv when interpreting equivalence-sensitive results.')
    (root/'evidence'/'report.md').write_text('\n\n'.join(lines),encoding='utf-8')
