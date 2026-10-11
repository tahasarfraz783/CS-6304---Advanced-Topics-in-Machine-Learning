from __future__ import annotations

import argparse
from common.data import load_yaml
from task2_ppo.studies import run_forks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/ppo.yaml")
    args = ap.parse_args()
    cfg = load_yaml(args.config)
    print("KL beta conditions:", cfg["kl_values"])
    print("Fork update budget:", cfg["fork_updates"])
    run_forks(args.config, 'kl')


if __name__ == "__main__":
    main()
