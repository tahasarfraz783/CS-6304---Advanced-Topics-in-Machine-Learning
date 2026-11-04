"""Offline checks: no downloads, GPU, or fabricated experiment outputs."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from task1.common import METHODS, read_json, stages, validate_config, write_json
from task1.plots import PRIMARY, refresh


class StarterChecks(unittest.TestCase):
    def test_assignment_schedule_and_effective_batch(self):
        c = read_json(HERE / "config.json")
        validate_config(c)
        self.assertEqual(c["examples"] // (c["microbatch"] * c["accumulation"]), 1250)
        self.assertEqual(stages(c), [312, 625, 937, 1250])
        c["examples"] = 33
        with self.assertRaises(ValueError):
            validate_config(c)

    def test_plan_needs_only_python(self):
        result = subprocess.run([sys.executable, str(HERE / "run.py"), "--mode", "plan"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1,250", result.stdout)
        for method in METHODS:
            self.assertIn(method, result.stdout)

    def test_real_plot_code_uses_percentage_points_and_well_formed_svg(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Tiny isolated unit-test fixtures, deleted on exit; never assignment evidence.
            for method, update, score in [("baseline", 0, 0.4), ("full_ft", 1250, 0.5)]:
                write_json(root / "evaluations" / f"{method}_{update:04d}" / "scores.json", {
                    "method": method, "update": update, "smoke_only": True,
                    "results": {task: {key: score, "acc,none": score} for task, key in PRIMARY.items()},
                })
            refresh(root)
            with (root / "evidence/benchmarks.csv").open() as f:
                rows = list(csv.DictReader(f))
            self.assertAlmostEqual(float(rows[1]["gsm8k_cot_delta_pp"]), 10.0)
            self.assertAlmostEqual(float(rows[1]["hellaswag_raw_acc_percent"]), 50.0)
            for svg in (root / "evidence").glob("*.svg"):
                ET.parse(svg)
                self.assertIn("SMOKE ONLY", svg.read_text())
            self.assertFalse((root / "evidence/sft_loss.svg").exists())
            self.assertEqual(read_json(root / "evidence/status.json")["completed_benchmark_conditions"], 2)

    def test_refresh_preserves_manual_annotations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "evidence"
            folder.mkdir()
            manual = folder / "annotations.csv"
            manual.write_text("my annotations", encoding="utf-8")
            refresh(root)
            self.assertEqual(manual.read_text(), "my annotations")


if __name__ == "__main__":
    unittest.main()
