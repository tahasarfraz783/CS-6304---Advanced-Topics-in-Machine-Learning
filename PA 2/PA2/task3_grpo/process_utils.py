"""Lightweight subprocess logging without importing model libraries."""
import os
from pathlib import Path
import subprocess


def run_stage(command, cwd, log_path):
    if os.name == 'nt':
        import ctypes
        # Per-process setting inherited by children, not a Windows-wide change.
        # Preserve existing flags and suppress modal native crash dialogs.
        kernel = ctypes.windll.kernel32
        kernel.SetErrorMode(kernel.GetErrorMode() | 0x0002)
    env = os.environ.copy()
    env['PYTHONFAULTHANDLER'] = '1'
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as log:
        log.write('\nCOMMAND: ' + repr(command) + '\n')
        log.flush()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
        code = process.wait()
        log.write(f'EXIT CODE: {code}\n')
    if code:
        native = f' (Windows code 0x{code & 0xffffffff:08X})' if os.name == 'nt' else ''
        raise RuntimeError(f'Stage failed with exit code {code}{native}. Console log: {log_path}. '
                           'An access violation is a native-library crash; its code alone does not identify the cause.')
