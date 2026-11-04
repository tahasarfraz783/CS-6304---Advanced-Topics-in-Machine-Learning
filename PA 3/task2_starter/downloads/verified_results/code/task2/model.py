import gc
import time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from .common import read, write
from .data import selected_images, image_path


class Images(torch.utils.data.Dataset):
    def __init__(self, root, manifest, keys, processor):
        self.root, self.manifest, self.keys, self.processor = root, manifest, keys, processor

    def __len__(self):
        return len(self.keys)

    def __getitem__(self, i):
        from PIL import Image
        split, iid = self.keys[i]
        with Image.open(image_path(self.root, self.manifest, split, iid)) as im:
            return self.processor(images=im.convert('RGB'), return_tensors='pt')['pixel_values'][0]


def cache_features(root, manifest, cfg, progress):
    from transformers import AutoImageProcessor, SiglipVisionModel
    dest = root/'prepared'/'features'
    dest.mkdir(parents=True, exist_ok=True)
    keys = selected_images(manifest)
    signature = dict(selection=manifest['selection_hash'], model=cfg['vision_model'], dtype='float16', shape=[196, 768])
    if (dest/'complete.json').exists():
        assert read(dest/'complete.json')['signature'] == signature
        return
    start = time.perf_counter()
    partial_timing = read(dest/'partial_timing.json') if (dest/'partial_timing.json').exists() else {'seconds':0., 'peak_gpu_bytes':0}
    torch.cuda.reset_peak_memory_stats()
    revision_path = dest/'revision.json'
    revision = read(revision_path)['revision'] if revision_path.exists() else None
    vision = SiglipVisionModel.from_pretrained(cfg['vision_model'], torch_dtype=torch.float16, attn_implementation='sdpa', revision=revision).cuda().eval()
    revision = getattr(vision.config, '_commit_hash', None)
    write(revision_path, dict(model=cfg['vision_model'], revision=revision))
    vision.requires_grad_(False)
    processor = AutoImageProcessor.from_pretrained(cfg['vision_model'], revision=revision)
    processor.save_pretrained(dest/'processor')
    write(dest/'vision_config.json', vision.config.to_dict())
    # Separate atomic shards allow interrupted caching to reuse all completed batches.
    progress.emit('SigLIP feature caching', 0, len(keys))
    shard_size = cfg['cache_batch']
    resume = 0
    while resume < len(keys) and (dest/f'{resume:07d}.npy').exists():
        arr = np.load(dest/f'{resume:07d}.npy', mmap_mode='r')
        assert arr.shape == (min(shard_size, len(keys)-resume), 196, 768) and arr.dtype == np.float16
        resume += shard_size
    # One persistent worker pool prefetches decoding/preprocessing while the GPU runs.
    loader = torch.utils.data.DataLoader(Images(root, manifest, keys[resume:], processor),
        batch_size=shard_size, num_workers=cfg['cache_workers'], pin_memory=True,
        persistent_workers=cfg['cache_workers'] > 0)
    for batch_index, pixels in enumerate(loader):
        first = resume+batch_index*shard_size
        shard = dest/f'{first:07d}.npy'
        selected = keys[first:first+shard_size]
        if shard.exists():
            arr = np.load(shard, mmap_mode='r')
            assert arr.shape == (len(selected), 196, 768) and arr.dtype == np.float16
        else:
            pixels = pixels.cuda(non_blocking=True).half()
            with torch.inference_mode():
                # last_hidden_state ALREADY includes SigLIP post_layernorm. Never apply it twice.
                features = vision(pixel_values=pixels).last_hidden_state
            assert features.shape[1:] == (196, 768) and torch.isfinite(features).all()
            with open(str(shard)+'.tmp', 'wb') as f:
                np.save(f, features.cpu().numpy().astype(np.float16))
            Path(str(shard)+'.tmp').replace(shard)
        progress.emit(completed=first+len(selected), cache_batch=shard_size)
        write(dest/'partial_timing.json', dict(seconds=partial_timing['seconds']+time.perf_counter()-start,
            peak_gpu_bytes=max(partial_timing['peak_gpu_bytes'], torch.cuda.max_memory_allocated())))
    torch.cuda.synchronize()
    write(dest/'complete.json', dict(signature=signature, keys=keys, shard_size=shard_size,
        seconds=partial_timing['seconds']+time.perf_counter()-start, peak_gpu_bytes=max(partial_timing['peak_gpu_bytes'], torch.cuda.max_memory_allocated()),
        model_commit=getattr(vision.config, '_commit_hash', None), preprocessing='Saved deterministic AutoImageProcessor; eval mode; exactly one final layer norm.'))
    del vision, processor
    gc.collect()
    torch.cuda.empty_cache()


