"""Offline HTML dashboard and vector/raster evidence, updated every 25 updates."""
import html
import json
import shutil
from pathlib import Path
from .common import read, rows, table, write


def build_evidence(root, live=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'figure.dpi':120, 'savefig.dpi':180, 'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    dest = root/'evidence'
    dest.mkdir(parents=True, exist_ok=True)
    config = read(root/'resolved_config.json') if (root/'resolved_config.json').exists() else {}
    budgets = config.get('stage_updates', [2250, 1500, 750])
    boundaries = [budgets[0], budgets[0]+budgets[1]]
    training = rows(root/'training.jsonl')
    if live:
        # Keep live rendering cheap: raster only. Vector/PDF evidence is rebuilt
        # at development evaluations and endpoints, rather than on every refresh.
        for name, key, ylabel, scale in [('training_loss', 'loss', 'Training loss', 1), ('throughput', 'examples_per_second', 'Examples / second', 1), ('memory', 'peak_gpu_bytes', 'Peak allocated GiB', 2**30)]:
            fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
            ax.plot([r['update'] for r in training], [r[key]/scale for r in training])
            for b in boundaries:
                ax.axvline(b, ls='--', color='#888')
            ax.set(xlabel='Main-run update', ylabel=ylabel, title=ylabel)
            fig.savefig(dest/(name+'.png'))
            plt.close(fig)
        return
    dev = [read(p) for p in sorted((root/'evaluations').glob('dev_*.json')) if p.stem[4:].isdigit()]
    figures = []

    def save(name, title, lines, ylabel, stages=True, bands=None):
        if not lines:
            return
        fig, ax = plt.subplots(figsize=(9, 4.2), constrained_layout=True)
        for label, x, y in lines:
            ax.plot(x, y, label=label, linewidth=1.6, marker='o' if len(x) < 30 else None, markersize=3)
        if stages:
            for b in boundaries:
                ax.axvline(b, color='#777', ls='--', lw=1)
            ax.set_xlabel('Main-run update')
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
        for ext in ['svg', 'png', 'pdf']:
            fig.savefig(dest/(name+'.'+ext))
        plt.close(fig)
        figures.append((name, title))

    if training:
        x = [r['update'] for r in training]
        loss = [r['loss'] for r in training]
        smooth = [sum(loss[max(0, i-24):i+1])/len(loss[max(0, i-24):i+1]) for i in range(len(loss))]
        save('training_loss', 'Training loss (25-update moving average)', [('raw', x, loss), ('mean 25', x, smooth)], 'Example-weighted supervised loss')
        save('throughput', 'Measured training throughput', [('examples/s', x, [r['examples_per_second'] for r in training])], 'Examples / second')
        save('memory', 'GPU memory during training', [(k, x, [r[k]/2**30 for r in training]) for k in ['peak_gpu_bytes', 'allocated_gpu_bytes', 'reserved_gpu_bytes']], 'GiB')
        save('learning_rates', 'Per-stage learning rates', [(k, x, [r[k] for r in training]) for k in ['lr_connector', 'lr_lora']], 'Learning rate')
        keys = sorted({k for r in training for k in r['mixture']})
        import itertools
        save('mixture', 'Cumulative sampled example presentations', [(k, x, list(itertools.accumulate(r['mixture'].get(k, 0) for r in training))) for k in keys], 'Examples')
        table(dest/'training.csv', [dict((k, json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()) for r in training])
    else:
        for name, title, ylabel in [('training_loss', 'Training loss — waiting for updates', 'Loss'), ('throughput', 'Throughput — waiting for updates', 'Examples/s'), ('memory', 'Memory — waiting for updates', 'GiB')]:
            save(name, title, [('pending', [], [])], ylabel)
    if dev:
        x = [r['update'] for r in dev]
        table(dest/'development.csv', dev)
        save('caption_dev_loss', 'Development caption reference loss', [('caption', x, [r['captions_correct_nll'] for r in dev])], 'Loss including end of turn')
        for suite in ['grounding', 'natural']:
            save(suite+'_dev_nll', suite.title()+' development answer likelihood', [(c, x, [r[suite+'_'+c+'_nll'] for r in dev]) for c in ['correct', 'swap', 'none']], 'Reference answer NLL (termination excluded)')
        save('swap_penalties', 'Development image-swap penalties', [(s, x, [r[s+'_swap_penalty'] for r in dev]) for s in ['grounding', 'natural']], 'NLL(swap) − NLL(correct)')
    resources = read(root/'resources.json') if (root/'resources.json').exists() else {}
    gpu = rows(root/'gpu_samples.jsonl')
    if gpu:
        try:
            save('gpu_utilization', 'Sampled GPU utilization (10-second cadence)', [('GPU %', list(range(len(gpu))), [float(r['gpu_percent']) for r in gpu])], 'GPU utilization %', stages=False)
            table(dest/'gpu_samples.csv', gpu)
        except ValueError:
            pass
    resource_rows = [dict(stage=k, **v) for k, v in resources.items()]
    cache = root/'prepared'/'features'/'complete.json'
    if cache.exists():
        c = read(cache)
        resource_rows.append(dict(stage='feature_cache', seconds=c['seconds'], peak_gpu_bytes=c['peak_gpu_bytes']))
    table(dest/'resources.csv', resource_rows)
    summary_path = root/'evaluations'/'final_summary.json'
    summary = read(summary_path) if summary_path.exists() else []
    table(dest/'final_results.csv', summary)
    if summary:
        compact = []
        for r in summary:
            c = {k:r[k] for k in ['suite', 'kind', 'condition', 'pairs']}
            for metric in ['accuracy', 'pair_accuracy', 'identical_rate', 'empty_rate', 'nll', 'seconds_per_answer']:
                if metric in r:
                    scale = 1 if metric in ['nll', 'seconds_per_answer'] else 100
                    name = metric+('_percent_95ci' if scale == 100 else '_95ci')
                    c[name] = f"{r[metric]*scale:.3f} [{r[metric+'_lo']*scale:.3f}, {r[metric+'_hi']*scale:.3f}]"
            compact.append(c)
        table(dest/'final_compact_tables.csv', compact)
    if summary:
        for suite in ['grounding', 'natural']:
            for metric in ['accuracy', 'pair_accuracy', 'nll', 'identical_rate', 'empty_rate', 'partner_follow_rate', 'unsupported_rate']:
                subset = [r for r in summary if r['suite'] == suite and r['kind'] == 'all' and r['condition'] != 'correct_advantage_over_swap']
                fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
                values = [r[metric] for r in subset]
                ax.bar([r['condition'] for r in subset], values, color=['#2979b8', '#ea8c23', '#956bb0', '#819095'],
                       yerr=[[max(0., v-r[metric+'_lo']) for r, v in zip(subset, values)], [max(0., r[metric+'_hi']-v) for r, v in zip(subset, values)]], capsize=4)
                ax.set_title(suite.title()+' — '+metric.replace('_', ' '))
                ax.set_ylabel('NLL' if metric == 'nll' else 'Fraction')
                if metric != 'nll':
                    ax.set_ylim(0, 1.05)
                name = suite+'_final_'+metric
                for ext in ['png', 'svg', 'pdf']:
                    fig.savefig(dest/(name+'.'+ext))
                plt.close(fig)
                figures.append((name, ax.get_title()))
    manifest_path = root/'prepared'/'manifest.json'
    qualitative = []
    if manifest_path.exists():
        manifest = read(manifest_path)
        final = {(r['id'], r['condition']): r for r in rows(root/'evaluations'/'final_examples.jsonl')}
        from .data import image_path
        for suite in ['grounding', 'natural']:
            pairs = manifest['test'][suite]
            for kind in sorted({p[0]['kind'] for p in pairs}):
                chosen = sorted([p for p in pairs if p[0]['kind'] == kind], key=lambda p:p[0]['pair_id'])[:3]
                for pair in chosen:
                    cells = []
                    for r in pair:
                        source = image_path(root, manifest, r['split'], r['image_id'])
                        imgdest = dest/'qualitative_images'/source.name
                        if source.exists() and not imgdest.exists():
                            imgdest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, imgdest)
                        predictions = {c: final.get((r['id'], c), {}).get('prediction', '[pending]') for c in ['correct', 'swap', 'mismatched', 'none']}
                        qualitative.append(dict(suite=suite, kind=kind, pair_id=r['pair_id'], id=r['id'], question=r['question'], reference=r['target'], **predictions))
                        cells.append('<section><img src="qualitative_images/'+html.escape(source.name)+'"><p>Reference: '+html.escape(r['target'])+'</p>'+''.join('<p>'+c+': '+html.escape(p)+'</p>' for c, p in predictions.items())+'</section>')
                    # Self-contained aligned pairs; images are copied into downloadable evidence.
                    if 'qual_html' not in locals():
                        qual_html = []
                    qual_html.append('<article><h3>'+html.escape(suite+' / '+kind+' / '+pair[0]['pair_id'])+'</h3><p>'+html.escape(pair[0]['question'])+'</p><div class="pair">'+''.join(cells)+'</div></article>')
        table(dest/'qualitative.csv', qualitative)
        (dest/'qualitative.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;max-width:1100px;margin:auto} .pair{display:flex;gap:30px}.pair section{width:48%}img{max-width:100%;height:250px;object-fit:contain}article{border-bottom:1px solid #ccc}</style><h1>Fixed-selection complementary pairs</h1><p>'+html.escape(manifest['qualitative_rule'])+'</p>'+''.join(locals().get('qual_html', [])), encoding='utf-8')
    status = read(root/'progress.json') if (root/'progress.json').exists() else {}
    table_html = ''
    if summary:
        cols = ['suite', 'kind', 'condition', 'pairs', 'accuracy', 'pair_accuracy', 'identical_rate', 'empty_rate', 'nll', 'seconds_per_answer']
        table_html = '<h2>Final results (fractions; full intervals in CSV)</h2><div style="overflow:auto"><table><tr>'+''.join('<th>'+k+'</th>' for k in cols)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(f'{r[k]:.4f}' if isinstance(r.get(k), float) else str(r.get(k, '')))+'</td>' for k in cols)+'</tr>' for r in summary)+'</table></div>'
    text = '''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>Task 2 live evidence</title><style>body{background:#101722;color:#e6edf4;font:16px system-ui;max-width:1200px;margin:30px auto;padding:20px}a{color:#74c8ff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:20px}.card{background:white;color:#111;padding:12px;border-radius:12px}.card img{width:100%}pre{white-space:pre-wrap;background:#1d2a3a;padding:18px}td,th{padding:8px;border-bottom:1px solid #415064}table{border-collapse:collapse;font-size:12px}</style></head><body><h1>Task 2 — live progress and evidence</h1><p>Refreshes every 30 seconds; live loss/speed/memory every 50 updates; complete vector/PDF evidence at development evaluations and endpoints. Status below is a snapshot; use monitor.py for 15-second heartbeats and activity age.</p>'''
    text += '<pre id="status">'+html.escape(json.dumps(status, indent=2))+'</pre><script>setInterval(async()=>{try{let r=await fetch("../progress.json?t="+Date.now());let s=await r.json();s.snapshot_age_seconds=(Date.now()/1000-s.timestamp).toFixed(0);document.getElementById("status").textContent=JSON.stringify(s,null,2)}catch(e){}},5000)</script><p>'
    text += ' · '.join('<a href="'+p.name+'">'+p.name+'</a>' for p in sorted(dest.glob('*.csv')))
    text += ' · <a href="qualitative.html">Aligned image pairs</a> · <a href="label_review/index.html">Independent grounding label review</a></p>'+table_html+'<div class="grid">'
    for name, title in figures:
        text += '<div class="card"><h3>'+html.escape(title)+'</h3><a href="'+name+'.svg"><img src="'+name+'.png"></a><a href="'+name+'.pdf">PDF</a></div>'
    text += '</div><p>Local subset results only. Empty outputs remain in denominators. CIs: 4,000 complete-pair bootstrap draws; differences use matched pair indices. Dashed lines mark stage boundaries.</p></body></html>'
    (dest/'index.html').write_text(text, encoding='utf-8')
