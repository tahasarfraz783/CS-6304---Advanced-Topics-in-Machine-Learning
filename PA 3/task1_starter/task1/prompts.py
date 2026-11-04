"""Convert course YAML to exact chat messages; never execute its judge metadata."""
from pathlib import Path
import yaml
from .common import read_json, write_json


def normalize_prompts(path):
    source = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(source, list) or len(source) != 24:
        raise ValueError("Expected the supplied list of 24 course entries.")
    plain = [e["id"] for e in source if not e["id"].endswith(("_json", "_template"))]
    if len(plain) != 8 or len(set(plain)) != 8:
        raise ValueError("Expected eight distinct plain questions.")
    result, seen = [], set()
    for entry in source:
        entry_id = entry["id"]
        fmt = "json" if entry_id.endswith("_json") else "template" if entry_id.endswith("_template") else "plain"
        question_id = entry_id[:-(len(fmt) + 1)] if fmt != "plain" else entry_id
        if question_id not in plain or (question_id, fmt) in seen:
            raise ValueError("Unrecognized or duplicate question/format.")
        seen.add((question_id, fmt))
        prompts = entry.get("paraphrases")
        if not isinstance(prompts, list) or len(prompts) != 1 or not isinstance(prompts[0], str):
            raise ValueError("Expected one exact prompt per course entry.")
        messages = []
        if "system" in entry:
            if not isinstance(entry["system"], str):
                raise ValueError("System prompt must be text.")
            messages.append({"role": "system", "content": entry["system"]})
        messages.append({"role": "user", "content": prompts[0]})
        result.append({"source_id": entry_id, "question_id": question_id, "format": fmt,
                       "prompt": prompts[0], "messages": messages,
                       "annotate": question_id in {plain[0], plain[-1]}})
    if len(seen) != 24 or sum(r["annotate"] for r in result) != 6:
        raise ValueError("Incomplete format groups or annotation subset.")
    return result


def prepare_prompts(path):
    rows = normalize_prompts(path)
    write_json(Path(path).with_name("qualitative.json"), rows)
    return rows


def qualitative_inputs(c):
    path = Path(c["qualitative_file"])
    normalized = path.with_name("qualitative.json")
    if not path.exists() or not normalized.exists():
        raise FileNotFoundError("Place the course YAML in inputs and run python prepare_prompts.py.")
    expected = normalize_prompts(path)
    if read_json(normalized) != expected:
        raise ValueError("qualitative.json differs from the course YAML. Run python prepare_prompts.py.")
    return expected
