"""Download the public assignment files; existing files are checked, never blindly replaced."""
import concurrent.futures
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def download_one(job):
    import gdown
    folder,name,ident=job;path=HERE/'inputs'/folder/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        with path.open('rb') as f:
            if f.read(4)!=b'PAR1':raise RuntimeError(f'{path} is not Parquet')
        return
    temp=path.with_suffix('.download')
    gdown.download(id=ident,output=str(temp),quiet=False)
    with temp.open('rb') as f:
        if f.read(4)!=b'PAR1':raise RuntimeError(f'{temp} is not Parquet')
    import pyarrow.parquet as pq
    assert pq.ParquetFile(temp).metadata.num_rows==32000
    temp.replace(path)


def main():
    files=json.loads((HERE/'inputs'/'drive_files.json').read_text())
    jobs=[(folder,name,ident) for folder,fs in files.items() for name,ident in fs.items()]
    with concurrent.futures.ThreadPoolExecutor(3) as pool:list(pool.map(download_one,jobs))


if __name__=='__main__':main()
