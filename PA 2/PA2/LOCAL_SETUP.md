# Local PA2 setup

This directory is the `PA2/` folder in the course repository. Run assignment commands here, not from the parent directory.

## PowerShell

```powershell
cd 'D:\LUMS GAMING\6. 2026 Fall\CS 6304\Programming Assignments\PA 2\PA2'
. .\activate.ps1
python -m scripts.check_environment
python -m scripts.validate_assets
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python`. To keep runtime model caches local without activation, set `$env:HF_HOME = Join-Path (Get-Location) '.cache\huggingface'`.

## Reinstall on another machine

For Conda, run these commands from this directory. CUDA support comes from the PyTorch package and your NVIDIA driver.

```powershell
conda env create -f environment.yml
conda activate atml-pa2
$env:HF_HOME = Join-Path (Get-Location) '.cache\huggingface'
python -m scripts.download_assets
python -m scripts.validate_assets
python -m scripts.check_environment
```

The Conda file reproduces the package specifications; it has not been executed locally. The verified local installation uses `.venv`. Do not run `activate.ps1` when using the Conda environment, because that helper activates `.venv`.

For a standard Python virtual environment:

```powershell
python -m venv .venv
. .\activate.ps1
python -m pip install -r requirements.txt
python -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
python -m scripts.download_assets
python -m scripts.validate_assets
python -m scripts.check_environment
```

The CUDA PyTorch version matches `manifests/source_v2_environment.json` from the course asset release. The original requirements and scientific configurations are unchanged.

## Provenance and Git

- Starter: https://github.com/AbDu11aHHH/ATML-PA2-LLM-PostTraining
- Starter commit: `05543bec4fba95eba708eae9d6e15730d53ca317`
- Assets: `AbDu11aHHH/ATML-PA2-assets`, revision `0b350481fb03f5525a35bcdec4131bd4fe487f98`
- Policy: `Qwen/Qwen2.5-1.5B-Instruct`, with the released LoRA and experiment configurations.

The virtual environment, Hugging Face cache, downloaded course datasets/checkpoints, and training outputs are ignored. The fixed `data/word_limit_prompts.jsonl` is included in Git. Starter Git metadata is preserved in the parent's ignored `.setup/starter.git`; this folder is an ordinary directory in your course repository.

Public policy, reward, and judge models are downloaded at runtime. No training or assignment task implementation is part of this setup.

## Local verification

The course asset validator passes. All 87 release files checked against `manifests/sha256.json` match their hashes; the manifest's inconsistent self-entry is excluded and recorded in `results/setup/asset_checksums.json`.

CUDA execution and bitsandbytes NF4 quantization pass on the NVIDIA GeForce RTX 4050 Laptop GPU (6 GB VRAM), using PyTorch `2.11.0+cu128`. Logs and the installed package list are in `results/setup/`.
