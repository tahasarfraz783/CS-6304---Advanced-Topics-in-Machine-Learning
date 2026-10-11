# Run from PowerShell with: . .\activate.ps1
$env:HF_HOME = Join-Path $PSScriptRoot '.cache\huggingface'
. (Join-Path $PSScriptRoot '.venv\Scripts\Activate.ps1')
