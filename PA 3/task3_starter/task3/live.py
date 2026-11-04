import importlib.metadata
import time
import numpy as np
import pandas as pd
from .common import read,write
from .core import boxed,votes
from .data import load_question
from .scoring import group_and_grade, math_equal, VERSION

MODEL='Qwen/Qwen2.5-3B-Instruct'
REVISION='aa8e72537993ba99e69dfaafa59ed015b17504d1'
INSTRUCTION='Think step by step inside <think> </think> tags, then give your final answer inside \\boxed{}.'
REVIEW='Review the solution above. Identify and correct any errors; if it is correct, retain its answer. Give your final answer inside \\boxed{}.'


def run_live(root,progress):
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer,StoppingCriteria,StoppingCriteriaList,set_seed
    if not torch.cuda.is_available():raise RuntimeError('Live comparison requires CUDA; CPU generation is disabled')
    if not torch.cuda.get_device_capability(0)[0]>=8:raise RuntimeError('Expected Ampere or newer GPU')
    torch.set_num_threads(4)
    progress.update('load pinned model',0,1,MODEL+' FP16 → CUDA')
    load_start=time.perf_counter()
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=REVISION)
    model=AutoModelForCausalLM.from_pretrained(MODEL,revision=REVISION,torch_dtype=torch.float16,
                                              attn_implementation='sdpa').to('cuda').eval()
    assert next(model.parameters()).dtype==torch.float16
    write(root/'live'/'environment.json',dict(model=MODEL,revision=REVISION,dtype='float16',batch_size=1,
          gpu=torch.cuda.get_device_name(0),vram_bytes=torch.cuda.get_device_properties(0).total_memory,
          torch=torch.__version__,transformers=importlib.metadata.version('transformers'),
          attention='sdpa',scorer=VERSION,model_loading_seconds=time.perf_counter()-load_start))
    # Fixed disposable warm-up, independent of evaluation questions. Excluded from timing.
    warm=tokenizer('Warm up.',return_tensors='pt').to('cuda')
    with torch.inference_mode():model.generate(**warm,max_new_tokens=8,do_sample=False,pad_token_id=tokenizer.eos_token_id)
    torch.cuda.synchronize()
    preflight=root/'live'/'preflight.json'
    if not preflight.exists():
        progress.update('GPU preflight',0,1,'FP16 / batch 1 / SDPA / 64-token disposable probe')
        set_seed(6304)
        probe=tokenizer('Explain how to add fractions, with two worked examples.',return_tensors='pt').to('cuda')
        torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats();probe_start=time.perf_counter()
        with torch.inference_mode():
            probe_output=model.generate(**probe,max_new_tokens=64,do_sample=True,temperature=.7,top_p=.8,top_k=20,
                       repetition_penalty=1.,use_cache=True,pad_token_id=tokenizer.eos_token_id)
        torch.cuda.synchronize();probe_seconds=time.perf_counter()-probe_start
        probe_tokens=int(probe_output.shape[-1]-probe.input_ids.shape[-1])
        write(preflight,dict(evaluation_data_used=False,output_tokens=probe_tokens,seconds=probe_seconds,
              generation_tokens_per_second=probe_tokens/probe_seconds,peak_allocated_bytes=torch.cuda.max_memory_allocated(),
              free_gpu_bytes=torch.cuda.mem_get_info()[0],dtype='float16',batch_size=1,attention='sdpa',kv_cache=True))
        del probe,probe_output
    ids=read(root/'splits'/'MATH.json')['live']

    class TokenProgress(StoppingCriteria):
        def __init__(self,start,detail):self.start=start;self.detail=detail;self.last=0
        def __call__(self,input_ids,scores,**kwargs):
            n=input_ids.shape[-1]-self.start
            if n-self.last>=32:
                progress.update('live generation',completed,250,self.detail+f' output tokens={n}')
                self.last=n
            return False

    completed=0
    for qi,sid in enumerate(ids):
        q=load_question(root,'MATH',sid)
        base=[dict(role='system',content='You are a helpful assistant.'),
              dict(role='user',content=q['question']+'\n\n'+INSTRUCTION)]
        saved={}
        # Shared first parallel response is used verbatim in refinement.
        for ci,(name,cap) in enumerate([('parallel_0',1024),('parallel_1',1024),('parallel_2',1024),('long',3072),('revision',2048)]):
            path=root/'live'/'calls'/f'{qi:02d}_{name}.json'
            if path.exists():saved[name]=read(path);completed+=1;continue
            messages=base if name!='revision' else base+[dict(role='assistant',content=saved['parallel_0']['response']),dict(role='user',content=REVIEW)]
            seed=int(np.random.SeedSequence([6304,qi,ci]).generate_state(1)[0]);set_seed(seed)
            progress.update('live generation',completed,250,f'{sid} {name} cap={cap}')
            torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
            # Includes template application, tokenization, device transfer, decode, synchronization.
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
            inputs=tokenizer(prompt,return_tensors='pt',add_special_tokens=False).to('cuda')
            with torch.inference_mode():
                output=model.generate(**inputs,max_new_tokens=cap,do_sample=True,temperature=.7,top_p=.8,top_k=20,
                     repetition_penalty=1.,use_cache=True,pad_token_id=tokenizer.eos_token_id,
                     stopping_criteria=StoppingCriteriaList([TokenProgress(inputs.input_ids.shape[-1],sid+' '+name)]))
            generated=output[0,inputs.input_ids.shape[-1]:].tolist()
            response=tokenizer.decode(generated,skip_special_tokens=True)
            torch.cuda.synchronize();elapsed=time.perf_counter()-start
            eos=model.generation_config.eos_token_id
            stops=set(eos if isinstance(eos,list) else [eos])
            retained=[t for t in generated if t not in stops]
            result=dict(sample_id=sid,name=name,seed=seed,messages=messages,prompt=prompt,response=response,
                   token_ids=generated,retained_token_ids=retained,extracted=boxed(response),cap=cap,
                   input_tokens=int(inputs.input_ids.numel()),output_tokens=len(generated),retained_tokens=len(retained),
                   truncated=len(generated)==cap and (not generated or generated[-1] not in stops),seconds=elapsed,
                   peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved())
            write(path,result);saved[name]=result;completed+=1
            del output,inputs
        progress.update('live generation',completed,250,sid+' complete')
    live_summary(root)
    del model
    torch.cuda.empty_cache()
    write(root/'live_complete.json',{'questions':50,'calls':250})


