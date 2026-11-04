import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task1.common import METHODS, read_json, write_json
from task1.delivery import cleanup_test_outputs, package


class DeliveryChecks(unittest.TestCase):
    def test_packaging_contents_checksums_and_excluding_recovery_states(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            root = source / "outputs/assignment"
            write_json(root / "pipeline_complete.json", {"smoke_only": False, "automated_stages_complete": True})
            write_json(root / "resolved_config.json", {"examples": 40000, "microbatch": 2, "accumulation": 16})
            (source / "run.py").write_text("# unit test source")
            write_json(root / "evidence/status.json", {"fixture": True})
            conditions = ["full_ft_0625"] + [f"{m}_1250" for m in METHODS]
            for condition in conditions:
                model = root / "models" / condition
                write_json(model / "export_complete.json", {"fixture": True})
                (model / "model.safetensors").write_bytes(b"unit test only")
            cp = root / "runs/full_ft/checkpoints"
            cp.mkdir(parents=True)
            (cp / "update_1250.pt").write_bytes(b"exclude this optimizer checkpoint")
            # Packaging logic should not depend on the test machine's free disk.
            with patch("task1.delivery.shutil.disk_usage", return_value=SimpleNamespace(free=10**12)):
                package(root, source)
            with zipfile.ZipFile(root / "downloads/task1_results.zip") as archive:
                self.assertIn("results/evidence/status.json", archive.namelist())
                self.assertIn("code/run.py", archive.namelist())
                self.assertFalse(any("checkpoints" in name for name in archive.namelist()))
            with zipfile.ZipFile(root / "downloads/task1_models.zip") as archive:
                self.assertEqual(sum(n.endswith("model.safetensors") for n in archive.namelist()), 6)
            for record in read_json(root / "downloads/SHA256.json"):
                path = root / "downloads" / record["file"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"])

    def test_cleanup_refuses_unknown_data_and_preserves_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            write_json(source / "outputs/assignment/important.json", {"keep": True})
            write_json(source / "outputs/smoke/resolved_config.json", {"examples": 128})
            cleanup_test_outputs(source)
            self.assertFalse((source / "outputs/smoke").exists())
            self.assertTrue((source / "outputs/assignment/important.json").exists())
            (source / "outputs/timing").mkdir()
            with self.assertRaises(ValueError):
                cleanup_test_outputs(source)

    def test_rejects_packaging_smoke_as_official_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "pipeline_complete.json", {"smoke_only": True, "automated_stages_complete": True})
            with self.assertRaises(ValueError):
                package(root, root)
