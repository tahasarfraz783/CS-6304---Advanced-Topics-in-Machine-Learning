import collections
import concurrent.futures
import json
import random
import time
import urllib.request
import zipfile
from pathlib import Path
from .common import read, write, digest
from .scoring import normalize

VQA_ROOT = 'https://cvmlp.s3.amazonaws.com/vqa/mscoco/vqa/'


def selection_config(cfg):
    return {k:cfg[k] for k in ['seed', 'caption_images', 'caption_dev_images', 'ground_dev_pairs', 'ground_test_pairs', 'natural_train_counts', 'natural_dev_counts', 'natural_test_counts']}


def download(url, path, progress=None):
    path = Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.part')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r, open(tmp, 'wb') as f:
                size = int(r.headers.get('Content-Length', 0))
                done, last = 0, time.monotonic()
                while chunk := r.read(1024*1024):
                    f.write(chunk)
                    done += len(chunk)
                    if progress and time.monotonic()-last > 3:
                        progress.emit('download '+path.name, done, size, units='bytes')
                        last = time.monotonic()
                if size and size != done:
                    raise IOError('Incomplete download')
            tmp.replace(path)
            return
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def annotations(root, progress):
    raw = root/'data'/'raw'
    raw.mkdir(parents=True, exist_ok=True)
    archive = raw/'annotations_trainval2014.zip'
    coco_files = [f'{kind}_{split}2014.json' for kind in ['captions', 'instances'] for split in ['train', 'val']]
    if not all((raw/'annotations'/f).exists() for f in coco_files):
        download('https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2014.zip', archive, progress)
        with zipfile.ZipFile(archive) as z:
            for f in coco_files:
                z.extract('annotations/'+f, raw)
        archive.unlink()
    for split, name in [('train', 'Train'), ('val', 'Val')]:
        for suffix, filename in [
            ('Annotations', f'v2_mscoco_{split}2014_annotations.json'),
            ('Questions', f'v2_OpenEnded_mscoco_{split}2014_questions.json'),
            ('Complementary_Pairs', f'v2_mscoco_{split}2014_complementary_pairs.json')
        ]:
            if (raw/filename).exists():
                continue
            urlname = f'v2_{suffix}_{name}_mscoco.zip'
            archive = raw/urlname
            download(VQA_ROOT+urlname, archive, progress)
            with zipfile.ZipFile(archive) as z:
                with z.open(filename) as src, open(raw/filename, 'wb') as dst:
                    import shutil
                    shutil.copyfileobj(src, dst)
            archive.unlink()
    return raw


def natural_pool(raw, split, progress=None):
    questions = {x['question_id']: x for x in read(raw/f'v2_OpenEnded_mscoco_{split}2014_questions.json')['questions']}
    anns = {x['question_id']: x for x in read(raw/f'v2_mscoco_{split}2014_annotations.json')['annotations']}
    pairs = read(raw/f'v2_mscoco_{split}2014_complementary_pairs.json')
    pool, seen = [], set()
    for pair_index, (a, b) in enumerate(pairs):
        if progress and pair_index % 5000 == 0:
            progress.emit('normalize/filter natural '+split+' pairs', pair_index, len(pairs))
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        if a not in anns or b not in anns:
            continue
        aa, bb = anns[a], anns[b]
        if aa['image_id'] == bb['image_id'] or aa['answer_type'] != bb['answer_type']:
            continue
        if questions[a]['question'] != questions[b]['question']:
            continue
        pair = []
        for qid in [a, b]:
            ann = anns[qid]
            answers = [x['answer'] for x in ann['answers']]
            canonical, count = collections.Counter(map(normalize, answers)).most_common(1)[0]
            if count < 8 or len(answers) != 10 or not canonical:
                break
            target = next(x for x in answers if normalize(x) == canonical)
            pair.append(dict(id=f'vqa-{qid}', question_id=qid, image_id=ann['image_id'],
                             split=split+'2014', question=questions[qid]['question'], target=target,
                             canonical=canonical, answers=answers, kind=ann['answer_type'], suite='natural'))
        if len(pair) != 2 or pair[0]['canonical'] == pair[1]['canonical']:
            continue
        pid = f'vqa-{key[0]}-{key[1]}'
        for i, row in enumerate(pair):
            row.update(pair_id=pid, partner_id=pair[1-i]['id'], partner_image_id=pair[1-i]['image_id'],
                       partner_canonical=pair[1-i]['canonical'])
        pool.append(pair)
    return pool


