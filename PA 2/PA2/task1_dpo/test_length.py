import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from task1_dpo.analyze_length import compliance, summarize, run_study, STRATA


class LengthTests(unittest.TestCase):
    def test_strict_and_inclusive_limits(self):
        self.assertTrue(compliance("Use at most 3 words.", "one two three")[2])
        self.assertFalse(compliance("Use under 3 words.", "one two three")[2])
        self.assertTrue(compliance("Use under 3 words.", "one two")[2])
        with self.assertRaises(ValueError):
            compliance("Explain this briefly.", "one two")

    def test_strata_are_aggregated_separately(self):
        pairs = [{"length_stratum": stratum, "loss": .5,
                  "preference_accuracy": float(index == 0),
                  "implicit_reward_accuracy": float(index == 2)} for index, stratum in enumerate(STRATA)]
        generations = [{"tokens": 5, "words": 3, "compliant": True, "truncated": False},
                       {"tokens": 15, "words": 9, "compliant": False, "truncated": True}]
        summary = summarize(pairs, generations)
        self.assertEqual(summary["strata"]["preferred_longer"]["preference_accuracy"], 1.)
        self.assertEqual(summary["strata"]["rejected_longer"]["implicit_reward_accuracy"], 1.)
        self.assertEqual(summary["word_limit_compliance"], .5)
        self.assertEqual(summary["generated_words_mean"], 6.)

    def test_plan_uses_supplied_data_and_two_models(self):
        stream = io.StringIO()
        with patch("task1_dpo.analyze_length.subprocess.run") as launch, redirect_stdout(stream):
            run_study("configs/dpo.yaml", dry_run=True)
        launch.assert_not_called()
        self.assertIn("--dataset data/dpo_length_balanced_train.jsonl", stream.getvalue())
        self.assertIn("--worker standard", stream.getvalue())
        self.assertIn("--worker length_balanced", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
