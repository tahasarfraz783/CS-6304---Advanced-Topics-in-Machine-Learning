"""PACS source splits and preprocessing. This module never opens Sketch."""
import hashlib
import json
from pathlib import Path

from PIL import Image
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset
from torchvision import transforms

SOURCES = ('photo', 'art_painting', 'cartoon')
CLASSES = ('dog', 'elephant', 'giraffe', 'guitar', 'horse', 'house', 'person')
SEED = 6304


def prepare_splits(root, destination):
    root, destination = Path(root), Path(destination)
    domains = {}
    for domain in SOURCES:
        folder = root / domain
        if not folder.is_dir():
            raise FileNotFoundError(f'Missing PACS source folder: {folder}')
        actual = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.'))
        if actual != list(CLASSES):
            raise ValueError(f'Unexpected classes in {domain}: {actual}')
        records = []
        for label, name in enumerate(CLASSES):
            paths = sorted(p for p in (folder / name).rglob('*')
                           if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp'})
            if not paths:
                raise ValueError(f'No images in {domain}/{name}')
            records.extend({'path': p.relative_to(root).as_posix(), 'label': label} for p in paths)
        train, val = train_test_split(records, test_size=0.2, random_state=SEED,
                                     stratify=[r['label'] for r in records])
        assert not ({r['path'] for r in train} & {r['path'] for r in val})
        domains[domain] = {'train': train, 'val': val}
    result = {'seed': SEED, 'class_to_idx': {c: i for i, c in enumerate(CLASSES)},
              'validation_fraction': 0.2, 'domains': domains}
    if destination.exists():
        if json.loads(destination.read_text()) != result:
            raise ValueError('Saved split differs from this dataset/protocol; refusing to replace it.')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def split_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_transform(training):
    operations = [transforms.Resize((256, 256))]
    operations += ([transforms.RandomCrop(224), transforms.RandomHorizontalFlip()]
                   if training else [transforms.CenterCrop(224)])
    return transforms.Compose(operations + [transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])


class PACSSource(Dataset):
    def __init__(self, root, records, training=False):
        self.root, self.records = Path(root), records
        self.transform = image_transform(training)
        if any(Path(r['path']).parts[0] not in SOURCES for r in records):
            raise ValueError('Source dataset cannot include target images.')

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]
        with Image.open(self.root / record['path']) as im:
            image = self.transform(im.convert('RGB'))
        return image, record['label']
