"""Common PACS training loop. Source-only mode never loads target data."""
import json
import math
import random
import platform
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torchvision
from sklearn.metrics import accuracy_score, f1_score
from torch import nn
from torch.utils.data import DataLoader
from torchvision.models import resnet18, ResNet18_Weights
from tqdm.auto import tqdm

from .pacs import SOURCES, CLASSES, SEED, PACSSource, prepare_splits, split_hash

CONFIG = dict(seed=SEED, epochs=30, patience=5, learning_rate=1e-4,
              weight_decay=1e-4, batch_per_domain=8, workers=0,
              weights='ResNet18_Weights.IMAGENET1K_V1',
              selection='mean_source_validation_macro_f1',
              batchnorm='frozen_pretrained_running_stats_trainable_affine',
              epoch_definition='ceil(largest_source_training_count / 8) balanced updates',
              precision='float32', resize=[256, 256], crop=224)


def seed_everything(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def make_model(pretrained=True):
    model = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1 if pretrained else None)
    model.fc = nn.Linear(model.fc.in_features, len(CLASSES))
    return model


def training_mode(model):
    model.train()
    for layer in model.modules():
        if isinstance(layer, nn.modules.batchnorm._BatchNorm):
            layer.eval()


class DomainStream:
    """Cycle shuffled loaders, retaining tails so every update has exactly eight/domain."""
    def __init__(self, loader):
        self.loader = loader
        self.iterator = iter(loader)
        self.pending = None

    def take(self, count):
        xs, ys = [], []
        remaining = count
        while remaining:
            if self.pending is None:
                try:
                    self.pending = next(self.iterator)
                except StopIteration:
                    self.iterator = iter(self.loader)
                    self.pending = next(self.iterator)
            x, y = self.pending
            n = min(remaining, len(y))
            xs.append(x[:n]); ys.append(y[:n])
            self.pending = (x[n:], y[n:]) if len(y) > n else None
            remaining -= n
        return torch.cat(xs), torch.cat(ys)


@torch.no_grad()
def evaluate(model, loaders, device):
    model.eval()
    rows, predictions = [], []
    for domain, loader in loaders.items():
        truth, pred, losses = [], [], 0.0
        for x, y in loader:
            logits = model(x.to(device))
            losses += nn.functional.cross_entropy(logits, y.to(device), reduction='sum').item()
            truth.extend(y.tolist()); pred.extend(logits.argmax(1).cpu().tolist())
        rows.append(dict(domain=domain, accuracy=accuracy_score(truth, pred),
                         macro_f1=f1_score(truth, pred, labels=list(range(7)), average='macro', zero_division=0),
                         loss=losses / len(truth), count=len(truth)))
        predictions.extend(dict(domain=domain, path=r['path'], label=y, prediction=p)
                           for r, y, p in zip(loader.dataset.records, truth, pred))
    return pd.DataFrame(rows), pd.DataFrame(predictions)


def train_source_only(data_root, split_path, output_dir, config=None):
    return train_pacs(data_root, split_path, output_dir, config, method='source_only')


