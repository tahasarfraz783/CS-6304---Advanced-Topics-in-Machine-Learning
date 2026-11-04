"""Test the actual wrapper with a fake backend; no downloads or lm_eval installation."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest


class GenerationProgressChecks(unittest.TestCase):
    def test_completed_answers_resume_and_request_changes_invalidate_cache(self):
        class Backend:
            def __init__(self):
                self.calls = 0
                self.batch_size = 1

            def tok_encode(self, text):
                return list(text.encode())

            def generate_until(self, requests, disable_tqdm=False):
                self.calls += 1
                self.generation_records[self.current_doc] = {"generated_tokens": 3}
                return ["answer " + str(self.current_doc)]

        source = Path(__file__).resolve().parents[1] / "task1/evaluation.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LoggedHFLM")
        namespace = {"HFLM": Backend, "hashlib": hashlib, "json": json, "time": time, "Path": Path}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), "exec"), namespace)
        wrapper_class = namespace["LoggedHFLM"]
        requests = [SimpleNamespace(doc_id=i, args=(f"prompt {i}", {"max_gen_toks": 32})) for i in range(3)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.jsonl"
            first = wrapper_class()
            first.generation_cache_path = path
            answers = first.generate_until(requests)
            self.assertEqual(first.calls, 3)
            self.assertEqual(len(path.read_text().splitlines()), 3)
            with path.open("a") as stream:
                stream.write('{"interrupted":')
            second = wrapper_class()
            second.generation_cache_path = path
            self.assertEqual(second.generate_until(requests), answers)
            self.assertEqual(second.calls, 0)
            self.assertTrue(Path(str(path)+".interrupted").exists())
            self.assertEqual(second.generation_records[2]["generated_tokens"], 3)
            requests[0].args = ("changed prompt", {"max_gen_toks": 32})
            second.generate_until(requests)
            self.assertEqual(second.calls, 1)
            # A completed final record missing only its newline must also resume.
            path.write_text(path.read_text().rstrip("\n"))
            third = wrapper_class()
            third.generation_cache_path = path
            self.assertEqual(third.generate_until(requests), answers)
            self.assertEqual(third.calls, 0)
