import concurrent.futures
import multiprocessing as mp
import itertools
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from .common import write,read
from .core import BUDGETS, quality, select, stopping, votes
from .data import load_question,DATASETS


def corr(a,b):
    if np.std(a)==0 or np.std(b)==0:return None
    return float(spearmanr(a,b).statistic)


def one_question(job):
    root,dataset,sid=job
    path=root/'offline'/dataset/(sid.replace(':','_')+'.json')
    if path.exists():return sid
    q=load_question(root,dataset,sid);c=q['candidates'];rows=[];policies=[]
    all_scores=quality(c)
    correct=np.array([r['correct'] for r in c],float);length=np.array([r['tokens'] for r in c])
    signal=[]
    for name,score in dict(all_scores,length=length).items():
        # Stable quartile membership: ties broken by rollout ID, fixed before labels.
        ix=np.argsort(score,kind='stable')
        signal.append(dict(score=name,top_minus_bottom=float(correct[ix[-8:]].mean()-correct[ix[:8]].mean()),
                           length_correlation=corr(score,length),correctness_correlation=corr(score,correct)))
    trajectory=[]
    if dataset=='MathVista':
        low,high=np.quantile(np.concatenate([r['kl'] for r in c]),[.05,.95],method='linear')
        for r in c:
            conf=np.clip((r['kl']-low)/max(high-low,1e-8),0,1)
            pearson=None if np.std(conf)==0 or np.std(r['v'])==0 else float(np.corrcoef(conf,r['v'])[0,1])
            trajectory.append(dict(rollout=r['id'],confidence_vision_correlation=pearson,
                                   covariance=float(np.mean(conf*r['v'])-np.mean(conf)*np.mean(r['v']))))
    for oi,order in enumerate(q['orders']):
        prefix={}
        for n in BUDGETS:
            cs=[c[j] for j in order[:n]];scores=quality(cs);sels=select(cs,scores)
            groups={r['answer']:r['correct'] for r in cs}
            prefix[n]=(cs,scores,sels)
            oracle=any(r['correct'] for r in cs);total=sum(r['tokens'] for r in cs)
            for method,answer in sels.items():
                ok=bool(groups[answer])
                selected_id=cs[int(np.argmax(scores[method]))]['id'] if method in scores else next(r['id'] for r in cs if r['answer']==answer)
                rows.append(dict(order=oi,N=n,method=method,answer=answer,correct=ok,oracle=oracle,
                                 selected_rollout_id=selected_id,
                                 sampling_failure=not oracle,selection_failure=oracle and not ok,
                                 tokens=cs[0]['tokens'] if method=='FirstAns' else total,
                                 distinct=len(groups),candidate_ids=order[:1] if method=='FirstAns' else order[:n]))
        for family in ['agreement','quality']:
            params=itertools.product([.5,.625,.75,.875,1.], [0.] if family=='agreement' else [0.,.1,.25,.5])
            for tau,gamma in params:
                consumed=32
                for n in [4,8,16]:
                    cs,scores,_=prefix[n]
                    if stopping(cs,family,tau,gamma,scores['certainty' if dataset=='MATH' else 'visconf']):
                        consumed=n;break
                cs,_,sels=prefix[consumed];answer=sels['SC']
                _,_,unique,count=votes([r['answer'] for r in cs])
                from .core import rwc
                quality_winner,quality_margin=rwc([r['answer'] for r in cs],prefix[consumed][1]['certainty' if dataset=='MATH' else 'visconf'])
                ok=next(r['correct'] for r in cs if r['answer']==answer)
                final=prefix[32][2]['SC'];final_ok=next(r['correct'] for r in c if r['answer']==final)
                policies.append(dict(order=oi,family=family,tau=tau,gamma=gamma,N=consumed,answer=answer,
                                     correct=bool(ok),tokens=sum(r['tokens'] for r in cs),
                                     leading_fraction=count/consumed,unique_leader=unique,rwc_margin=quality_margin,
                                     selector_agreement=quality_winner==answer,candidate_ids=order[:consumed],
                                     premature_recoverable=consumed<32 and not ok and bool(final_ok)))
    write(path,dict(dataset=dataset,sample_id=sid,rows=rows,policies=policies,signal=signal,trajectory=trajectory,
                    full_correct_fraction=float(correct.mean()),orders=q['orders']))
    return sid


def run_offline(root,workers,progress):
    for dataset in DATASETS:
        split=read(root/'splits'/f'{dataset}.json');ids=split['dev']+split['eval']
        with concurrent.futures.ProcessPoolExecutor(workers,mp_context=mp.get_context('spawn')) as pool:
            futures=[pool.submit(one_question,(root,dataset,sid)) for sid in ids]
            for i,future in enumerate(concurrent.futures.as_completed(futures),1):
                sid=future.result()
                progress.update('offline '+dataset,i,len(ids),sid)
    aggregate(root,progress)


def bootstrap(delta):
    rng=np.random.default_rng(6304);x=np.asarray(delta,float)
    values=np.mean(x[rng.integers(0,len(x),size=(1000,len(x)))],axis=1)
    return np.quantile(values,[.025,.975]).tolist()


