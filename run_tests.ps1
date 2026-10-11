$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
python -m compileall -q .\agent_harness .\s_full.py .\tests
python -m unittest discover -s tests -v
