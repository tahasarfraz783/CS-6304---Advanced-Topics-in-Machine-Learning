"""Repack large safetensors shards without changing tensor bytes or model weights."""
from __future__ import annotations
import json
import os
import shutil
import struct
from pathlib import Path
from huggingface_hub import snapshot_download
from common.data import repo_path


def repack_checkpoint(source, destination, shard_bytes=128 * 1024 * 1024):
    source, destination = Path(source), Path(destination)
    marker = destination / 'repack_complete.json'
    if marker.exists():
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    tensors = []
    for path in sorted(source.glob('*.safetensors')):
        with path.open('rb') as f:
            header_size = struct.unpack('<Q', f.read(8))[0]
            header = json.loads(f.read(header_size))
        for name, info in header.items():
            if name != '__metadata__':
                begin, end = info['data_offsets']
                if not 0 <= begin <= end <= path.stat().st_size - 8 - header_size:
                    raise ValueError(f'Invalid tensor offsets: {path}/{name}')
                tensors.append((name, info, path, 8 + header_size + begin, end - begin))
    if not tensors:
        raise ValueError(f'No model tensors in {source}')
    groups, group, size = [], [], 0
    for tensor in tensors:
        if group and size + tensor[4] > shard_bytes:
            groups.append(group)
            group, size = [], 0
        group.append(tensor)
        size += tensor[4]
    if group:
        groups.append(group)
    weight_map = {}
    for i, group in enumerate(groups, 1):
        name = f'model-{i:05d}-of-{len(groups):05d}.safetensors'
        header, offset = {'__metadata__': {'format': 'pt'}}, 0
        for key, info, _, _, length in group:
            header[key] = {**info, 'data_offsets': [offset, offset + length]}
            weight_map[key] = name
            offset += length
        encoded = json.dumps(header, separators=(',', ':')).encode()
        encoded += b' ' * ((-len(encoded)) % 8)
        temporary = destination / (name + '.tmp')
        with temporary.open('wb') as out:
            out.write(struct.pack('<Q', len(encoded)))
            out.write(encoded)
            for _, _, path, start, length in group:
                with path.open('rb') as f:
                    f.seek(start)
                    remaining = length
                    while remaining:
                        chunk = f.read(min(remaining, 8 * 1024 * 1024))
                        if not chunk:
                            raise ValueError(f'Unexpected end of {path}')
                        out.write(chunk)
                        remaining -= len(chunk)
        temporary.replace(destination / name)
    for name in ('config.json', 'generation_config.json'):
        if (source / name).exists():
            shutil.copyfile(source / name, destination / name)
    (destination / 'model.safetensors.index.json').write_text(json.dumps({
        'metadata': {'total_size': sum(t[4] for t in tensors)}, 'weight_map': weight_map}), encoding='utf-8')
    marker.write_text(json.dumps({'source': str(source), 'tensor_count': len(tensors), 'shards': len(groups)}), encoding='utf-8')
    return destination


def judge_checkpoint(cfg):
    if os.name != 'nt':
        return cfg['ai_judge_model']
    destination = repo_path('.cache/task5_judge_small_shards') / cfg['ai_judge_model'].replace('/', '--')
    if (destination / 'repack_complete.json').exists():
        return str(destination)
    source = snapshot_download(cfg['ai_judge_model'], allow_patterns=['*.safetensors', '*.json'])
    print('Preparing smaller judge checkpoint shards for Windows (weights unchanged)...', flush=True)
    return str(repack_checkpoint(source, destination))
