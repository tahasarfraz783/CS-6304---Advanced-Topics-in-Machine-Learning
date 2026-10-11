"""Task 2 DAN loss and unlabeled target loader; imported only for adaptation."""
import json
from pathlib import Path

from PIL import Image
import torch
from torch.utils.data import Dataset

from .pacs import image_transform


def forward_features(model, x):
    """The same ResNet-18 forward path, stopping at its 512-D pooled feature."""
    x = model.maxpool(model.relu(model.bn1(model.conv1(x))))
    x = model.layer4(model.layer3(model.layer2(model.layer1(x))))
    return torch.flatten(model.avgpool(x), 1)


def multi_kernel_mmd(source, target, scales=(0.5, 1.0, 2.0)):
    """Biased empirical squared RKHS distance, including diagonal kernel terms.

    k(a,b) = sum_s exp(-||a-b||^2 / (s * median_distance_squared)).
    Median uses all unique off-diagonal pairs in the current combined batch.
    Bandwidth estimation is detached; gradients flow through both feature sets.
    Kernels are summed, not averaged. No feature normalization is applied.
    """
    if source.ndim != 2 or target.ndim != 2 or source.shape[1] != target.shape[1]:
        raise ValueError('Expected two nonempty feature matrices with matching width.')
    if not len(source) or not len(target):
        raise ValueError('MMD needs source and target examples.')
    if not scales or any(s <= 0 for s in scales):
        raise ValueError('Kernel scales must be positive.')
    features = torch.cat((source, target), dim=0).float()
    norm = features.square().sum(dim=1, keepdim=True)
    distances = (norm + norm.T - 2 * features @ features.T).clamp_min(0)
    # Enforce the exact self-distance rather than retaining roundoff on the diagonal.
    distances = distances - torch.diag_embed(distances.diagonal())
    pairs = torch.triu_indices(len(features), len(features), offset=1, device=features.device)
    median = distances.detach()[pairs[0], pairs[1]].median().clamp_min(1e-8)
    kernel = sum(torch.exp(-distances / (float(scale) * median)) for scale in scales)
    n = len(source)
    return kernel[:n, :n].mean() + kernel[n:, n:].mean() - 2 * kernel[:n, n:].mean()


class UnlabeledSketch(Dataset):
    """Scan images without constructing class labels or stratifying target data.

    Decoding failures are logged before training. Crops/flips use a separate CPU
    RNG stream, so adding target transforms cannot change the source augmentation
    sequence relative to ERM. Use with num_workers=0.
    """
    def __init__(self, root, output_dir, seed):
        self.root = Path(root)
        folder = self.root / 'sketch'
        if not folder.is_dir():
            raise FileNotFoundError(f'Missing target directory: {folder}')
        candidates = sorted(p for p in folder.rglob('*')
                            if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp'})
        self.paths, rejected = [], []
        for path in candidates:
            try:
                with Image.open(path) as im:
                    im.convert('RGB').load()
                self.paths.append(path)
            except (OSError, ValueError) as exc:
                rejected.append(dict(path=path.relative_to(self.root).as_posix(), reason=str(exc)))
        if not self.paths:
            raise ValueError('No decodable Sketch images found.')
        manifest = dict(accepted=[p.relative_to(self.root).as_posix() for p in self.paths],
                        rejected=rejected, rule='Exclude only images that cannot be decoded as RGB.')
        output = Path(output_dir) / 'target_manifest.json'
        if output.exists() and json.loads(output.read_text(encoding='utf-8')) != manifest:
            raise ValueError('Target manifest changed; use a new output directory.')
        output.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'Unlabeled Sketch: {len(self.paths)} usable images, {len(rejected)} decoding failures.')
        self.transform = image_transform(training=True)
        self.rng_state = torch.Generator().manual_seed(seed + 4).get_state()

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        with Image.open(self.paths[index]) as im:
            rgb = im.convert('RGB')
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(self.rng_state)
            image = self.transform(rgb)
            self.rng_state = torch.get_rng_state()
        return image, -1


def train_dan(data_root, split_path, output_dir, config=None):
    from .source_erm import CONFIG, train_pacs
    cfg = dict(CONFIG)
    cfg.update(lambda_mmd=1.0, kernel_scales=[0.5, 1.0, 2.0], target_batch_size=24,
               mmd_estimator='biased_including_diagonals',
               kernel_definition='sum exp(-squared_distance / (scale * batch_median_squared_distance))')
    if config is not None:
        cfg.update(config)
    if cfg['target_batch_size'] != 24 or cfg['batch_per_domain'] != 8:
        raise ValueError('The required protocol uses 8 per source and 24 target examples.')
    if cfg['lambda_mmd'] < 0:
        raise ValueError('lambda_mmd must be nonnegative.')
    return train_pacs(data_root, split_path, output_dir, cfg, method='dan')
