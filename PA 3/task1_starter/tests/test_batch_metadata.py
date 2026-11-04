import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task1.common import read_json, write_json
SOURCE = Path(__file__).resolve().parents[1] / "task1/evaluation.py"


class BatchMetadataChecks(unittest.TestCase):
    def test_runtime_batch_is_frozen_separately_from_training_config(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "evaluation_batch_size")
        namespace = {"Path": Path, "os": os, "read_json": read_json, "write_json": write_json}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
        resolve = namespace["evaluation_batch_size"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PA3_EVAL_BATCH_SIZE": "8"}):
                self.assertEqual(resolve({"eval_batch_size": 1}, directory), 8)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(resolve({"eval_batch_size": 1}, directory), 8)
            with patch.dict(os.environ, {"PA3_EVAL_BATCH_SIZE": "4"}):
                with self.assertRaises(ValueError):
                    resolve({}, directory)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "Requires torch")
    def test_sorted_padded_rows_eos_stop_and_cap_are_attributed_correctly(self):
        import torch
        class Backend:
            def _model_generate(self, *args, **kwargs):
                return self.result
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LoggedHFLM")
        namespace = {"HFLM": Backend, "hashlib": hashlib, "json": json, "time": time, "Path": Path}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), "exec"), namespace)
        wrapper = namespace["LoggedHFLM"]()
        wrapper.model = SimpleNamespace(generation_config=SimpleNamespace(eos_token_id=2))
        wrapper.tokenizer = SimpleNamespace(decode=lambda ids, **kw: " ".join("STOP" if i == 15 else str(i) for i in ids))
        wrapper._active_docs = {(11,): [41, 42], (12, 13, 14): [9], (21, 22): [3]}
        context = torch.tensor([[0, 0, 11], [12, 13, 14], [0, 21, 22]])
        attention = torch.tensor([[0, 0, 1], [1, 1, 1], [0, 1, 1]])
        wrapper.result = torch.cat([context, torch.tensor([[7, 2, 0, 0], [8, 9, 10, 11], [15, 0, 0, 0]])], dim=1)
        output = wrapper._model_generate(context, 7, ["STOP"], attention_mask=attention)
        self.assertTrue(torch.equal(output, wrapper.result))
        records = wrapper.generation_records
        self.assertEqual(records[41]["generated_tokens"], 2)
        self.assertFalse(records[41]["truncated"])
        self.assertEqual(records[41], records[42])
        self.assertEqual(records[9]["generated_tokens"], 4)
        self.assertTrue(records[9]["truncated"])
        self.assertEqual(records[3]["generated_tokens"], 1)
        self.assertFalse(records[3]["truncated"])
