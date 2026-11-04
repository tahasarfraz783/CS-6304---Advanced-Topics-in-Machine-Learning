import tempfile
from pathlib import Path
import unittest
from task3.common import write,read,run_lock
from task3.data import input_manifest,DATASETS


class Recovery(unittest.TestCase):
    def test_atomic_json_and_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write(root/'state.json',{'done':1});self.assertEqual(read(root/'state.json'),{'done':1})
            self.assertFalse((root/'state.json.tmp').exists())
            with run_lock(root):
                with self.assertRaises(RuntimeError):
                    with run_lock(root):pass
            self.assertFalse((root/'.run.lock').exists())
    def test_portable_input_hashes_and_mutation_detection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ['README.MD','mathvista_testmini.json']:(root/name).write_text('fixture')
            for dataset,folder in DATASETS.items():
                (root/folder).mkdir()
                for name in ['generations.parquet','probability_metrics.parquet']+(['attention_metrics.parquet'] if dataset=='MathVista' else []):
                    (root/folder/name).write_bytes(b'fixture')
            original=input_manifest(root)
            self.assertTrue(all('\\' not in k for k in original))
            write(root/'expected_files.json',original);self.assertEqual(input_manifest(root),original)
            (root/'README.MD').write_text('changed')
            with self.assertRaises(ValueError):input_manifest(root)


if __name__=='__main__':unittest.main()
