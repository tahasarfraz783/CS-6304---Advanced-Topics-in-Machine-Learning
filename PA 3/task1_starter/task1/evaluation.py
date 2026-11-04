"""Evaluate checkpoint copies; never change the weights or RNG of a training process."""
import gc
import hashlib
import json
import os
import time
from pathlib import Path

import torch
from lm_eval.models.huggingface import HFLM

from .common import read_json, read_jsonl, write_json, write_jsonl
from .data import qualitative_inputs
from .model import (LowRankLinear, attach_adapters, load_base, load_tokenizer,
                    merge_into_fresh, restore_trainable, seed_all)


def evaluation_batch_size(c, root):
    """Freeze a runtime-only batch size without invalidating prepared training data."""
    path = Path(root) / "evaluation_runtime.json"
    saved = read_json(path) if path.exists() else None
    batch = int(os.environ.get("PA3_EVAL_BATCH_SIZE", str(saved["batch_size"] if saved else c.get("eval_batch_size", 1))))
    if not 1 <= batch <= 32:
        raise ValueError("Evaluation batch size must be between 1 and 32.")
    if saved and saved["batch_size"] != batch:
        raise ValueError("Evaluation batch size is frozen for this experiment. Use a separate output directory to change it.")
    if not saved:
        if list((Path(root) / "evaluations").glob("*/complete.json")):
            raise ValueError("This output already has completed evaluations from the old runtime. Use a separate output directory; do not silently mix evaluation settings.")
        write_json(path, {"schema": "batched-v3", "batch_size": batch,
                         "training_batch_unchanged": True, "scoring": "stock harness; FP16 greedy generation",
                         "note": "Batch size can affect FP16 rounding. Apply consistently to all conditions."})
    return batch


