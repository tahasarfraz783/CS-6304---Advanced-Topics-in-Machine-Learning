import csv
import io
import subprocess
import threading
import time
from .common import jsonl


class Telemetry:
    def __init__(self, root):
        self.path = root/'gpu_samples.jsonl'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                process = subprocess.run(['nvidia-smi', '--query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8)
                if process.returncode == 0:
                    for values in csv.reader(io.StringIO(process.stdout)):
                        jsonl(self.path, dict(zip(['timestamp', 'gpu_percent', 'memory_controller_percent', 'used_MiB', 'total_MiB', 'power_W'], [v.strip() for v in values])))
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.stop.wait(10)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=9)
