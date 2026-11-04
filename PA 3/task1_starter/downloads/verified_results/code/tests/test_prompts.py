from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task1.common import read_json, write_json
from task1.prompts import normalize_prompts, prepare_prompts, qualitative_inputs

SOURCE = Path(__file__).resolve().parents[1] / "inputs/first_plot_questions.yaml"


class CoursePromptChecks(unittest.TestCase):
    def test_exact_roles_formats_and_annotation_subset(self):
        rows = normalize_prompts(SOURCE)
        self.assertEqual(len(rows), 24)
        self.assertEqual({r["format"] for r in rows}, {"plain", "json", "template"})
        for row in rows:
            self.assertEqual(row["messages"][-1], {"role": "user", "content": row["prompt"]})
            self.assertEqual([m["role"] for m in row["messages"]],
                             ["system", "user"] if row["format"] == "json" else ["user"])
            self.assertNotIn("judge", row)
            self.assertNotIn("samples_per_paraphrase", row)
        flagged = [r for r in rows if r["annotate"]]
        self.assertEqual(len(flagged), 6)
        self.assertEqual({r["question_id"] for r in flagged}, {"what_is_your_wish", "enough_of_my_husband"})

    def test_normalized_file_must_match_yaml_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "first_plot_questions.yaml"
            path.write_bytes(SOURCE.read_bytes())
            prepare_prompts(path)
            self.assertEqual(len(qualitative_inputs({"qualitative_file": str(path)})), 24)
            normalized = path.with_name("qualitative.json")
            rows = read_json(normalized)
            rows[8]["messages"][0]["role"] = "user"
            write_json(normalized, rows)
            with self.assertRaises(ValueError):
                qualitative_inputs({"qualitative_file": str(path)})
