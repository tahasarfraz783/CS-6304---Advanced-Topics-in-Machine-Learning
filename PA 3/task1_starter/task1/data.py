"""Prepare once; every method reuses exactly these tokenized examples and IDs."""
import hashlib
import re
import unicodedata
from pathlib import Path

import numpy as np
import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer

from .common import fingerprint, read_json, write_json, write_jsonl


def normalize_question(text):
    # Explicit, reproducible policy; retain punctuation to avoid over-collapsing math.
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def encode_example(tokenizer, question, answer):
    messages = [{"role": "user", "content": question}]
    prefix = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
    )
    # Append the actual response to the same non-thinking assistant prefix used at inference.
    # Qwen's im_end is the assistant end-of-turn token. Do not train on template newlines.
    response = tokenizer.encode(answer, add_special_tokens=False)
    end_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if end_id is None or end_id == tokenizer.unk_token_id:
        raise ValueError("Expected Qwen end-of-turn token was not found.")
    ids = prefix + response + [end_id]
    return {"input_ids": ids, "labels": [-100] * len(prefix) + response + [end_id]}


def collate(rows, pad_id):
    length = max(len(row["input_ids"]) for row in rows)
    ids, labels, masks = [], [], []
    for row in rows:
        missing = length - len(row["input_ids"])
        ids.append(row["input_ids"] + [pad_id] * missing)
        labels.append(row["labels"] + [-100] * missing)
        masks.append([1] * len(row["input_ids"]) + [0] * missing)
    return {"input_ids": torch.tensor(ids), "labels": torch.tensor(labels),
            "attention_mask": torch.tensor(masks)}


def prepare(c, root, progress=None):
    root = Path(root)
    out = root / "prepared"
    if (out / "manifest.json").exists():
        if read_json(out / "manifest.json")["config_hash"] != fingerprint(c):
            raise ValueError("Prepared data belongs to a different configuration. Use a new output directory.")
        print("Reusing frozen preparation.")
        if progress:
            progress.phase("reusing prepared model, training examples, and probe IDs")
        return
    out.mkdir(parents=True, exist_ok=True)
    if progress:
        progress.phase("download/load and freeze starting model")
    tokenizer = AutoTokenizer.from_pretrained(c["model"])
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(c["model"], torch_dtype=torch.float32)
    revision = getattr(model.config, "_commit_hash", None)
    model.save_pretrained(out / "base")
    tokenizer.save_pretrained(out / "base")
    del model

    if progress:
        progress.phase("loading GSM8K and MetaMath datasets")
    gsm = load_dataset("openai/gsm8k", "main", split="test")
    test_questions = {normalize_question(row["question"]) for row in gsm}
    source = load_dataset("meta-math/MetaMathQA", split="train")
    kept, excluded = [], {"empty": 0, "test_match": 0, "too_long": 0}
    if progress:
        progress.phase("selecting eligible training examples", c["examples"], "eligible examples")
    for source_id, row in enumerate(source):
        question, answer = row.get("query", ""), row.get("response", "")
        if not question or not answer or not question.strip() or not answer.strip():
            excluded["empty"] += 1
            continue
        if any(normalize_question(row.get(key)) in test_questions for key in ("query", "original_question")):
            excluded["test_match"] += 1
            continue
        encoded = encode_example(tokenizer, question, answer)
        if len(encoded["input_ids"]) > c["max_length"]:
            excluded["too_long"] += 1
            continue
        kept.append({"source_id": source_id, **encoded})
        if progress and (len(kept) == 1 or len(kept) % 100 == 0 or len(kept) == c["examples"]):
            progress.advance(len(kept), source_rows_examined=source_id+1, exclusions=dict(excluded))
        if len(kept) == c["examples"]:
            break
    if len(kept) != c["examples"]:
        raise ValueError("Not enough eligible examples.")
    write_jsonl(out / "training.jsonl", kept)

    # Task documents and their native formatting are shared with benchmark evaluation.
    from lm_eval.tasks import TaskManager, get_task_dict
    tasks = get_task_dict(["gsm8k_cot", "hellaswag"], task_manager=TaskManager())
    rng = np.random.default_rng(c["seed"])
    probes = []
    if progress:
        progress.phase("selecting fixed diagnostic prompts", 64, "prompts")
    for task_name, dataset in (("gsm8k_cot", "math"), ("hellaswag", "non_math")):
        task = tasks[task_name]
        docs = list(task.test_docs() if task.has_test_docs() else task.validation_docs())
        for doc_id in rng.choice(len(docs), 32, replace=False).tolist():
            prompt = task.doc_to_text(docs[doc_id])
            if dataset == "math":
                prompt = tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}], tokenize=False,
                    add_generation_prompt=True, enable_thinking=False,
                )
            probes.append({"task": task_name, "domain": dataset, "doc_id": doc_id, "prompt": prompt})
            if progress:
                progress.advance(len(probes))
    write_jsonl(out / "probes.jsonl", probes)
    write_json(out / "manifest.json", {
        "config_hash": fingerprint(c), "model_commit": revision,
        "metamath_fingerprint": source._fingerprint, "gsm8k_fingerprint": gsm._fingerprint,
        "retained": len(kept), "excluded_before_cutoff": excluded,
        "training_sha256": hashlib.sha256((out / "training.jsonl").read_bytes()).hexdigest(),
        "normalization": "Unicode NFKC, casefold, collapse whitespace, preserve punctuation",
    })


def qualitative_inputs(c):
    from .prompts import qualitative_inputs as load_exact_prompts
    return load_exact_prompts(c)
