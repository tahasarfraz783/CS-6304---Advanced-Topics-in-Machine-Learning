"""Selection functions receive predictions and scores, never correctness labels."""
import numpy as np
from scipy.stats import rankdata

NO_ANSWER = 'NO_ANSWER'
BUDGETS = (1, 2, 4, 8, 16, 32)


def boxed(text):
    start = text.rfind('\\boxed{')
    if start < 0:
        return None
    start += 7
    depth = 1
    for end in range(start, len(text)):
        if text[end] == '{': depth += 1
        if text[end] == '}': depth -= 1
        if depth == 0:
            return text[start:end].strip() or None
    return None


def votes(answers, weights=None):
    result = {}
    for a, w in zip(answers, np.ones(len(answers)) if weights is None else weights):
        result[a] = result.get(a, 0.) + float(w)
    # dict insertion order is the earliest supporting rollout tie break.
    winner = max(result, key=result.get)
    ordered = sorted(result.values(), reverse=True)
    total = sum(ordered)
    margin = (ordered[0] - (ordered[1] if len(ordered)>1 else 0)) / total if total else 0.
    unique = len(ordered)==1 or ordered[0]>ordered[1]
    return winner, margin, unique, result[winner]


def rwc(answers, scores):
    n = len(answers)
    if n == 1: return answers[0], 1.
    weights = (n-rankdata(-np.asarray(scores), method='average'))/(n-1)
    winner, margin, _, _ = votes(answers, weights)
    return winner, margin


def quality(candidates):
    result = {'logp': np.array([c['L'] for c in candidates]),
              'certainty': np.array([c['K'] for c in candidates]),
              'shortest': -np.array([c['tokens'] for c in candidates])}
    if 'v' in candidates[0]:
        # Pool only the revealed prefix. NumPy linear interpolation is explicit.
        low, high = np.quantile(np.concatenate([c['kl'] for c in candidates]), [.05,.95], method='linear')
        conf = [np.clip((c['kl']-low)/max(high-low,1e-8),0,1) for c in candidates]
        result['vision'] = np.array([np.mean(c['v']) for c in candidates])
        result['visconf'] = result['vision'] * np.array([np.mean(x) for x in conf])
        result['tokenfusion'] = np.array([np.mean(x*c['v']) for x,c in zip(conf,candidates)])
    return result


def select(candidates, scores=None):
    answers = [c['answer'] for c in candidates]
    scores = quality(candidates) if scores is None else scores
    out = {'FirstAns':answers[0], 'SC':votes(answers)[0]}
    for name, values in scores.items():
        out[name] = answers[int(np.argmax(values))]
        if name in ('certainty','vision','visconf','tokenfusion'):
            out[name+'_RWC'] = rwc(answers,values)[0]
    return out


def stopping(candidates, family, tau, gamma, scores):
    answers = [c['answer'] for c in candidates]
    winner, _, unique, count = votes(answers)
    agree = unique and winner != NO_ANSWER and count/len(answers)>=tau
    if family == 'agreement': return agree
    ranked, margin = rwc(answers, scores)
    return agree and ranked==winner and margin>=gamma


def split_ids(ids):
    ids = np.array(sorted(str(x) for x in ids))
    ids = np.random.default_rng(6304).permutation(ids).tolist()
    return {'dev':ids[:200], 'eval':ids[200:], 'live':ids[200:250]}


def orders_for(index):
    rng = np.random.default_rng(np.random.SeedSequence([6304,index]))
    return [rng.permutation(32).tolist() for _ in range(10)]