def pick_natural(pool, counts, rng, excluded=None):
    used = set(excluded or [])
    selected = []
    for kind, count in zip(['yes/no', 'number', 'other'], counts):
        candidates = [p for p in pool if p[0]['kind'] == kind]
        rng.shuffle(candidates)
        n = 0
        for p in candidates:
            ids = {x['image_id'] for x in p}
            if ids & used:
                continue
            selected.append(p)
            used |= ids
            n += 1
            if n == count:
                break
        if n != count:
            raise ValueError(f'Insufficient image-disjoint {kind} pairs: {n}/{count}')
    return selected, used


PLURALS = {'person':'people', 'mouse':'mice', 'sheep':'sheep', 'knife':'knives',
           'bus':'buses', 'bench':'benches', 'couch':'couches', 'sandwich':'sandwiches', 'broccoli':'broccoli',
           'scissors':'scissors', 'skis':'skis', 'wine glass':'wine glasses',
           'sports ball':'sports balls', 'toothbrush':'toothbrushes'}


def object_index(instances, images):
    counts = {i: collections.Counter() for i in images}
    for ann in instances['annotations']:
        if ann['image_id'] in counts and not ann.get('iscrowd', 0):
            counts[ann['image_id']][ann['category_id']] += 1
    # Crowd regions make individual counts ambiguous: exclude that category/image from counting.
    crowds = {(a['image_id'], a['category_id']) for a in instances['annotations'] if a.get('iscrowd', 0)}
    pools = []
    for cat in instances['categories']:
        cid = cat['id']
        positive = [i for i, c in counts.items() if c[cid] or (i, cid) in crowds]
        negative = [i for i, c in counts.items() if not c[cid] and (i, cid) not in crowds]
        bins = {str(n): [i for i, c in counts.items() if c[cid] == n and (i, cid) not in crowds] for n in range(1, 5)}
        if cat['name'] == 'broccoli':
            # Fixed before model outputs after annotation-only inspection: boxed
            # broccoli groups do not define an unambiguous countable visual unit.
            bins = {str(n): [] for n in range(1, 5)}
        if positive and negative:
            pools.append(dict(category_id=cid, name=cat['name'], positive=positive, negative=negative, bins=bins))
    return pools


def ground_pair(pools, kind, rng, split, serial):
    eligible = [p for p in pools if kind == 'presence' or sum(bool(v) for v in p['bins'].values()) >= 2]
    p = rng.choice(eligible)
    name = p['name']
    if kind == 'presence':
        images = [rng.choice(p['positive']), rng.choice(p['negative'])]
        targets = ['yes', 'no']
        question = f'Does this image contain {name}?'
    else:
        targets = rng.sample([n for n, v in p['bins'].items() if v], 2)
        images = [rng.choice(p['bins'][n]) for n in targets]
        plural = PLURALS.get(name, name+'s')
        question = f'How many {plural} can you see?'
    pid = f'ground-{split}-{kind}-{serial}'
    return [dict(id=pid+f'-{i}', pair_id=pid, image_id=images[i], split=split,
                 partner_id=pid+f'-{1-i}', partner_image_id=images[1-i],
                 question=question, target=targets[i], canonical=targets[i], answers=[targets[i]],
                 partner_canonical=targets[1-i], kind=kind, suite='grounding', category_id=p['category_id'])
            for i in range(2)]


def pick_ground(instances, available, count, rng, split):
    pools = object_index(instances, available)
    chosen, used = [], set()
    for i in range(count):
        kind = 'presence' if i < count//2 else 'counting'
        for _ in range(100000):
            p = ground_pair(pools, kind, rng, split, i)
            ids = {x['image_id'] for x in p}
            if not ids & used:
                chosen.append(p)
                used |= ids
                break
        else:
            raise ValueError('Cannot construct disjoint grounding pairs')
    return chosen, used