def train_pacs(data_root, split_path, output_dir, config=None, method='source_only'):
    if method not in ('source_only', 'dan', 'dann', 'cdan', 'dan_dg', 'sam'):
        raise ValueError(f'Unsupported method: {method}')
    cfg = dict(CONFIG if config is None else config)
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / 'best.pt'
    if checkpoint.exists():
        raise FileExistsError(f'Preserving existing baseline: {checkpoint}. Load it or choose a new output directory.')
    seed_everything(cfg['seed'])
    splits = prepare_splits(data_root, split_path)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    train_loaders, val_loaders = {}, {}
    for i, domain in enumerate(SOURCES):
        train_loaders[domain] = DataLoader(
            PACSSource(data_root, splits['domains'][domain]['train'], True),
            batch_size=cfg['batch_per_domain'], shuffle=True, num_workers=cfg['workers'],
            generator=torch.Generator().manual_seed(cfg['seed'] + i), drop_last=False)
        val_loaders[domain] = DataLoader(
            PACSSource(data_root, splits['domains'][domain]['val']),
            batch_size=64, shuffle=False, num_workers=cfg['workers'])
    target_loader = None
    if method == 'sam':
        from .sam import sam_step
    if method == 'dan_dg':
        from .dan import forward_features
        from .dan_dg import pairwise_source_mmd
    if method in ('dan', 'dann', 'cdan'):
        from .dan import UnlabeledSketch, forward_features, multi_kernel_mmd
        if cfg['workers'] != 0:
            raise ValueError('Use workers=0 to preserve the target augmentation RNG stream.')
        target_loader = DataLoader(
            UnlabeledSketch(data_root, out, cfg['seed']),
            batch_size=24, shuffle=True, num_workers=0, drop_last=False,
            generator=torch.Generator().manual_seed(cfg['seed'] + 3))
    torch.hub.set_dir(str(Path(data_root).parent / 'torch_cache'))
    initial_checkpoint = cfg.get('initial_checkpoint')
    model = make_model(pretrained=not bool(initial_checkpoint)).to(device)
    if initial_checkpoint:
        initial = torch.load(initial_checkpoint, map_location='cpu', weights_only=True)
        if initial.get('method') != 'source_only':
            raise ValueError('Recovery initialization must be the source-only checkpoint.')
        if initial['split_sha256'] != split_hash(split_path) or initial['class_to_idx'] != splits['class_to_idx']:
            raise ValueError('Initialization split/class mapping mismatch.')
        cfg['initial_checkpoint_sha256'] = hashlib.sha256(Path(initial_checkpoint).read_bytes()).hexdigest()
        model.load_state_dict(initial['model_state'])
        del initial
    if cfg.get('freeze_batchnorm_affine', False):
        for layer in model.modules():
            if isinstance(layer, nn.modules.batchnorm._BatchNorm):
                layer.requires_grad_(False)
    discriminator = None
    parameters = list(model.parameters())
    if method in ('dann', 'cdan'):
        from .dann import DomainDiscriminator, reverse_gradient, reversal_strength
        if method == 'cdan':
            from .cdan import conditional_features
        # Do not perturb the baseline's CPU initialization/augmentation RNG stream.
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(torch.Generator().manual_seed(cfg['seed'] + 5).get_state())
            discriminator = DomainDiscriminator(512 * len(CLASSES) if method == 'cdan' else 512).to(device)
        discriminator_cpu_rng = torch.Generator().manual_seed(cfg['seed'] + 6).get_state()
        parameters += list(discriminator.parameters())
    if 'backbone_learning_rate' in cfg:
        head_ids = {id(p) for p in model.fc.parameters()}
        groups = [dict(params=[p for p in model.parameters() if p.requires_grad and id(p) not in head_ids],
                       lr=cfg['backbone_learning_rate']),
                  dict(params=list(model.fc.parameters()), lr=cfg['learning_rate'])]
        if discriminator is not None:
            groups.append(dict(params=list(discriminator.parameters()),
                               lr=cfg.get('discriminator_learning_rate', cfg['learning_rate'])))
        optimizer = torch.optim.AdamW(groups, weight_decay=cfg['weight_decay'])
    else:
        optimizer = torch.optim.AdamW(parameters, lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    metadata = dict(config=cfg, split_sha256=split_hash(split_path), class_to_idx=splits['class_to_idx'],
                    environment=dict(python=platform.python_version(), torch=str(torch.__version__),
                    torchvision=str(torchvision.__version__), device=str(device),
                    gpu=torch.cuda.get_device_name(0) if device.type == 'cuda' else None))
    metadata['method'] = method
    (out / 'config.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    steps = math.ceil(max(len(loader.dataset) for loader in train_loaders.values()) / cfg['batch_per_domain'])
    history, best, stale = [], -float('inf'), 0
    for epoch in range(1, cfg['epochs'] + 1):
        training_mode(model)
        if discriminator is not None:
            discriminator.train()
        streams = {d: DomainStream(loader) for d, loader in train_loaders.items()}
        target_stream = DomainStream(target_loader) if target_loader is not None else None
        total_loss, correct, count = 0.0, 0, 0
        total_classification, total_alignment = 0.0, 0.0
        total_perturbed = 0.0
        weighted_alignment_total, ramp_total, gradient_norm_total = 0.0, 0.0, 0.0
        domain_correct, domain_count, alpha_sum = 0, 0, 0.0
        for step in tqdm(range(steps), desc=f'Epoch {epoch}/{cfg["epochs"]}', leave=False):
            batches = [streams[d].take(cfg['batch_per_domain']) for d in SOURCES]
            x = torch.cat([b[0] for b in batches]).to(device)
            y = torch.cat([b[1] for b in batches]).to(device)
            optimizer.zero_grad(set_to_none=True)
            ramp_epochs = cfg.get('alignment_ramp_epochs', 0)
            ramp = min(1.0, ((epoch - 1) * steps + step + 1) / (ramp_epochs * steps)) if ramp_epochs else 1.0
            ramp_total += ramp
            if method == 'sam':
                logits, loss, perturbed_loss = sam_step(model, optimizer, x, y, cfg['rho'])
                total_perturbed += perturbed_loss.item() * len(y)
            elif method == 'dan_dg':
                source_features = forward_features(model, x)
                logits = model.fc(source_features)
                classification = nn.functional.cross_entropy(logits, y)
                alignment = pairwise_source_mmd(source_features, cfg['batch_per_domain'],
                                                cfg['kernel_scales'])
                loss = classification + ramp * cfg['lambda_dg'] * alignment
                weighted_alignment_total += ramp * cfg['lambda_dg'] * alignment.item() * len(y)
                total_classification += classification.item() * len(y)
                total_alignment += alignment.item() * len(y)
            elif method in ('dan', 'dann', 'cdan'):
                # Target dataset supplies a constant -1 placeholder, never class labels.
                target_x, _ = target_stream.take(24)
                source_features = forward_features(model, x)
                target_features = forward_features(model, target_x.to(device))
                logits = model.fc(source_features)
                classification = nn.functional.cross_entropy(logits, y)
                if method == 'dan':
                    alignment = multi_kernel_mmd(source_features, target_features,
                                                 cfg['kernel_scales'])
                    loss = classification + ramp * cfg['lambda_mmd'] * alignment
                    weighted_alignment_total += ramp * cfg['lambda_mmd'] * alignment.item() * len(y)
                else:
                    progress = ((epoch - 1) * steps + step) / max(cfg['epochs'] * steps - 1, 1)
                    alpha = ramp * reversal_strength(progress, cfg['max_grl_strength'])
                    features = torch.cat((source_features, target_features), dim=0)
                    if method == 'cdan':
                        target_logits = model.fc(target_features)
                        probabilities = torch.cat((logits, target_logits), dim=0).softmax(dim=1)
                        features = conditional_features(features, probabilities)
                    domain_labels = torch.cat((
                        torch.zeros(len(source_features), dtype=torch.long, device=device),
                        torch.ones(len(target_features), dtype=torch.long, device=device)))
                    # CPU dropout must not change subsequent source crop/flip draws.
                    with torch.random.fork_rng(devices=[]):
                        torch.set_rng_state(discriminator_cpu_rng)
                        domain_logits = discriminator(reverse_gradient(features, alpha))
                        discriminator_cpu_rng = torch.get_rng_state()
                    alignment = nn.functional.cross_entropy(domain_logits, domain_labels)
                    loss = classification + alignment  # Unit domain-loss weight.
                    domain_correct += (domain_logits.argmax(1) == domain_labels).sum().item()
                    domain_count += len(domain_labels)
                    alpha_sum += alpha
                total_classification += classification.item() * len(y)
                total_alignment += alignment.item() * len(y)
            else:
                logits = model(x)
                loss = nn.functional.cross_entropy(logits, y)
            if not torch.isfinite(loss):
                raise RuntimeError('Non-finite training loss')
            if method != 'sam':
                loss.backward()
                if cfg.get('gradient_clip_norm') is not None:
                    norm = torch.nn.utils.clip_grad_norm_(parameters, cfg['gradient_clip_norm'], error_if_nonfinite=True)
                    gradient_norm_total += float(norm)
                optimizer.step()
            total_loss += loss.item() * len(y)
            correct += (logits.argmax(1) == y).sum().item(); count += len(y)
        metrics, _ = evaluate(model, val_loaders, device)
        score = float(metrics.macro_f1.mean())
        row = dict(epoch=epoch, train_loss=total_loss/count, train_accuracy=correct/count,
                   mean_val_macro_f1=score, mean_val_accuracy=float(metrics.accuracy.mean()),
                   mean_val_loss=float(metrics.loss.mean()))
        if cfg.get('alignment_ramp_epochs', 0):
            row['mean_alignment_ramp'] = ramp_total / steps
        if cfg.get('gradient_clip_norm') is not None:
            row['mean_gradient_norm_before_clip'] = gradient_norm_total / steps
        if method == 'sam':
            row.update(classification_loss=total_loss/count,
                       perturbed_classification_loss=total_perturbed/count)
        elif method in ('dan', 'dan_dg'):
            row.update(classification_loss=total_classification/count,
                       mmd_loss=total_alignment/count,
                       weighted_mmd_loss=weighted_alignment_total/count)
        elif method in ('dann', 'cdan'):
            row.update(classification_loss=total_classification/count,
                       domain_loss=total_alignment/count,
                       domain_accuracy=domain_correct/domain_count,
                       mean_grl_strength=alpha_sum/steps,
                       last_grl_strength=alpha)
        for item in metrics.to_dict('records'):
            for key in ('accuracy', 'macro_f1', 'loss'):
                row[f'{item["domain"]}_{key}'] = item[key]
        history.append(row)
        pd.DataFrame(history).to_csv(out / 'history.csv', index=False)
        eligible = epoch >= cfg.get('selection_start_epoch', 1)
        if eligible and score > best:
            best, stale = score, 0
            state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            payload = dict(model_state=state, epoch=epoch, best_source_macro_f1=best, **metadata)
            if discriminator is not None:
                payload['discriminator_state'] = {
                    k: v.detach().cpu().clone() for k, v in discriminator.state_dict().items()}
            torch.save(payload, checkpoint)
        elif eligible:
            stale += 1
        print(f'Epoch {epoch}: loss={row["train_loss"]:.4f}, mean source macro-F1={score:.4f}, patience={stale}/{cfg["patience"]}', flush=True)
        if stale >= cfg['patience']:
            break
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    model.load_state_dict(saved['model_state'])
    metrics, predictions = evaluate(model, val_loaders, device)
    metrics.to_csv(out / 'source_validation.csv', index=False)
    predictions.to_csv(out / 'source_validation_predictions.csv', index=False)
    (out / 'completion.json').write_text(json.dumps(dict(
        completed_epochs=len(history), best_epoch=saved['epoch'],
        best_source_macro_f1=saved['best_source_macro_f1'],
        stopped_early=stale >= cfg['patience']), indent=2))
    return model, metrics, pd.DataFrame(history)
