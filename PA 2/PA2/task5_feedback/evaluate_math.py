from __future__ import annotations

import argparse
import gc
import json
import time
import torch
from common.data import load_yaml, read_jsonl, write_jsonl, prompt_messages
from common.generation import batch_generate
from common.models import load_policy, load_tokenizer
from task5_feedback.analysis import POLICIES, output_dir, save_json, fingerprint, response_metrics, summarize_math, verifier_preference
from task5_feedback.rlaif import PairwiseAIJudge


def policy_specs(cfg):
    return {name: cfg['policies'].get(name) for name in POLICIES}


def dataset_path(cfg, dataset):
    return cfg['paths'][{'gsm': 'gsm_eval', 'transfer': 'math_transfer_eval'}[dataset]]


def load_math_evaluation(config_path, dataset):
    cfg = load_yaml(config_path)
    return cfg, read_jsonl(dataset_path(cfg, dataset)), load_tokenizer(cfg['base_model'])


def load_frozen_policy(cfg, name):
    return load_policy(cfg, adapter_path=policy_specs(cfg)[name], trainable=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/feedback.yaml')
    ap.add_argument('--dataset', choices=['gsm', 'transfer'], default='gsm')
    ap.add_argument('--batch-size', type=int, default=4)
    ap.add_argument('--overwrite', action='store_true')
    args = ap.parse_args()
    if args.batch_size < 1:
        ap.error('--batch-size must be positive')
    cfg, rows, tokenizer = load_math_evaluation(args.config, args.dataset)
    if not rows or (args.dataset == 'transfer' and len(rows) != 100):
        raise ValueError('Expected nonempty fixed evaluation set and exactly 100 transfer examples')
    root = output_dir(cfg)
    signature = fingerprint({'rows': rows, 'base': cfg['base_model'], 'policies': policy_specs(cfg),
                             'seed': cfg['seed'], 'cap': cfg['math_max_new_tokens'], 'prompt_cap': cfg.get('math_max_prompt_length', 1024), 'decoding': 'greedy'})
    responses = []
    for name in POLICIES:
        path = root / f'{args.dataset}_{name}_responses.jsonl'
        completed = read_jsonl(path) if path.exists() and not args.overwrite else []
        if len(completed) > len(rows) or any(r.get('signature') != signature or r.get('index') != i or r.get('policy') != name for i, r in enumerate(completed)):
            raise ValueError(f'Incompatible response file {path}; use --overwrite')
        if len(completed) < len(rows):
            torch.manual_seed(int(cfg['seed']))
            model = load_frozen_policy(cfg, name)
            for start in range(len(completed), len(rows), args.batch_size):
                batch = rows[start:start + args.batch_size]
                generated = batch_generate(model, tokenizer, [prompt_messages(r) for r in batch],
                                           int(cfg.get('math_max_prompt_length', 1024)), int(cfg['math_max_new_tokens']), do_sample=False)
                for j, (row, text) in enumerate(zip(batch, generated['responses'])):
                    completed.append({'signature': signature, 'index': start + j, 'policy': name,
                                      'question': row['question'], 'gold_final': row['gold_final'], 'response': text,
                                      **response_metrics(text, row['gold_final'], generated['response_lengths'][j], generated['truncated'][j])})
                write_jsonl(path, completed)
                print(f'{args.dataset} {name}: {len(completed)}/{len(rows)}', flush=True)
            del model, generated
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        responses.extend(completed)
    print(f'{args.dataset}: all saved responses ready; loading AI judge...', flush=True)
    judge = PairwiseAIJudge(cfg, root / 'judge_cache.json')
    start_time = time.perf_counter()
    initial_cache_size = len(judge.cache)
    indexed = {(r['policy'], r['index']): r for r in responses}
    pairs = []
    for name in ('rlvr', 'rlaif'):
        for i, row in enumerate(rows):
            a, b = indexed[name, i], indexed['sft', i]
            pref = judge.compare(row['question'], a['response'], b['response'])
            pairs.append({'index': i, 'policy': name, 'judge_preference': pref,
                          'verifier_preference': verifier_preference(a['exact_reward'], b['exact_reward']),
                          'policy_reward': a['exact_reward'], 'sft_reward': b['exact_reward']})
            if (i + 1) % 25 == 0 or i + 1 == len(rows):
                print(f'{args.dataset} judge {name} vs SFT: {i + 1}/{len(rows)}', flush=True)
        print(f'{args.dataset}: judged {name} against SFT', flush=True)
    write_jsonl(root / f'{args.dataset}_pairs.jsonl', pairs)
    save_json(root / f'{args.dataset}_summary.json', {'dataset': args.dataset, 'signature': signature,
              'config': cfg, 'policies': summarize_math(responses, pairs),
              'judge_cost': {'requested_pairs': len(pairs), 'new_cache_entries': len(judge.cache) - initial_cache_size,
                             'elapsed_seconds': time.perf_counter() - start_time}})


if __name__ == '__main__':
    main()
