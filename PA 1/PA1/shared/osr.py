"""Task 4: reproducible CIFAR-10 vanilla baseline (no unknown data access)."""
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, models, transforms

CONFIG = dict(seed=6304, epochs=100, batch_size=128, lr=0.1,
              momentum=0.9, weight_decay=5e-4,
              normalization_mean=[0.4914, 0.4822, 0.4465],
              normalization_std=[0.2470, 0.2435, 0.2616])


def make_model():
    model = models.resnet18(weights=None, num_classes=10)
    model.conv1 = nn.Conv2d(3, 64, 3, stride=1, padding=1, bias=False)
    nn.init.kaiming_normal_(model.conv1.weight, mode='fan_out', nonlinearity='relu')
    model.maxpool = nn.Identity()
    return model


def forward_features(model, x):
    x = model.maxpool(model.relu(model.bn1(model.conv1(x))))
    x = model.layer4(model.layer3(model.layer2(model.layer1(x))))
    features = model.avgpool(x).flatten(1)
    return features, model.fc(features)


def seed_everything():
    random.seed(CONFIG['seed'])
    np.random.seed(CONFIG['seed'])
    torch.manual_seed(CONFIG['seed'])
    torch.cuda.manual_seed_all(CONFIG['seed'])
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def method_config(method):
    if method not in ('vanilla', 'gcsc'):
        raise ValueError('Expected vanilla or gcsc.')
    return dict(CONFIG, randaugment_num_ops=2, randaugment_magnitude=9) if method == 'gcsc' else dict(CONFIG)


def prepare(root, method='vanilla'):
    method_config(method)
    root = Path(root)
    out = root / 'Task 4/results' / method
    out.mkdir(parents=True, exist_ok=True)
    normalize = [transforms.ToTensor(), transforms.Normalize(
        CONFIG['normalization_mean'], CONFIG['normalization_std'])]
    plain = transforms.Compose(normalize)
    augmentation = [transforms.RandomCrop(32, padding=4), transforms.RandomHorizontalFlip()]
    if method == 'gcsc':
        augmentation.append(transforms.RandAugment(num_ops=2, magnitude=9))
    augmented = transforms.Compose([*augmentation, *normalize])
    train = datasets.CIFAR10(root / 'data', train=True, download=True, transform=augmented)
    clean = datasets.CIFAR10(root / 'data', train=True, download=False, transform=plain)
    rng = np.random.default_rng(CONFIG['seed'])
    targets = np.asarray(train.targets)
    split = dict(seed=CONFIG['seed'], train=[], validation=[])
    for c in range(10):
        indices = rng.permutation(np.flatnonzero(targets == c))
        split['validation'].extend(indices[:500].tolist())
        split['train'].extend(indices[500:].tolist())
    split_path = out / 'split.json'
    if split_path.exists() and json.loads(split_path.read_text()) != split:
        raise ValueError('Existing split differs from seed-6304 stratified split.')
    split_path.write_text(json.dumps(split, indent=2))
    return out, train, clean, plain, split


def loader(dataset, shuffle=False):
    return DataLoader(dataset, batch_size=CONFIG['batch_size'], shuffle=shuffle,
                      num_workers=0, pin_memory=torch.cuda.is_available())


@torch.inference_mode()
def accuracy(model, batches, device):
    model.eval()
    correct = total = 0
    for x, y in batches:
        pred = model(x.to(device)).argmax(1).cpu()
        correct += (pred == y).sum().item()
        total += len(y)
    return correct / total


def train_vanilla(root):
    return train_classifier(root, 'vanilla')


def train_gcsc(root):
    return train_classifier(root, 'gcsc')


def train_classifier(root, method='vanilla'):
    config = method_config(method)
    seed_everything()
    out, train, clean, _, split = prepare(root, method)
    if (out / 'complete.json').exists():
        saved = json.loads((out / 'complete.json').read_text())
        if saved['config'] != config:
            raise ValueError('Completed run has different configuration.')
        return saved
    if (out / 'best.pt').exists() or (out / 'history.json').exists():
        raise RuntimeError('Incomplete run exists; preserve it in another directory before restarting.')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = make_model().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=CONFIG['lr'],
        momentum=CONFIG['momentum'], weight_decay=CONFIG['weight_decay'])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=CONFIG['epochs'])
    training = loader(Subset(train, split['train']), shuffle=True)
    validation = loader(Subset(clean, split['validation']))
    best, history = -1.0, []
    (out / 'config.json').write_text(json.dumps(config, indent=2))
    print(f'Training on {device}: 45,000 training / 5,000 validation images', flush=True)
    for epoch in range(1, CONFIG['epochs'] + 1):
        model.train()
        loss_sum = correct = count = 0
        lr = optimizer.param_groups[0]['lr']
        for x, y in training:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = nn.functional.cross_entropy(logits, y)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * len(y)
            correct += (logits.argmax(1) == y).sum().item()
            count += len(y)
        val = accuracy(model, validation, device)
        history.append(dict(epoch=epoch, lr=lr, train_loss=loss_sum/count,
                            train_accuracy=correct/count, validation_accuracy=val))
        if val > best:
            best = val
            torch.save(dict(model_state=model.state_dict(), epoch=epoch,
                            validation_accuracy=val, config=config, split=split,
                            classes=train.classes), out / 'best.pt')
        scheduler.step()
        (out / 'history.json').write_text(json.dumps(history, indent=2))
        print(f'Epoch {epoch:03d}/100 | loss {loss_sum/count:.4f} | validation {val:.2%}', flush=True)
    result = dict(config=config, best_validation_accuracy=best, epochs_completed=100)
    (out / 'complete.json').write_text(json.dumps(result, indent=2))
    return result


@torch.inference_mode()
def extract_known(root, method='vanilla'):
    out, _, clean, plain, split = prepare(root, method)
    if not (out / 'complete.json').exists():
        raise RuntimeError('Finish the full training run before final known evaluation.')
    checkpoint = out / 'best.pt'
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    if saved['config'] != method_config(method) or saved['split'] != split:
        raise ValueError('Checkpoint protocol mismatch.')
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = make_model().to(device)
    model.load_state_dict(saved['model_state'])
    model.eval().requires_grad_(False)
    test = datasets.CIFAR10(Path(root) / 'data', train=False, download=True, transform=plain)
    summary = dict(selected_epoch=saved['epoch'], validation_accuracy=saved['validation_accuracy'],
                   checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                   unknowns_evaluated=False)
    for name, dataset, indices in [('train', clean, split['train']),
                                   ('validation', clean, split['validation']),
                                   ('test', test, list(range(len(test))))]:
        features, logits, labels = [], [], []
        for x, y in loader(Subset(dataset, indices)):
            f, z = forward_features(model, x.to(device))
            features.append(f.cpu().numpy())
            logits.append(z.cpu().numpy())
            labels.append(y.numpy())
        f, z, y = map(np.concatenate, (features, logits, labels))
        np.savez_compressed(out / f'{name}_outputs.npz', features=f, logits=z,
                            labels=y, indices=np.asarray(indices),
                            checkpoint_sha256=summary['checkpoint_sha256'])
        summary[f'{name}_accuracy'] = float((z.argmax(1) == y).mean())
    (out / 'known_evaluation.json').write_text(json.dumps(summary, indent=2))
    return summary
