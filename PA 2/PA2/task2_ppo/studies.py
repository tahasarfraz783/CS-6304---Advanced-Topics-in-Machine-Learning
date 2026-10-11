"""Serial matched forks in isolated processes, releasing CUDA state on exit."""
import subprocess
import sys
from common.data import load_yaml, repo_path
from common.logging_utils import save_json, load_json


def run_command(module, *arguments):
    subprocess.run([sys.executable, '-m', module, *map(str, arguments)],
                   cwd=repo_path('.'), check=True)


def run_forks(config_path, kind):
    cfg = load_yaml(config_path)
    results = []
    conditions = cfg['clip_values' if kind == 'clip' else 'kl_values']
    for condition in conditions:
        name = f'{kind}_{condition:.2f}'
        output = f'outputs/task2_ppo/{name}'
        summary_path = repo_path(cfg['results_dir']) / f'{name}_summary.json'
        eval_path = repo_path(cfg['results_dir']) / f'{name}_evaluation.json'
        if summary_path.exists():
            training = load_json(summary_path)
            saved = training['config']
            if (training['updates'] != cfg['fork_updates'] or saved['seed'] != cfg['seed'] or
                saved['clip_epsilon'] != (condition if kind == 'clip' else cfg['clip_epsilon']) or
                saved['kl_beta'] != (condition if kind == 'kl' else cfg['kl_beta'])):
                raise ValueError(f'Existing {name} has incompatible settings')
        else:
            flag = '--clip-epsilon' if kind == 'clip' else '--kl-beta'
            run_command('task2_ppo.continue_train', '--config', repo_path(config_path),
                        '--output', output, '--updates', cfg['fork_updates'],
                        '--run-name', name, flag, condition)
            training = load_json(summary_path)
        if not eval_path.exists():
            run_command('task2_ppo.evaluate', '--config', repo_path(config_path),
                        '--adapter', output, '--name', name)
        evaluation = load_json(eval_path)
        results.append({'condition': condition, 'training': training, 'evaluation': evaluation})
        save_json(repo_path(cfg['results_dir']) / f'{kind}_comparison.json', results)
    budget = {'updates_per_fork': cfg['fork_updates'], 'prompts_per_update': cfg['prompts_per_update'],
              'max_generated_tokens_per_fork': cfg['fork_updates'] * cfg['prompts_per_update'] * cfg['max_response_length'],
              'actual_generated_tokens': {r['training']['run_name']: r['training']['generated_tokens'] for r in results},
              'note': 'Matched prompt IDs, seeds, update counts and generation caps. EOS can produce unequal actual token counts; report these explicitly.'}
    save_json(repo_path(cfg['results_dir']) / f'{kind}_budgets.json', budget)
    return results
