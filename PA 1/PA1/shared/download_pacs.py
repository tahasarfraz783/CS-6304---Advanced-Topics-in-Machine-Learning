"""Download the PACS archive linked by Dassl.pytorch.

Source: https://github.com/KaiyangZhou/Dassl.pytorch/blob/master/dassl/data/datasets/dg/pacs.py
Only the dataset URL is reused; extraction/download handling is implemented here.
"""
import argparse
import hashlib
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
import requests

URL = 'https://drive.google.com/uc?export=download&id=1m4X4fROCCXMO0lRLrr6Zz9Vb3974NWhE'


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__(); self.action = None; self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'download-form':
            self.action = attrs.get('action')
        if tag == 'input' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')


def download_pacs(data_dir):
    data_dir = Path(data_dir).resolve(); data_dir.mkdir(parents=True, exist_ok=True)
    root = data_dir / 'PACS'
    if (data_dir / 'pacs_download.json').exists() and all((root / d).is_dir() for d in ('photo', 'art_painting', 'cartoon', 'sketch')):
        return root
    archive = data_dir / 'PACS.zip'
    if not archive.exists():
        session = requests.Session()
        response = session.get(URL, stream=True, timeout=60)
        response.raise_for_status()
        if 'text/html' in response.headers.get('Content-Type', ''):
            form = DownloadForm(); form.feed(response.text); response.close()
            if not form.action or not form.action.startswith('https://drive.usercontent.google.com/'):
                raise RuntimeError('Google Drive did not return a download form. Download PACS.zip manually from the documented URL.')
            response = session.get(form.action, params=form.fields, stream=True, timeout=60)
            response.raise_for_status()
        if 'text/html' in response.headers.get('Content-Type', ''):
            raise RuntimeError('Google Drive returned HTML instead of a ZIP (possibly a download quota).')
        temporary = archive.with_suffix('.zip.part')
        size = 0
        with temporary.open('wb') as f:
            for chunk in response.iter_content(1024 * 1024):
                f.write(chunk); size += len(chunk)
                if size // (50 * 1024**2) != (size - len(chunk)) // (50 * 1024**2):
                    print(f'Downloaded {size / 1024**2:.0f} MiB', flush=True)
        response.close()
        if not zipfile.is_zipfile(temporary):
            raise RuntimeError('Downloaded file is not a ZIP archive.')
        temporary.replace(archive)
    with zipfile.ZipFile(archive) as z:
        import shutil
        for member in z.infolist():
            parts = Path(member.filename).parts
            indices = [i for i, p in enumerate(parts) if p in ('photo', 'art_painting', 'cartoon', 'sketch')]
            if not indices or member.is_dir() or '__MACOSX' in parts:
                continue
            relative = Path(*parts[indices[0]:])
            if relative.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.bmp'):
                continue
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Archive path escapes destination')
            path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, path.open('wb') as dst:
                shutil.copyfileobj(src, dst)
    if not all((root / d).is_dir() for d in ('photo', 'art_painting', 'cartoon', 'sketch')):
        raise RuntimeError(f'Unexpected archive layout under {data_dir}')
    digest = hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    (data_dir / 'pacs_download.json').write_text(json.dumps(dict(url=URL, sha256=digest.hexdigest()), indent=2))
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    print(download_pacs(parser.parse_args().data_dir))
