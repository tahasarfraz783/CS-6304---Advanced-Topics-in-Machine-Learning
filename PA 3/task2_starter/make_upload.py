"""Build the portable source+selected-data upload; never includes experiment outputs."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
dest = root.parent/'task2_starter_upload.zip'
with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(root.rglob('*')):
        if path.is_file() and not any(p in {'outputs', '__pycache__', '.verification', '.venv', '.git'} for p in path.relative_to(root).parts):
            archive.write(path, path.relative_to(root.parent))
with zipfile.ZipFile(dest) as archive:
    assert archive.testzip() is None
    assert 'task2_starter/inputs/selected_manifest.json' in archive.namelist()
    assert 'task2_starter/run.py' in archive.namelist()
h = hashlib.sha256(dest.read_bytes()).hexdigest()
dest.with_suffix('.sha256').write_text(h+'  '+dest.name+'\n', encoding='ascii')
print(f'{dest}\n{dest.stat().st_size:,} bytes\nSHA256 {h}')
