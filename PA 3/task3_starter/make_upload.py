"""Create a portable upload, with optional supplied Parquet files."""
import argparse
import hashlib
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--include-data',action='store_true');a=p.parse_args()
target=HERE.parent/('task3_starter_with_data.zip' if a.include_data else 'task3_starter_upload.zip')
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for f in sorted(HERE.rglob('*')):
        rel=f.relative_to(HERE)
        if not f.is_file() or any(x in {'outputs','downloads','__pycache__','.git'} for x in rel.parts):continue
        if f.suffix in {'.part','.download'}:continue
        if f.suffix=='.parquet' and not a.include_data:continue
        z.write(f,Path(HERE.name)/rel)
with zipfile.ZipFile(target) as z:assert z.testzip() is None
h=hashlib.sha256()
with target.open('rb') as f:
    for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
target.with_suffix('.sha256').write_text(h.hexdigest()+'  '+target.name+'\n')
print(target,target.stat().st_size,'bytes',h.hexdigest())