def live_summary(root):
    rows=[]
    for qi,sid in enumerate(read(root/'splits'/'MATH.json')['live']):
        q=load_question(root,'MATH',sid)
        calls={name:read(root/'live'/'calls'/f'{qi:02d}_{name}.json') for name in ['parallel_0','parallel_1','parallel_2','long','revision']}
        groups,_=group_and_grade([calls[f'parallel_{i}']['extracted'] for i in range(3)],q['gold'],'MATH')
        winner=votes(groups)[0]
        ix=groups.index(winner)
        initial=math_equal(calls['parallel_0']['extracted'],str(q['gold']))
        for strategy,names,answer in [('long',['long'],calls['long']['extracted']),
             ('parallel',['parallel_0','parallel_1','parallel_2'],calls[f'parallel_{ix}']['extracted']),
             ('refinement',['parallel_0','revision'],calls['revision']['extracted'])]:
            used=[calls[n] for n in names];ok=math_equal(answer,str(q['gold']))
            rows.append(dict(sample_id=sid,strategy=strategy,correct=ok,answer=answer,extracted=answer is not None,
                       initial_correct=initial,wrong_to_correct=not initial and ok,correct_to_wrong=initial and not ok,
                       input_tokens=sum(x['input_tokens'] for x in used),output_tokens=sum(x['output_tokens'] for x in used),
                       retained_tokens=sum(x['retained_tokens'] for x in used),seconds=sum(x['seconds'] for x in used),
                       truncated_calls=sum(x['truncated'] for x in used),calls=len(used),
                       failed_extraction_calls=sum(x['extracted'] is None for x in used),
                       peak_allocated_bytes=max(x['peak_allocated_bytes'] for x in used)))
    df=pd.DataFrame(rows);out=root/'evidence';out.mkdir(exist_ok=True)
    df.to_csv(out/'live_per_question.csv',index=False)
    summary=df.groupby('strategy').agg(accuracy=('correct','mean'),input_tokens=('input_tokens','mean'),
            output_tokens=('output_tokens','mean'),seconds=('seconds','mean'),extraction_rate=('extracted','mean'),
            truncated_calls=('truncated_calls','sum'),calls=('calls','sum'),failed_extraction_calls=('failed_extraction_calls','sum'),
            wrong_to_correct=('wrong_to_correct','sum'),correct_to_wrong=('correct_to_wrong','sum'),
            peak_allocated_bytes=('peak_allocated_bytes','max')).reset_index()
    summary['truncation_rate']=summary.truncated_calls/summary.calls
    summary['call_extraction_failure_rate']=summary.failed_extraction_calls/summary.calls
    summary.to_csv(out/'live_summary.csv',index=False)
    from .offline import bootstrap
    wide=df.pivot(index='sample_id',columns='strategy',values='correct');diffs=[]
    for a,b in [('parallel','long'),('refinement','long'),('refinement','parallel')]:
        delta=wide[a].astype(float)-wide[b].astype(float);lo,hi=bootstrap(delta)
        diffs.append(dict(method=a,reference=b,difference=float(delta.mean()),low=lo,high=hi))
    pd.DataFrame(diffs).to_csv(out/'live_paired_bootstrap.csv',index=False)