def mismatches(pairs, rng):
    result = {}
    for pair in pairs:
        banned = {x['image_id'] for x in pair}
        choices = sorted({r['image_id'] for p in pairs if p[0]['pair_id'] != pair[0]['pair_id'] for r in p} - banned)
        if not choices:
            raise ValueError('No valid mismatched image')
        for row in pair:
            result[row['id']] = rng.choice(choices)
    return result


def audit(manifest):
    sets = {}
    for partition in ['train', 'dev', 'test']:
        data = manifest[partition]
        flat = data.get('captions', []) + [r for name in ['grounding', 'natural'] for p in data.get(name, []) for r in p]
        sets[partition] = {(r['split'], r['image_id']) for r in flat}
    assert not sets['train'] & sets['dev']
    assert not sets['train'] & sets['test']
    assert not sets['dev'] & sets['test']
    for part in ['train', 'dev', 'test']:
        for p in manifest[part].get('natural', []):
            assert len(p) == 2 and p[0]['question'] == p[1]['question']
            assert p[0]['canonical'] != p[1]['canonical']
            for r in p:
                assert sum(normalize(a) == r['canonical'] for a in r['answers']) >= 8
    return {k: len(v) for k, v in sets.items()}


def prepare(root, cfg, progress):
    dest = root/'prepared'/'manifest.json'
    if dest.exists():
        m = read(dest)
        assert digest({k:v for k,v in m.items() if k != 'selection_hash'}) == m['selection_hash']
        audit(m)
        return m
    bundled = Path(__file__).resolve().parents[1]/'inputs'/'selected_manifest.json'
    if bundled.exists():
        m = read(bundled)
        if m.get('data_selection_config') == selection_config(cfg):
            expected = m['selection_hash']
            assert digest({k:v for k,v in m.items() if k != 'selection_hash'}) == expected
            audit(m)
            write(dest, m)
            progress.emit('reuse locally verified official-data selection', 1, 1)
            return m
    raw = annotations(root, progress)
    rng = random.Random(cfg['seed'])
    progress.emit('select image-disjoint data')
    train_inst = read(raw/'annotations'/'instances_train2014.json')
    val_inst = read(raw/'annotations'/'instances_val2014.json')
    train_caps = read(raw/'annotations'/'captions_train2014.json')
    val_caps = read(raw/'annotations'/'captions_val2014.json')
    cap_index = collections.defaultdict(list)
    for a in train_caps['annotations']:
        cap_index[a['image_id']].append(a)
    train_ids = rng.sample(sorted(i for i, v in cap_index.items() if len(v) >= 3), cfg['caption_images'])
    captions = []
    for iid in train_ids:
        for a in rng.sample(cap_index[iid], 3):
            captions.append(dict(id=f"caption-{a['id']}", caption_id=a['id'], image_id=iid,
                                 split='train2014', question='Describe this image.', target=a['caption'], kind='caption'))
    train_nat, _ = pick_natural(natural_pool(raw, 'train', progress), cfg['natural_train_counts'], rng)
    val_pool = natural_pool(raw, 'val', progress)
    test_nat, test_used = pick_natural(val_pool, cfg['natural_test_counts'], rng)
    dev_nat, used = pick_natural(val_pool, cfg['natural_dev_counts'], rng, test_used)
    val_ids = {x['id'] for x in val_inst['images']}
    test_ground, test_ground_ids = pick_ground(val_inst, val_ids-used, cfg['ground_test_pairs'], rng, 'val2014')
    used |= test_ground_ids
    dev_ground, dev_ground_ids = pick_ground(val_inst, val_ids-used, cfg['ground_dev_pairs'], rng, 'val2014-dev')
    # Image filenames still use val2014, while pair IDs identify their partition.
    for p in dev_ground:
        for r in p:
            r['split'] = 'val2014'
    used |= dev_ground_ids
    dev_cap_index = collections.defaultdict(list)
    for a in val_caps['annotations']:
        dev_cap_index[a['image_id']].append(a)
    dev_ids = rng.sample(sorted(set(dev_cap_index)-used), cfg['caption_dev_images'])
    dev_captions = []
    for iid in dev_ids:
        a = rng.choice(dev_cap_index[iid])
        dev_captions.append(dict(id=f"caption-{a['id']}", caption_id=a['id'], image_id=iid,
                                 split='val2014', question='Describe this image.', target=a['caption'], kind='caption'))
    # Limit grounding pool images to the union already needed for captions/natural training.
    # Unique training-pair pool size is unrestricted; all categories remain eligible where available.
    train_image_ids = set(train_ids) | {r['image_id'] for p in train_nat for r in p}
    train_pools = object_index(train_inst, train_image_ids)
    image_meta = {}
    for split, inst in [('train2014', train_inst), ('val2014', val_inst)]:
        for im in inst['images']:
            if im['id'] not in (train_image_ids if split == 'train2014' else used | set(dev_ids)):
                continue
            image_meta[f"{split}/{im['id']}"] = dict(file_name=im['file_name'], url=im.get('coco_url', f"https://images.cocodataset.org/{split}/{im['file_name']}"))
    manifest = dict(seed=cfg['seed'], train=dict(captions=captions, natural=train_nat, pools=train_pools),
                    dev=dict(captions=dev_captions, grounding=dev_ground, natural=dev_nat),
                    test=dict(grounding=test_ground, natural=test_nat), images=image_meta,
                    annotation_policy='Presence: any annotation incl. crowd; negative: no category annotation. Counts: noncrowd instances; category/image with crowd excluded; broccoli excluded from counting because grouped florets have ambiguous units (annotation-only inspection before model predictions). Absence is annotation-based, not guaranteed visual absence.',
                    qualitative_rule='First three sorted pair IDs per suite and type, fixed before training; no selection by prediction.')
    manifest['mismatches'] = {suite: mismatches(manifest['test'][suite], rng) for suite in ['grounding', 'natural']}
    wanted = {(r['image_id'], r['category_id']) for partition in ['dev', 'test'] for p in manifest[partition]['grounding'] for r in p}
    boxes = collections.defaultdict(list)
    for ann in val_inst['annotations']:
        key = (ann['image_id'], ann['category_id'])
        if key in wanted:
            boxes[f'{key[0]}/{key[1]}'].append(dict(annotation_id=ann['id'], bbox=ann['bbox'], iscrowd=ann.get('iscrowd', 0)))
    manifest['grounding_review_boxes'] = dict(boxes)
    manifest['audit'] = audit(manifest)
    manifest['data_selection_config'] = selection_config(cfg)
    manifest['selection_hash'] = digest(manifest)
    write(dest, manifest)
    return manifest


