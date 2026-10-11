"""Validate beta experiment planning without expensive model loads."""
import copy
import io
import json
import tempfile
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from common.data import load_yaml
from task1_dpo.ablate_beta import conditions, run_study
from task1_dpo.evaluate import load_evaluation_bundle, evaluate, run_reward_worker, run_worker


class BetaStudyTests(unittest.TestCase):
    def test_policy_native_crash_retries(self):
        with patch("task1_dpo.evaluate.subprocess.run", side_effect=[
                subprocess.CalledProcessError(3221225477, ["policy"]), None]) as launch:
            run_worker(["policy"], stage="Policy")
        self.assertEqual(launch.call_count, 2)

    def test_native_reward_crash_retries(self):
        with patch("task1_dpo.evaluate.subprocess.run", side_effect=[
                subprocess.CalledProcessError(3221225477, ["worker"]), None]) as launch:
            run_reward_worker(["worker"])
        self.assertEqual(launch.call_count, 2)

    def test_python_errors_are_not_retried(self):
        with patch("task1_dpo.evaluate.subprocess.run", side_effect=
                   subprocess.CalledProcessError(1, ["worker"])) as launch:
            with self.assertRaises(subprocess.CalledProcessError):
                run_reward_worker(["worker"])
        launch.assert_called_once()

    def test_native_retries_are_bounded(self):
        with patch("task1_dpo.evaluate.subprocess.run", side_effect=
                   subprocess.CalledProcessError(3221225477, ["worker"])) as launch:
            with self.assertRaises(subprocess.CalledProcessError):
                run_reward_worker(["worker"])
        self.assertEqual(launch.call_count, 3)

    def test_cached_evaluation_restarts_only_reward_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"results_dir": directory, "paths": {"dpo_standard_eval": "unused"}}
            adapter = str(Path(directory) / "adapter")
            Path(directory, "retry_evaluation_cache.json").write_text(json.dumps({
                "adapter": adapter, "config": cfg,
                "pairs": [{"prompt_id": "a"}], "generations": [{}]}))
            Path(directory, "retry_summary.json").write_text(json.dumps({"complete": True}))
            with patch("task1_dpo.evaluate.load_yaml", return_value=cfg), \
                 patch("task1_dpo.evaluate.read_jsonl", return_value=[{"prompt_id": "a"}]), \
                 patch("task1_dpo.evaluate.subprocess.run") as launch:
                result = evaluate("unused", adapter, "retry")
            self.assertTrue(result["complete"])
            launch.assert_called_once()
            self.assertEqual(launch.call_args.args[0][-2:], ["--phase", "score"])

    def test_only_beta_changes(self):
        cfg = load_yaml("configs/dpo.yaml")
        original = copy.deepcopy(cfg)
        planned = list(conditions(cfg))
        self.assertEqual([condition["beta"] for _, condition, _ in planned], [.03, .10, .30])
        for _, condition, _ in planned:
            self.assertEqual({k: v for k, v in condition.items() if k != "beta"},
                             {k: v for k, v in cfg.items() if k != "beta"})
        self.assertEqual(cfg, original)

    def test_dry_run_does_not_launch_or_write(self):
        output = io.StringIO()
        with patch("task1_dpo.ablate_beta.subprocess.run") as launch, \
             patch("task1_dpo.ablate_beta.save_json") as save, redirect_stdout(output):
            run_study("configs/dpo.yaml", dry_run=True)
        launch.assert_not_called()
        save.assert_not_called()
        self.assertEqual(output.getvalue().count("-m task1_dpo.train"), 3)
        self.assertEqual(output.getvalue().count("-m task1_dpo.evaluate"), 3)
        self.assertEqual(output.getvalue().count("--max-examples 600"), 3)

    def test_evaluation_uses_trained_beta(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "run_metadata.json").write_text(json.dumps({"beta": .30}))
            with patch("task1_dpo.evaluate.load_tokenizer"), \
                 patch("task1_dpo.evaluate.load_policy"), \
                 patch("task1_dpo.evaluate.read_jsonl", return_value=[]):
                bundle = load_evaluation_bundle("configs/dpo.yaml", directory)
            self.assertEqual(bundle["cfg"]["beta"], .30)


if __name__ == "__main__":
    unittest.main()