class LoggedHFLM(HFLM):
    """Use stock scoring/stopping, but retain raw generation lengths and cap flags."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generation_records = {}
        self.current_doc = None

    def generate_until(self, requests, disable_tqdm=False):
        # Batch one for traceability. Candidate-likelihood tasks still use normal batching.
        # Cache each completed answer, not just an entire finished benchmark.
        path = getattr(self, "generation_cache_path", None)
        cache = {}
        if path and Path(path).exists():
            contents = Path(path).read_text(encoding="utf-8")
            lines = contents.splitlines()
            for index, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    if index != len(lines) - 1:
                        raise ValueError("Generation cache is corrupted before its final line.")
                    # Preserve a crash-interrupted final record separately before repairing.
                    Path(str(path) + ".interrupted").write_text(line, encoding="utf-8")
                    Path(path).write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
                    continue
                cache[record["key"]] = record
            if contents and not contents.endswith("\n"):
                # A valid last JSON record may have survived without its newline.
                # Ensure the next appended record cannot concatenate onto it.
                with Path(path).open("a", encoding="utf-8") as stream:
                    stream.write("\n")
        batch_size = int(getattr(self, "generation_batch_size", self.batch_size))
        recipes = {json.dumps(request.args[1], sort_keys=True, default=str) for request in requests}
        if len(recipes) > 1:
            raise ValueError("Traced generation expects one shared generation recipe per task call.")
        answers = [None] * len(requests)
        pending, reused = [], 0
        started = time.monotonic()
        progress = getattr(self, "progress", None)
        if progress:
            progress.phase("GSM8K batched answer generation", len(requests), "answers")
        for index, request in enumerate(requests):
            # Batch size/version is part of cache identity. Do not silently mix old
            # batch-one FP16 outputs into the new controlled batch-eight experiment.
            signature = json.dumps(["batched-v3", batch_size, int(request.doc_id), request.args],
                                   sort_keys=True, default=str)
            key = hashlib.sha256(signature.encode()).hexdigest()
            if key in cache:
                record = cache[key]
                answers[index] = record["answer"]
                self.generation_records[int(request.doc_id)] = record["metadata"]
                reused += 1
            else:
                pending.append((index, request, key))
        # Greedy decoding has no sampling RNG. Sort by prompt length for padding
        # efficiency, then restore responses to original request order below.
        pending.sort(key=lambda item: -len(self.tok_encode(item[1].args[0])))
        print(f"GSM8K: {len(requests)} questions, batch size {batch_size}, {reused} cached answers", flush=True)
        completed = reused
        if progress:
            progress.advance(completed, cache_reused=reused, batch_size=batch_size)
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start+batch_size]
            batch_requests = [item[1] for item in batch]
            self._active_docs = {}
            for _, request, _ in batch:
                ids = tuple(self.tok_encode(request.args[0]))
                self._active_docs.setdefault(ids, []).append(int(request.doc_id))
            self.current_doc = int(batch_requests[0].doc_id)
            if progress:
                progress.detail(current_doc_ids=[int(r.doc_id) for r in batch_requests],
                                current_doc_id=self.current_doc, current_generation_steps=0,
                                batch_size=len(batch_requests))
            generated = super().generate_until(batch_requests, disable_tqdm=True)
            if len(generated) != len(batch):
                raise RuntimeError("Batched generation returned the wrong number of answers.")
            for (original_index, request, key), answer in zip(batch, generated):
                doc_id = int(request.doc_id)
                if doc_id not in self.generation_records:
                    raise RuntimeError(f"Missing generation metadata for question {doc_id}.")
                record = {"key": key, "doc_id": doc_id, "answer": answer,
                          "metadata": self.generation_records[doc_id]}
                if path:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    with Path(path).open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                cache[key] = record
                answers[original_index] = answer
                completed += 1
            if progress:
                fresh = completed-reused
                elapsed = time.monotonic()-started
                progress.advance(completed, cache_reused=reused,
                    remaining_seconds_estimate=(len(requests)-completed)*elapsed/fresh if fresh >= batch_size else None)
            else:
                print(f"GSM8K: {completed}/{len(requests)} answers saved", flush=True)
        return answers

    def loglikelihood(self, requests, disable_tqdm=False):
        progress = getattr(self, "progress", None)
        if not progress:
            return super().loglikelihood(requests, disable_tqdm=disable_tqdm)
        progress.phase(f"{getattr(self, 'active_task', 'benchmark')} candidate-likelihood scoring",
                       len(requests), "candidate scores")
        result = []
        for start in range(0, len(requests), 64):
            result.extend(super().loglikelihood(requests[start:start+64], disable_tqdm=True))
            progress.advance(min(start+64, len(requests)))
        return result

    def _model_generate(self, context, max_length, stop, **kwargs):
        progress = getattr(self, "progress", None)
        handle = None
        steps = 0
        if progress:
            def observed_forward(module, inputs, output):
                nonlocal steps
                steps += 1
                # Observe completed forward calls; do not change tokens or stopping rules.
                progress.detail(current_generation_steps=steps)
            handle = self.model.register_forward_hook(observed_forward)
        try:
            tokens = super()._model_generate(context, max_length, stop, **kwargs)
        finally:
            if handle is not None:
                handle.remove()
        attention = kwargs.get("attention_mask")
        cap = max_length-context.shape[1]
        eos = self.model.generation_config.eos_token_id
        eos = set(eos if isinstance(eos, list) else [eos])
        context_rows = context.tolist()
        masks = attention.tolist() if attention is not None else None
        continuations = tokens[:, context.shape[1]:].tolist()
        for row in range(tokens.shape[0]):
            prompt_ids = [token for token, keep in zip(context_rows[row], masks[row]) if keep] if masks is not None else context_rows[row]
            doc_ids = self._active_docs.get(tuple(prompt_ids))
            if not doc_ids:
                raise RuntimeError("Could not map a padded/sorted generation row back to its question; refusing mislabelled results.")
            continuation = continuations[row]
            # Each row can finish before its batch peers. Ignore subsequent padding
            # when logging token counts; leave returned tokens untouched for stock
            # harness decoding, stopping, and filters.
            end = next((i+1 for i, token in enumerate(continuation) if token in eos), len(continuation))
            candidate = continuation[:end]
            def contains_stop(prefix):
                text = self.tokenizer.decode(prefix, skip_special_tokens=False)
                return any(value and value in text for value in stop)
            stopped = end < len(continuation) or (bool(candidate) and candidate[-1] in eos)
            if contains_stop(candidate):
                low, high = 1, len(candidate)
                while low < high:
                    middle = (low+high)//2
                    if contains_stop(candidate[:middle]):
                        high = middle
                    else:
                        low = middle+1
                candidate = candidate[:low]
                stopped = True
            metadata = {"generated_tokens": len(candidate), "hit_token_cap": len(candidate) >= cap,
                        "truncated": len(candidate) >= cap and not stopped,
                        "raw_response": self.tokenizer.decode(candidate, skip_special_tokens=False)}
            for doc_id in doc_ids:
                self.generation_records[doc_id] = dict(metadata)
        return tokens


def evaluation_model(c, root, method, update):
    tokenizer = load_tokenizer(root)
    if method == "baseline":
        return load_base(c, root).eval(), tokenizer
    run = Path(root) / "runs" / method
    if method in ("full_ft", "l2sp"):
        model = load_base(c, root)
        state = torch.load(run / "checkpoints" / f"update_{update:04d}.pt", map_location="cpu", weights_only=False)
        restore_trainable(model, state["model"])
        del state
        return model.eval(), tokenizer

    exports = torch.load(run / f"adapters_{update:04d}.pt", weights_only=True)
    # Check the exported effective (already projected) factors against their merged form.
    unmerged = attach_adapters(load_base(c, root), "lora4" if method == "lora4" else "lora16", c, root)
    with torch.no_grad():
        for name, item in exports.items():
            module = unmerged.get_submodule(name)
            module.A.copy_(item["A"].to("cuda"))
            module.B.copy_(item["B"].to("cuda"))
    unmerged.eval()
    merged = merge_into_fresh(load_base(c, root), exports).eval()
    probe_rows = read_jsonl(Path(root) / "prepared/probes.jsonl")
    differences = []
    relative = []
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        # Math and non-math prompts, using actual exported factors.
        for row in [probe_rows[0], probe_rows[-1]]:
            inputs = tokenizer(row["prompt"], return_tensors="pt", add_special_tokens=False).to("cuda")
            a = unmerged(**inputs, logits_to_keep=1).logits[:, -1].float()
            b = merged(**inputs, logits_to_keep=1).logits[:, -1].float()
            differences.append((a - b).abs().max().item())
            relative.append(((a - b).norm() / (a.norm() + 1e-8)).item())
    destination = Path(root) / "evaluations" / f"{method}_{update:04d}"
    write_json(destination / "merge_check.json", {
        "max_abs_logit_differences": differences, "relative_l2_errors": relative,
        "relative_l2_tolerance": 0.02,
        "note": "FP16 merge changes rounding; inspect saved errors as well as threshold.",
    })
    if max(relative) > 0.02:
        raise ValueError("Merged/unmerged logits differ substantially. Inspect merge_check.json.")
    del unmerged, exports
    gc.collect()
    torch.cuda.empty_cache()
    return merged, tokenizer


def evaluate(c, root, method, update, smoke=False, progress=None):
    from lm_eval import simple_evaluate
    batch_size = evaluation_batch_size(c, root)
    seed_all(c["seed"])
    destination = Path(root) / "evaluations" / f"{method}_{update:04d}"
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "complete.json").exists():
        if progress:
            progress.phase("already complete; reusing evaluation")
        return
    started = time.perf_counter()
    if progress:
        progress.phase("loading evaluation model")
    model, tokenizer = evaluation_model(c, root, method, update)
    model.config.use_cache = True
    if not smoke and method != "baseline":
        if progress:
            progress.phase("exporting standalone inference model")
        export = Path(root) / "models" / f"{method}_{update:04d}"
        # Save ordinary Hugging Face models so downloads do not require recovery
        # optimizer states or this custom adapter implementation for inference.
        model.save_pretrained(export, safe_serialization=True)
        tokenizer.save_pretrained(export)
        write_json(export / "export_complete.json", {
            "method": method, "update": update, "dtype": "float16",
            "format": "standalone Hugging Face model; projected adapters already merged",
        })
    wrapper = LoggedHFLM(
        pretrained=model, tokenizer=tokenizer, batch_size=batch_size,
        enable_thinking=False, max_length=model.config.max_position_embeddings,
    )
    wrapper.generation_cache_path = destination / f"gsm8k_generation_b{batch_size}_v3.jsonl"
    wrapper.progress = progress
    all_scores = {}
    expected = {"gsm8k_cot": 1319, "hellaswag": 10042, "boolq": 3270, "arc_easy": 2376}
    for task, chat in [("gsm8k_cot", True), ("hellaswag", False), ("boolq", False), ("arc_easy", False)]:
        tasks = [task]
        wrapper.active_task = task
        result_path = destination / f"harness_{task}.json"
        samples_path = destination / f"{task}_samples.jsonl"
        if result_path.exists() and samples_path.exists():
            from .common import read_json
            cached = read_json(result_path)
            sample_ids = {row["doc_id"] for row in read_jsonl(samples_path)}
            if len(sample_ids) == (2 if smoke else expected[task]):
                all_scores.update(cached["results"])
                print(f"[REUSE] Completed {task} scores and per-example outputs", flush=True)
                continue
        if progress:
            progress.phase(f"preparing {task} prompts/requests (generation has not finished)")
        kwargs = dict(
            model=wrapper, tasks=tasks, num_fewshot=0, batch_size=batch_size,
            apply_chat_template=chat, log_samples=True,
            random_seed=c["seed"], numpy_random_seed=c["seed"],
            torch_random_seed=c["seed"], fewshot_random_seed=c["seed"],
            limit=2 if smoke else None,
        )
        if chat:
            kwargs["gen_kwargs"] = "max_gen_toks=32,do_sample=False" if smoke else "max_gen_toks=1024,do_sample=False"
        result = simple_evaluate(**kwargs)
        if result is None:
            raise RuntimeError("Evaluation harness returned no results.")
        for task, samples in result.pop("samples").items():
            doc_ids = {row["doc_id"] for row in samples}
            if not smoke and len(doc_ids) != expected[task]:
                raise ValueError(f"{task}: expected complete split ({expected[task]}), got {len(doc_ids)}")
            if task == "gsm8k_cot":
                for row in samples:
                    row.update(wrapper.generation_records[int(row["doc_id"])])
                    # Stock filtered_resps is the authoritative extracted answer.
                    row["extracted_answer"] = row.get("filtered_resps")
            write_jsonl(destination / f"{task}_samples.jsonl", samples)
        all_scores.update(result["results"])
        write_json(result_path, result)
        write_json(destination / "scores_partial.json", {"method": method, "results": all_scores,
                                                        "complete": len(all_scores) == 4})
    write_json(destination / "scores.json", {
        "method": method, "update": update, "smoke_only": smoke, "results": all_scores,
    })

    qualitative = []
    rows = qualitative_inputs(c)
    cap = 32 if smoke else 512
    existing = read_jsonl(destination / "qualitative.jsonl") if (destination / "qualitative.jsonl").exists() else []
    saved = {r["source_id"]: r for r in existing if r.get("generation_cap") == cap}
    if progress:
        progress.phase("qualitative response generation", len(rows), "responses")
    for index, row in enumerate(rows, 1):
        if row["source_id"] in saved and saved[row["source_id"]].get("messages") == row["messages"]:
            qualitative.append(saved[row["source_id"]])
            if progress:
                progress.advance(index, reused=True)
            continue
        if progress:
            progress.detail(question_id=row["source_id"])
        prompt = tokenizer.apply_chat_template(
            row["messages"], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
        with torch.inference_mode():
            tokens = model.generate(**inputs, do_sample=False, max_new_tokens=cap,
                                    pad_token_id=tokenizer.pad_token_id)
        continuation = tokens[0, inputs.input_ids.shape[1]:].tolist()
        eos = model.generation_config.eos_token_id
        eos = set(eos if isinstance(eos, list) else [eos])
        qualitative.append({**row, "condition": f"{method}_{update:04d}",
                            "generation_cap": cap,
                            "response": tokenizer.decode(continuation, skip_special_tokens=True),
                            "generated_tokens": len(continuation),
                            "truncated": len(continuation) >= cap and continuation[-1] not in eos})
        write_jsonl(destination / "qualitative.jsonl", qualitative)
        if progress:
            progress.advance(index, last_answer_tokens=len(continuation))
    write_jsonl(destination / "qualitative.jsonl", qualitative)
    write_json(destination / "complete.json", {
        "evaluation_seconds": time.perf_counter() - started, "smoke_only": smoke,
    })


def verify_evaluation(c, root, progress):
    """Short real-model batch/stock-parity/resume check; not assignment evidence."""
    from lm_eval.api.instance import Instance
    progress.phase("loading existing starting model for quick evaluation preflight")
    model, tokenizer = evaluation_model(c, root, "baseline", 0)
    batch_size = evaluation_batch_size(c, root)
    wrapper = LoggedHFLM(pretrained=model, tokenizer=tokenizer, batch_size=batch_size,
                        enable_thinking=False, max_length=model.config.max_position_embeddings)
    wrapper.progress = progress
    wrapper.generation_cache_path = Path(root) / f"evaluation_preflight/generations_b{batch_size}_v3.jsonl"
    requests = []
    questions = ["What is 2 + 2? Give a short answer.", "Reply with the word hello.",
                 "What is 5 minus 2?", "Name one color.", "What is 3 times 3?",
                 "Say yes.", "Name a fruit.", "What is 10 divided by 2? Give only the answer."]
    for i in range(max(8, batch_size)):
        question = questions[i % len(questions)]
        prompt = tokenizer.apply_chat_template([{"role": "user", "content": question}],
                  tokenize=False, add_generation_prompt=True, enable_thinking=False)
        requests.append(Instance(request_type="generate_until", doc={}, idx=0,
                        arguments=(prompt, {"max_gen_toks": 8, "do_sample": False,
                                            "until": ["<|im_end|>"]}), metadata=("preflight", i, 1)))
    answers = wrapper.generate_until(requests)
    native = HFLM(pretrained=model, tokenizer=tokenizer, batch_size=batch_size,
                  enable_thinking=False, max_length=model.config.max_position_embeddings)
    progress.phase("comparing traced batch answers with unmodified stock harness")
    if native.generate_until(requests, disable_tqdm=True) != answers:
        raise RuntimeError("Traced batched answers differ from unmodified stock HFLM. Do not start the official run.")
    # On repeat every answer must come from its durable per-answer cache.
    if wrapper.generate_until(requests) != answers:
        raise RuntimeError("Cached generation differed from its saved answer.")
    wrapper.active_task = "preflight"
    likelihood = Instance(request_type="loglikelihood", doc={}, idx=0,
                          arguments=("The answer is", " four"), metadata=("preflight", 0, 1))
    result = wrapper.loglikelihood([likelihood])
    write_json(Path(root) / "evaluation_preflight/complete.json", {
        "passed": True, "answers": answers, "likelihood": result,
        "batch_size": batch_size, "stock_harness_parity": True,
        "note": "Short eight-token outputs only; not benchmark results or a runtime estimate.",
    })
    print("EVALUATION PREFLIGHT PASSED: generation, progress, per-answer saves, resume, and likelihood scoring.", flush=True)