class FeatureStore:
    def __init__(self, root, cfg, device='cpu'):
        dest = root/'prepared'/'features'
        meta = read(dest/'complete.json')
        arrays = [np.load(dest/f'{first:07d}.npy') for first in range(0, len(meta['keys']), meta['shard_size'])]
        self.data = torch.from_numpy(np.concatenate(arrays)).to(device)
        if device == 'cpu' and torch.cuda.is_available():
            self.data = self.data.pin_memory()
        self.index = {(s, i): j for j, (s, i) in enumerate(meta['keys'])}
        self.tokens = cfg['visual_tokens']

    def batch(self, examples, condition='correct', mismatch=None):
        ids = []
        for r in examples:
            iid = r['partner_image_id'] if condition == 'swap' else mismatch[r['id']] if condition == 'mismatched' else r['image_id']
            ids.append(self.index[(r['split'], iid)])
        result = self.data[torch.tensor(ids, device=self.data.device)].cuda(non_blocking=True)
        if self.tokens == 49:
            result = result.reshape(-1, 14, 14, 768).reshape(-1, 7, 2, 7, 2, 768).mean((2, 4)).reshape(-1, 49, 768)
        return result


class VLM(nn.Module):
    def __init__(self, cfg, revision=None):
        super().__init__()
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.cfg = cfg
        self.tokenizer = AutoTokenizer.from_pretrained(cfg['language_model'], revision=revision)
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.lm = AutoModelForCausalLM.from_pretrained(cfg['language_model'], torch_dtype=torch.float16,
                                                       attn_implementation='sdpa', revision=revision).cuda()
        assert self.lm.config.hidden_size == 1024
        self.lm.requires_grad_(False)
        self.lm.config.use_cache = False
        self.lm.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        self.connector = nn.Sequential(nn.Linear(768, 1024), nn.GELU(), nn.Linear(1024, 1024)).float().cuda()
        self.register_buffer('visual_scale', torch.tensor(1., device='cuda'))
        self.has_lora = False
        self.end_id = self.tokenizer.convert_tokens_to_ids('<|im_end|>')
        assert isinstance(self.end_id, int) and self.end_id != self.tokenizer.unk_token_id

    def enable_lora(self):
        if self.has_lora:
            return
        from peft import LoraConfig, get_peft_model
        self.lm = get_peft_model(self.lm, LoraConfig(r=16, lora_alpha=32, lora_dropout=.05,
            bias='none', target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj'], task_type='CAUSAL_LM'))
        for name, p in self.lm.named_parameters():
            if p.requires_grad:
                assert 'lora_' in name
                p.data = p.data.float()
        self.has_lora = True

    @property
    def device(self):
        return self.lm.get_input_embeddings().weight.device

    def prompt(self, question):
        tok = self.tokenizer
        q = tok.decode(tok.encode(question, add_special_tokens=False)[:self.cfg['question_cap']], skip_special_tokens=False)
        marker = 'VISUAL_INSERTION_SENTINEL_6304'
        full = tok.apply_chat_template([
            {'role':'system', 'content':'Answer the question using the image. Give a concise answer.'},
            {'role':'user', 'content':marker+q}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        before, after = full.split(marker)
        return tok.encode(before, add_special_tokens=False), tok.encode(after, add_special_tokens=False)

    def pack(self, examples, features, condition='correct', targets=True, include_end=True):
        emb = self.lm.get_input_embeddings()
        visuals = None if condition == 'none' else self.connector(features.float())*self.visual_scale
        seqs, labels = [], []
        for i, r in enumerate(examples):
            before, after = self.prompt(r['question'])
            chunks = [emb(torch.tensor(before, device=self.device))]
            if visuals is not None:
                chunks.append(visuals[i].to(emb.weight.dtype))
            chunks.append(emb(torch.tensor(after, device=self.device)))
            prefix = sum(x.shape[0] for x in chunks)
            y = []
            if targets:
                cap = self.cfg['caption_cap'] if r['kind'] == 'caption' else self.cfg['answer_cap']
                y = self.tokenizer.encode(r['target'], add_special_tokens=False)[:cap]
                if not y:
                    raise ValueError('Empty reference target')
                if include_end:
                    y.append(self.end_id)
                chunks.append(emb(torch.tensor(y, device=self.device)))
            seqs.append(torch.cat(chunks))
            labels.append(torch.tensor([-100]*prefix+y, device=self.device))
        length = max(len(s) for s in seqs)
        # Left padding for BOTH teacher forcing and generation; positions reset per example.
        values = torch.stack([F.pad(s, (0, 0, length-len(s), 0)) for s in seqs])
        mask = torch.stack([F.pad(torch.ones(len(s), device=self.device, dtype=torch.long), (length-len(s), 0)) for s in seqs])
        labels = torch.stack([F.pad(y, (length-len(y), 0), value=-100) for y in labels])
        positions = (mask.cumsum(-1)-1).clamp_min(0)
        return dict(inputs_embeds=values, attention_mask=mask, position_ids=positions), labels

    def losses(self, examples, features, condition='correct', include_end=True):
        inputs, labels = self.pack(examples, features, condition, True, include_end)
        base = self.lm.get_base_model() if self.has_lora else self.lm
        hidden = base.model(**inputs, use_cache=False).last_hidden_state[:, :-1]
        shifted = labels[:, 1:]
        valid = shifted != -100
        # Only project supervised positions to the 151k-word vocabulary. This avoids
        # materializing scores for ~196 visual tokens + every prompt in every example.
        logits = base.lm_head(hidden[valid])
        token_loss = F.cross_entropy(logits.float(), shifted[valid], reduction='none')
        owner = torch.arange(len(examples), device=self.device)[:, None].expand_as(shifted)[valid]
        sums = torch.zeros(len(examples), device=self.device).scatter_add(0, owner, token_loss)
        return sums/valid.sum(1).clamp_min(1)

    def generate(self, examples, features, condition='correct'):
        inputs, _ = self.pack(examples, features, condition, False)
        # HF derives generation positions from the rebuilt attention mask; explicit
        # prefix-only position_ids would otherwise be reused during cached decoding.
        inputs.pop('position_ids')
        output = self.lm.generate(**inputs, do_sample=False, max_new_tokens=16,
            eos_token_id=self.end_id, pad_token_id=self.tokenizer.pad_token_id,
            use_cache=True)
        return self.tokenizer.batch_decode(output, skip_special_tokens=True)

    def trainable_state(self):
        return {k: v.detach().cpu().clone() for k, v in self.named_parameters() if v.requires_grad}

    def load_trainable(self, state):
        params = dict(self.named_parameters())
        with torch.no_grad():
            for k, v in state.items():
                params[k].copy_(v.to(params[k]))

    def parameter_counts(self):
        return dict(connector=sum(p.numel() for p in self.connector.parameters()),
                    lora=sum(p.numel() for p in self.lm.parameters() if p.requires_grad),
                    frozen=sum(p.numel() for p in self.lm.parameters() if not p.requires_grad))

    def calibrate(self, examples, store):
        self.eval()
        with torch.no_grad():
            f = store.batch(examples)
            connector_rms = self.connector(f.float()).square().mean().sqrt()
            ids = [t for r in examples for t in self.tokenizer.encode(r['target'], add_special_tokens=False)[:64]]
            text_rms = self.lm.get_input_embeddings()(torch.tensor(ids, device='cuda')).float().square().mean().sqrt()
            self.visual_scale.copy_(text_rms/connector_rms.clamp_min(1e-8))
        return dict(rule='Fixed scalar = training-caption text-embedding RMS / initial connector-output RMS, first 64 selected training captions; no eval data.',
                    text_rms=text_rms.item(), connector_rms=connector_rms.item(), scale=self.visual_scale.item(),
                    example_ids=[r['id'] for r in examples])
