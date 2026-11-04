"""Live status viewer. Ctrl+C closes ONLY this viewer, not the experiment."""
import argparse
from pathlib import Path
import time

from task1.common import read_json
from task1.progress import show_status

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/assignment")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    root = (HERE / args.output).resolve()
    print("MONITOR ONLY. Ctrl+C closes this viewer; it does not stop training.\n", flush=True)
    try:
        while True:
            show_status(root)
            status = root / "pipeline_status.json"
            if status.exists() and read_json(status).get("state") in {"completed", "failed"}:
                print("Pipeline ended. Check the result/error above. Cloud billing is still your responsibility.")
                break
            if args.once:
                break
            print("\nNext status refresh in 10 seconds...\n", flush=True)
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nMonitor closed. The experiment was NOT stopped.")