def label_review(root, manifest):
    """Prediction-independent evidence for human inspection of all grounding eval labels."""
    import html
    from PIL import Image, ImageDraw
    from .common import table
    dest = root/'evidence'/'label_review'
    dest.mkdir(parents=True, exist_ok=True)
    review, cards = [], []
    for partition in ['dev', 'test']:
        for pair in manifest[partition]['grounding']:
            for row in pair:
                boxes = manifest['grounding_review_boxes'].get(f"{row['image_id']}/{row['category_id']}", [])
                actual = len([b for b in boxes if not b['iscrowd']])
                assert (bool(boxes) == (row['target'] == 'yes')) if row['kind'] == 'presence' else actual == int(row['target'])
                filename = row['id']+'.jpg'
                if not (dest/filename).exists():
                    with Image.open(image_path(root, manifest, row['split'], row['image_id'])) as src:
                        im = src.convert('RGB')
                    draw = ImageDraw.Draw(im)
                    for box in boxes:
                        x, y, w, h = box['bbox']
                        draw.rectangle((x, y, x+w, y+h), outline='orange' if box['iscrowd'] else 'red', width=3)
                    im.thumbnail((500, 400))
                    im.save(dest/filename, quality=85)
                review.append(dict(partition=partition, id=row['id'], pair_id=row['pair_id'], image_id=row['image_id'],
                    question=row['question'], annotation_target=row['target'], human_label_valid='', human_notes=''))
                cards.append('<article><h3>'+html.escape(partition+' / '+row['id'])+'</h3><p>'+html.escape(row['question'])+'</p><b>Annotation target: '+html.escape(row['target'])+'</b><br><img src="'+filename+'"></article>')
    table(dest/'review_template.csv', review)
    (dest/'index.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;background:#eee}main{display:flex;flex-wrap:wrap;gap:20px}article{background:white;padding:15px;width:500px}img{max-width:100%}</style><h1>Grounding label review — independent of model outputs</h1><p>All dev/test grounding labels. Red: category-instance boxes; orange: crowd. Missing annotations do not prove visual absence. Record your inspection in review_template.csv; do not change labels based on predictions.</p><main>'+''.join(cards)+'</main>', encoding='utf-8')


