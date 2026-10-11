"""Run the required GRPO experiments in separate processes."""
import argparse
import sys
from common.data import repo_path
from task3_grpo.process_utils import run_stage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/grpo.yaml')
    args = ap.parse_args()
    config = str(repo_path(args.config))
    commands = [
        ['task3_grpo.continue_train', '--config', config],
        ['task3_grpo.evaluate', '--config', config, '--adapter', 'outputs/task3_grpo/standard'],
        ['task3_grpo.analyze_group_size', '--config', config],
        ['task3_grpo.compare_normalization', '--config', config],
        ['task3_grpo.report_results', '--config', config],
    ]
    # Respect custom output paths for the standard branch.
    from common.data import load_yaml
    commands[1][-1] = load_yaml(config)['output']
    for command in commands:
        print('Running: ' + ' '.join(command), flush=True)
        run_stage([sys.executable, '-m', *command], cwd=repo_path('.'),
                  log_path=repo_path(load_yaml(config)['results_dir']) / 'run_all_console.log')


if __name__ == '__main__':
    main()
