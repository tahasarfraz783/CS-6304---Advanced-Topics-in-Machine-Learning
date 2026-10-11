import unittest
from task4_safety.evaluate_safety import summarize
from task4_safety.make_audit_sheet import fixed_audit_ids


class SafetyTests(unittest.TestCase):
    def test_denominators_and_ambiguity(self):
        rows = [dict(xstest_id=i, benchmark_class=cls, type="category", response_tokens=n, judge={"label":label}) for i, (cls, label, n) in enumerate([
            ("SAFE", "SAFE_ANSWER", 10), ("SAFE", "OVER_REFUSAL", 20),
            ("SAFE", "AMBIGUOUS", 30), ("UNSAFE", "UNSAFE_COMPLIANCE", 40),
            ("UNSAFE", "JUSTIFIED_REFUSAL", 50)])]
        summary, categories, _ = summarize(rows)
        self.assertAlmostEqual(summary["safe_answer_rate"], 1/3)
        self.assertAlmostEqual(summary["safe_over_refusal_rate"], 1/3)
        self.assertEqual(summary["unsafe_compliance_rate"], .5)
        self.assertEqual(summary["justified_refusal_rate"], .5)
        self.assertEqual(summary["ambiguous_rate"], .2)
        self.assertEqual(summary["mean_response_tokens"], 30)
        self.assertEqual(sum(c["AMBIGUOUS"] for c in categories), 1)

    def test_audit_balances_categories_and_classes(self):
        rows = [dict(xstest_id=len_cls*100 + cat*10 + i, benchmark_class=cls, type=str(cat))
                for len_cls, cls in enumerate(("SAFE", "UNSAFE")) for cat in range(3) for i in range(10)]
        ids = fixed_audit_ids(rows, 6, 6304)
        self.assertEqual(ids, fixed_audit_ids(rows, 6, 6304))
        self.assertEqual(len(set(ids)), 12)
        for cls in ("SAFE", "UNSAFE"):
            for cat in range(3):
                self.assertEqual(sum(r["xstest_id"] in ids and r["benchmark_class"] == cls and r["type"] == str(cat) for r in rows), 2)
        with self.assertRaises(ValueError):
            fixed_audit_ids(rows + [rows[0]], 6, 6304)

    def test_end_to_end_reports_without_models(self):
        import tempfile
        import json
        import sys
        from unittest.mock import patch
        import pandas as pd
        from task4_safety.evaluate_safety import main
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "task4_safety"
            out.mkdir()
            benchmark = pd.DataFrame([
                dict(xstest_id=0, prompt="benign", benchmark_class="SAFE", type="a"),
                dict(xstest_id=1, prompt="harmful", benchmark_class="UNSAFE", type="b")])
            benchmark.to_csv(root / "benchmark.csv", index=False)
            pd.DataFrame({"xstest_id": [0, 1]}).to_csv(out / "manual_audit_ids.csv", index=False)
            for policy in ("sft", "dpo", "ppo", "grpo"):
                rows = [dict(r, policy=policy, response="answer", response_tokens=12,
                    judge={"label": "SAFE_ANSWER" if r["benchmark_class"] == "SAFE" else "JUSTIFIED_REFUSAL"})
                    for r in benchmark.to_dict("records")]
                (out / f"judged_{policy}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
                pd.DataFrame({"xstest_id": [0, 1], "manual_label": ["SAFE_ANSWER", "AMBIGUOUS"]}).to_csv(out / f"manual_audit_{policy}.csv", index=False)
            cfg = dict(results_dir=str(root), paths={"xstest":str(root / "benchmark.csv")}, manual_audit_per_class=1)
            with patch("task4_safety.evaluate_safety.load_yaml", return_value=cfg), patch.object(sys, "argv", ["evaluate"]):
                main()
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["manual_audit"]["sft"]["agreement"], .5)
            self.assertEqual(summary["manual_audit"]["sft"]["status"], "complete")
            self.assertEqual(len(pd.read_csv(out / "category_results.csv")), 8)
            self.assertTrue((out / "audit_confusion_grpo.csv").exists())


if __name__ == "__main__":
    unittest.main()
