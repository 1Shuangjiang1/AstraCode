param(
    [switch]$Offline,
    [ValidateSet("safe", "approval", "full_access")]
    [string]$PermissionMode
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if ($Offline) {
    $env:S_FULL_FAKE_CLIENT = "1"
}
elseif (-not (Test-Path -LiteralPath ".env")) {
    Write-Host "缺少 .env。请复制 .env.example 为 .env，并填写 API 配置；或使用 -Offline。" -ForegroundColor Yellow
    exit 1
}

if ($PermissionMode) {
    $env:S_FULL_PERMISSION_MODE = $PermissionMode
}

python .\s_full.py
