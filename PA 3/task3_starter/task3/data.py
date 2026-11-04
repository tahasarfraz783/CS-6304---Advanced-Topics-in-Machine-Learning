import concurrent.futures
import multiprocessing as mp
import hashlib
import importlib.metadata
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
from .common import read, write, sha
from .core import split_ids, orders_for
from .scoring import group_and_grade, VERSION
from .scoring import TIMEOUT_EVENTS

DATASETS={'MATH':'qwen25-math','MathVista':'qwen25vl-mathvista'}
KEYS=['dataset','sample_id','rollout_id']


def qpath(root,dataset,sid):
    return Path(root)/'prepared'/dataset/(hashlib.sha256(sid.encode()).hexdigest()[:20]+'.pkl')


def load_question(root,dataset,sid):
    with qpath(root,dataset,sid).open('rb') as f:return pickle.load(f)


def _prepare_question(job):
    root,dataset,sid,rows,meta,index=job
    path=qpath(root,dataset,sid)
    if path.exists():return sid
    assert len(rows)==32 and [r['rollout_id'] for r in rows]==list(range(32))
    assert len({str(r['gold_answer']) for r in rows})==1
    assert len({str(r['question_text']) for r in rows})==1
    TIMEOUT_EVENTS.clear()
    groups,correct=group_and_grade([r['extracted_answer'] for r in rows],rows[0]['gold_answer'],dataset,meta)
    candidates=[]
    for r,answer,ok in zip(rows,groups,correct):
        n=int(r['n_generated_text_tokens']);assert n>0
        arrays={k:np.asarray(r[k],dtype=np.float64) for k in ['logp','kl_u_p']}
        assert len(r['generated_token_ids'])==n
        for a in arrays.values():assert len(a)==n and np.isfinite(a).all()
        assert np.all(arrays['logp']<=1e-5) and np.all(arrays['kl_u_p']>=-1e-5)
        c={'id':int(r['rollout_id']),'answer':answer,'correct':bool(ok),'tokens':n,
           'L':float(arrays['logp'].mean()),'K':float(arrays['kl_u_p'].mean()),'kl':arrays['kl_u_p'],
           'extracted':r['extracted_answer'],'text':r['generated_text'],'truncated':bool(r['hit_max_new_tokens'])}
        if dataset=='MathVista':
            masses=[np.asarray(r[k],dtype=np.float64) for k in ['img_attn_total','prompt_text_attn_total','generated_text_attn_total']]
            for a in masses:assert len(a)==n and np.isfinite(a).all() and np.all(a>=0)
            assert np.array_equal(r['attention_preceding_counts'],np.arange(n))
            denom=sum(masses);assert np.all(denom>0)
            c['v']=masses[0]/denom
        candidates.append(c)
    obj={'dataset':dataset,'sample_id':sid,'question':rows[0]['question_text'],'gold':rows[0]['gold_answer'],
         'candidates':candidates,'orders':orders_for(index),'scoring_timeout_pair_hashes':list(TIMEOUT_EVENTS)}
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    with temp.open('wb') as f:pickle.dump(obj,f,protocol=5)
    temp.replace(path)
    return sid


def input_manifest(inputs):
    paths=[inputs/'README.MD',inputs/'mathvista_testmini.json']
    for folder in DATASETS.values():paths.extend(sorted((inputs/folder).glob('*.parquet')))
    for dataset,folder in DATASETS.items():
        for name in ['generations.parquet','probability_metrics.parquet']+(['attention_metrics.parquet'] if dataset=='MathVista' else []):
            if not (inputs/folder/name).exists():raise FileNotFoundError(inputs/folder/name)
    observed={p.relative_to(inputs).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in paths}
    expected=inputs/'expected_files.json'
    if expected.exists():
        reference=read(expected)
        if observed!=reference:raise ValueError('Input bytes differ from the verified public dataset snapshot')
    return observed


def prepare(inputs,root,workers,progress):
    manifest=input_manifest(inputs)
    identity={'files':manifest,'scorer':VERSION,'math_verify':importlib.metadata.version('math-verify')}
    assert identity['math_verify']=='0.9.0'
    prior=root/'input_identity.json'
    if prior.exists() and read(prior)!=identity:raise RuntimeError('Inputs/scorer changed: choose a new output directory')
    write(prior,identity)
    metadata=read(inputs/'mathvista_testmini.json')
    for dataset,folder in DATASETS.items():
        progress.update('join '+dataset,0,1000)
        base=inputs/folder
        df=pd.read_parquet(base/'generations.parquet')
        observed=dict(retained_tokens=int(df.n_generated_text_tokens.sum()),capped=int(df.hit_max_new_tokens.sum()),
                      missing_extractions=int(df.extracted_answer.isna().sum()))
        expected={'MATH':dict(retained_tokens=20742094,capped=523,missing_extractions=521),
                  'MathVista':dict(retained_tokens=8961703,capped=487,missing_extractions=3032)}[dataset]
        assert observed==expected,(dataset,observed,expected)
        write(root/'validation'/f'{dataset}.json',dict(rows=len(df),**observed,readme_totals_match=True))
        for name in ['probability_metrics.parquet']+(['attention_metrics.parquet'] if dataset=='MathVista' else []):
            other=pd.read_parquet(base/name)
            if name.startswith('attention'):other=other.rename(columns={'n_generated_text_tokens':'attention_preceding_counts'})
            assert len(other)==32000 and not other.duplicated(KEYS).any()
            df=df.merge(other,on=KEYS,how='outer',validate='one_to_one',indicator=True)
            assert (df.pop('_merge')=='both').all()
        assert len(df)==32000 and not df.duplicated(KEYS).any()
        df['sample_id']=df['sample_id'].astype(str)
        ids=sorted(df['sample_id'].unique());assert len(ids)==1000
        split=split_ids(ids);write(root/'splits'/f'{dataset}.json',split)
        jobs=((root,dataset,sid,group.sort_values('rollout_id').to_dict('records'),metadata.get(sid),ids.index(sid))
              for sid,group in df.groupby('sample_id',sort=True))
        with concurrent.futures.ProcessPoolExecutor(workers,mp_context=mp.get_context('spawn')) as pool:
            futures={pool.submit(_prepare_question,job):job[2] for job in jobs}
            for i,future in enumerate(concurrent.futures.as_completed(futures),1):
                sid=future.result()
                futures.pop(future)
                detail=sid
                if 0<len(futures)<=10:detail+='; pending '+', '.join(sorted(futures.values()))
                progress.update('prepare '+dataset,i,1000,detail)
        del df
    scoring=[]
    for dataset in DATASETS:
        split=read(root/'splits'/f'{dataset}.json')
        for sid in split['dev']+split['eval']:
            q=load_question(root,dataset,sid)
            scoring.append(dict(dataset=dataset,sample_id=sid,timeout_count=len(q.get('scoring_timeout_pair_hashes',[]))))
    pd.DataFrame(scoring).to_csv(root/'validation'/'scorer_timeouts.csv',index=False)
    write(root/'prepared_complete.json',identity)
