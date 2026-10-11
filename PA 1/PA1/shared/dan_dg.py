"""DAN-DG: average Task 2 MMD across the three source-domain pairs."""
from itertools import combinations
from pathlib import Path
import math

import torch

from .dan import multi_kernel_mmd
from .pacs import CLASSES, split_hash
from .source_erm import CONFIG, train_pacs


def pairwise_source_mmd(features, batch_per_domain=8, scales=(0.5, 1.0, 2.0)):
    """Features are ordered Photo, Art Painting, Cartoon; bandwidths are per pair."""
    if features.ndim != 2 or features.shape != (3 * batch_per_domain, 512):
        raise ValueError('Expected three equal source blocks of 512-D features.')
    blocks = features.split(batch_per_domain)
    return sum(multi_kernel_mmd(a, b, scales) for a, b in combinations(blocks, 2)) / 3


def train_dan_dg(data_root, split_path, output_dir, baseline_checkpoint, lambda_dg=1.0):
    if not math.isfinite(lambda_dg) or lambda_dg < 0:
        raise ValueError('lambda_dg must be finite and nonnegative.')
    if not Path(split_path).is_file():
        raise FileNotFoundError('Task 3 requires the existing Task 2 source split.')
    baseline = torch.load(baseline_checkpoint, map_location='cpu', weights_only=True)
    if baseline.get('method', 'source_only') != 'source_only':
        raise ValueError('Expected the source-only ERM baseline.')
    if baseline['split_sha256'] != split_hash(split_path):
        raise ValueError('Baseline and current source split differ.')
    if baseline['class_to_idx'] != {name: i for i, name in enumerate(CLASSES)}:
        raise ValueError('Baseline class mapping differs from the shared protocol.')
    cfg = dict(baseline['config'])
    if any(cfg.get(key) != value for key, value in CONFIG.items()):
        raise ValueError('Baseline configuration differs from the shared protocol.')
    cfg.update(lambda_dg=float(lambda_dg), kernel_scales=[0.5, 1.0, 2.0],
               mmd_estimator='biased_including_diagonals',
               kernel_definition='sum exp(-squared_distance / (scale * batch_median_squared_distance))',
               alignment='mean of Photo-Art, Photo-Cartoon, Art-Cartoon MMD; per-pair bandwidth')
    # The checkpoint supplies protocol metadata only, never the initialization.
    del baseline
    return train_pacs(data_root, split_path, output_dir, cfg, method='dan_dg')