def aggregate(root,progress):
    out=root/'evidence';out.mkdir(exist_ok=True)
    summaries=[];diffs=[];adaptive=[];signals=[];trajectories=[];frozen={}
    for dataset in DATASETS:
        progress.update('aggregate '+dataset,0,1)
        split=read(root/'splits'/f'{dataset}.json');rows=[];pol=[]
        for part in ['dev','eval']:
            for sid in split[part]:
                obj=read(root/'offline'/dataset/(sid.replace(':','_')+'.json'))
                rows.extend(dict(r,sample_id=sid,split=part) for r in obj['rows'])
                pol.extend(dict(r,sample_id=sid,split=part,full_correct_fraction=obj['full_correct_fraction']) for r in obj['policies'])
                if part=='eval':
                    signals.extend(dict(r,dataset=dataset,sample_id=sid) for r in obj['signal'])
                    trajectories.extend(dict(r,dataset=dataset,sample_id=sid) for r in obj['trajectory'])
        df=pd.DataFrame(rows);pf=pd.DataFrame(pol)
        df.to_parquet(out/f'{dataset}_per_question_orders.parquet',index=False)
        pf.to_parquet(out/f'{dataset}_adaptive_all_settings.parquet',index=False)
        # Average orders inside each question before averaging questions or bootstrapping.
        numeric=['correct','oracle','tokens','distinct','sampling_failure','selection_failure']
        qavg=df.groupby(['split','sample_id','N','method'])[numeric].mean().reset_index()
        summary=qavg.groupby(['split','N','method'])[numeric].mean().reset_index()
        summaries.extend(dict(r,dataset=dataset) for r in summary.to_dict('records'))
        ev=qavg[qavg.split=='eval'];wide=ev.pivot(index=['sample_id','N'],columns='method',values='correct')
        for n in BUDGETS:
            w=wide.xs(n,level='N')
            for a,b in [('SC','FirstAns'),('logp','SC'),('certainty','SC'),('certainty_RWC','certainty'),('shortest','SC')]+(
                 [('visconf','vision'),('visconf_RWC','visconf'),('visconf_RWC','certainty_RWC'),
                  ('tokenfusion','visconf'),('tokenfusion_RWC','visconf_RWC')] if dataset=='MathVista' else []):
                delta=w[a]-w[b];lo,hi=bootstrap(delta)
                diffs.append(dict(dataset=dataset,N=n,method=a,reference=b,difference=float(delta.mean()),low=lo,high=hi))
        baseline=float(summary.query("split=='dev' and N==32 and method=='SC'").iloc[0]['correct'])
        frozen[dataset]={}
        for family in ['agreement','quality']:
            dev=pf[(pf.split=='dev')&(pf.family==family)]
            options=dev.groupby(['tau','gamma'])[['correct','tokens']].mean().reset_index()
            options=options[options.correct>=baseline-.01]
            fixed_dev=float(summary.query("split=='dev' and N==32 and method=='SC'").iloc[0]['tokens'])
            choices=[dict(tau=None,gamma=None,correct=baseline,tokens=fixed_dev)] + options.to_dict('records')
            chosen=min(choices,key=lambda r:(r['tokens'],-r['correct'],r['tau'] if r['tau'] is not None else 2,r['gamma'] or 0))
            frozen[dataset][family]=chosen
        # Freeze all settings before extracting held-out controller outcomes.
        write(root/'frozen_policies.json',frozen)
        fixed=ev[(ev.N==32)&(ev.method=='SC')].set_index('sample_id')['correct']
        for family,chosen in frozen[dataset].items():
            if chosen['tau'] is None:
                selected=df[(df.split=='eval')&(df.N==32)&(df.method=='SC')].copy()
                selected['premature_recoverable']=False
            else:
                selected=pf[(pf.split=='eval')&(pf.family==family)&(pf.tau==chosen['tau'])&(pf.gamma==chosen['gamma'])].copy()
            selected.to_parquet(out/f'{dataset}_{family}_selected.parquet',index=False)
            if 'full_correct_fraction' in selected:
                retrospective=selected.copy()
                retrospective['full_pool_correctness_bin']=pd.cut(retrospective.full_correct_fraction,
                      bins=[-.001,0,.25,.5,.75,1.],include_lowest=True).astype(str)
                retrospective.groupby('full_pool_correctness_bin')[['N','correct','tokens','leading_fraction','premature_recoverable']].mean().to_csv(out/f'{dataset}_{family}_retrospective.csv')
            avg=selected.groupby('sample_id')[['correct','tokens','N','premature_recoverable']].mean()
            delta=avg.correct-fixed;lo,hi=bootstrap(delta)
            adaptive.append(dict(dataset=dataset,family=family,**chosen,eval_accuracy=float(avg.correct.mean()),
                                 eval_tokens=float(avg.tokens.mean()),eval_rollouts=float(avg.N.mean()),
                                 accuracy_difference_fixed32=float(delta.mean()),low=lo,high=hi,
                                 recoverable_early_stop_rate=float(avg.premature_recoverable.mean()),
                                 incorrect_early_stop_rate=float(((selected.N<32)&~selected.correct.astype(bool)).mean()),
                                 stopping_distribution=selected.N.value_counts(normalize=True).sort_index().to_dict()))
    pd.DataFrame(summaries).to_csv(out/'method_comparison.csv',index=False)
    pd.DataFrame(diffs).to_csv(out/'paired_bootstrap.csv',index=False)
    pd.DataFrame(signals).to_csv(out/'signal_per_question.csv',index=False)
    pd.DataFrame(trajectories).to_csv(out/'confidence_vision_per_rollout.csv',index=False)
    write(out/'adaptive_summary.json',adaptive)
    write(root/'offline_complete.json',{'datasets':list(DATASETS),'bootstrap_resamples':1000})
