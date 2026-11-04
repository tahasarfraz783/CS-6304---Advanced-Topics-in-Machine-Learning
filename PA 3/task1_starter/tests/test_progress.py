import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task1.progress import LiveProgress, show_status


class LiveProgressChecks(unittest.TestCase):
    def test_heartbeat_is_distinct_from_measured_progress(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            root = Path(directory)
            with LiveProgress(root, "evaluate", "baseline", heartbeat_seconds=0.01) as progress:
                progress.phase("generation", 2, "answers")
                time.sleep(0.04)
                snapshot = json.loads((root / "progress.json").read_text())
                self.assertEqual(snapshot["completed"], 0)
                self.assertEqual(snapshot["event"], "HEARTBEAT")
                progress.detail(current_generation_steps=8)
                progress.advance(1)
            final = json.loads((root / "progress.json").read_text())
            self.assertEqual(final["state"], "completed")
            self.assertEqual(final["completed"], 1)
            self.assertIn("NOT proof of progress", output.getvalue())
            show_status(root)

    def test_failure_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "test failure"):
                with LiveProgress(root, "evaluate"):
                    raise ValueError("test failure")
            state = json.loads((root / "progress.json").read_text())
            self.assertEqual(state["state"], "failed")
            self.assertEqual(state["error"], "test failure")