def selected_images(manifest):
    result = set()
    for part in ['train', 'dev', 'test']:
        data = manifest[part]
        for r in data.get('captions', []) + [r for k in ['natural', 'grounding'] for p in data.get(k, []) for r in p]:
            result.add((r['split'], r['image_id']))
    return sorted(result)


def image_path(root, manifest, split, iid):
    return root/'data'/'images'/split/manifest['images'][f'{split}/{iid}']['file_name']


def download_images(root, manifest, cfg, progress):
    images = selected_images(manifest)
    progress.emit('download selected images', 0, len(images))
    def one(key):
        split, iid = key
        info = manifest['images'][f'{split}/{iid}']
        url = info['url'].replace('http://images.cocodataset.org/', 'https://s3.amazonaws.com/images.cocodataset.org/').replace('https://images.cocodataset.org/', 'https://s3.amazonaws.com/images.cocodataset.org/')
        download(url, image_path(root, manifest, split, iid))
    with concurrent.futures.ThreadPoolExecutor(cfg['download_workers']) as executor:
        futures = [executor.submit(one, x) for x in images]
        for i, f in enumerate(concurrent.futures.as_completed(futures), 1):
            f.result()
            if i % 50 == 0 or i == len(images):
                progress.emit(completed=i)


class Sampler:
    def __init__(self, manifest, seed):
        self.m = manifest
        self.rng = random.Random(seed)
        self.caption_order = []
        self.caption_position = 0
        self.draws = 0

    def batch(self, stage, size=16):
        data, counts = [], collections.Counter()
        if stage == 1:
            for _ in range(size):
                if self.caption_position == len(self.caption_order):
                    self.caption_order = list(range(len(self.m['train']['captions'])))
                    self.rng.shuffle(self.caption_order)
                    self.caption_position = 0
                data.append(self.m['train']['captions'][self.caption_order[self.caption_position]])
                self.caption_position += 1
                counts['caption'] += 1
        else:
            for _ in range(size//2):
                components, weights = (['presence', 'counting', 'caption'], [.5, .25, .25]) if stage == 2 else (['natural', 'presence', 'counting', 'caption'], [.7, .1, .1, .1])
                kind = self.rng.choices(components, weights)[0]
                if kind == 'caption':
                    pair = [self.rng.choice(self.m['train']['captions']) for _ in range(2)]
                elif kind == 'natural':
                    pair = self.rng.choice(self.m['train']['natural'])
                else:
                    pair = ground_pair(self.m['train']['pools'], kind, self.rng, 'train2014', self.draws)
                data.extend(pair)
                counts[kind] += 2
                self.draws += 1
        return data, dict(counts)

    def state_dict(self):
        return dict(rng=self.rng.getstate(), caption_order=self.caption_order,
                    caption_position=self.caption_position, draws=self.draws)

    def load_state_dict(self, state):
        self.rng.setstate(state['rng'])
        for key in ['caption_order', 'caption_position', 'draws']:
            setattr(self, key, state[key])
