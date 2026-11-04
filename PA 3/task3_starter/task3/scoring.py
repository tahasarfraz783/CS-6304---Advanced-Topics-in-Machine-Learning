"""Frozen scorer: math-verify 0.9.0 and MathVista released type rules."""
from functools import lru_cache
import os
import re
import multiprocessing as mp
import atexit
import hashlib
from .core import NO_ANSWER

VERSION='task3-scorer-v3/math-verify-0.9.0/parse-verify-8s'


def missing(answer):
    return answer is None or not str(answer).strip()


@lru_cache(maxsize=100000)
def parse_math(text):
    from math_verify import parse, LatexExtractionConfig
    return parse('\\boxed{'+text+'}', extraction_config=[LatexExtractionConfig()],
                 parsing_timeout=0)


def _compare(left,right):
    from math_verify import verify
    return bool(verify(parse_math(left),parse_math(right),timeout_seconds=0))


def _symbolic_worker(pipe):
    import logging
    logging.getLogger('math_verify').setLevel(logging.ERROR)
    while True:
        try:action,args=pipe.recv()
        except EOFError:return
        # Never send SymPy objects: unpickling can eagerly evaluate giant powers
        # in the parent and defeat process isolation.
        try:pipe.send(bool(parse_math(*args)) if action=='parse' else _compare(*args))
        except (MemoryError,OverflowError,RecursionError) as e:pipe.send({'resource_error':type(e).__name__})
        except Exception as e:pipe.send({'error':repr(e)})


_process=None
_pipe=None
TIMEOUT_EVENTS=[]


def close_worker():
    global _process,_pipe
    if _process is not None:
        _process.terminate();_process.join(timeout=2);_process=None
    if _pipe is not None:_pipe.close();_pipe=None


atexit.register(close_worker)


def _request(action,args):
    # Bound parse and verify separately. Cache parsed answers in the parent so
    # one pathological expression cannot trigger a parse timeout for every pair.
    global _process,_pipe
    if _process is None or not _process.is_alive():
        close_worker();ctx=mp.get_context('spawn');parent,child=ctx.Pipe()
        _pipe=parent;_process=ctx.Process(target=_symbolic_worker,args=(child,),daemon=True)
        _process.start();child.close()
    _pipe.send((action,args))
    if not _pipe.poll(8):
        close_worker()
        TIMEOUT_EVENTS.append(hashlib.sha256((action+repr(args)).encode()).hexdigest())
        import warnings
        warnings.warn('Symbolic '+action+' exceeded 8s; treated as non-equivalent',RuntimeWarning)
        return None
    try:result=_pipe.recv()
    except (EOFError,OSError):
        close_worker()
        TIMEOUT_EVENTS.append(hashlib.sha256((action+repr(args)).encode()).hexdigest())
        return None
    if isinstance(result,dict):
        if 'resource_error' in result:
            close_worker();TIMEOUT_EVENTS.append(hashlib.sha256((action+repr(args)).encode()).hexdigest())
            return None
        raise RuntimeError(result['error'])
    return result


@lru_cache(maxsize=100000)
def parsed(text):
    return bool(_request('parse',(str(text),)))


@lru_cache(maxsize=200000)
def math_equal(left,right):
    if missing(left) or missing(right):return False
    if not parsed(str(left)) or not parsed(str(right)):return False
    return bool(_request('verify',(str(left),str(right))))


def distance(a,b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1): cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]


def vista(answer,meta):
    if missing(answer): return NO_ANSWER
    text=str(answer).strip()
    if meta['question_type']=='multi_choice':
        choices=[str(c) for c in meta['choices']]
        letter=re.findall(r'\(([a-zA-Z])\)',text)
        if letter: text=letter[0].upper()
        letters=[chr(65+i) for i in range(len(choices))]
        if text in letters: return text
        ix=min(range(len(choices)),key=lambda i:distance(text,choices[i]))
        return letters[ix]
    try:
        if meta['answer_type']=='integer': return str(int(float(text)))
        if meta['answer_type']=='float': return str(round(float(text),int(meta['precision'])))
        if meta['answer_type']=='list': return text
    except (ValueError,TypeError,OverflowError): return NO_ANSWER
    raise ValueError('Unrecognized MathVista answer type: '+str(meta))


def group_and_grade(answers,gold,dataset,meta=None):
    # Build ALL groups before reading gold; candidate representative order is fixed rollout ID.
    representatives=[];groups=[]
    for a in answers:
        if missing(a): groups.append(NO_ANSWER);continue
        if dataset=='MathVista': groups.append(vista(a,meta));continue
        found=next((i for i,r in enumerate(representatives) if str(a)==r or math_equal(str(a),r)),None)
        if found is None: found=len(representatives);representatives.append(str(a))
        groups.append('g'+str(found))
    if dataset=='MathVista':
        target=vista(gold,meta)
        correct=[g!=NO_ANSWER and g==target for g in groups]
    else:
        labels={f'g{i}':math_equal(r,str(gold)) for i,r in enumerate(representatives)}
        correct=[labels.get(g,False) for g in groups]
    return groups,correct
