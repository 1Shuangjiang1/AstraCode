param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$desktopRoot = Join-Path $projectRoot "desktop"
Set-Location -LiteralPath $desktopRoot
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js / npm was not found. Install Node.js first." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "Rust / Cargo was not found. Install Rust first." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if ($Install -or -not (Test-Path -LiteralPath (Join-Path $desktopRoot "node_modules"))) {
    Write-Host "Installing desktop dependencies..." -ForegroundColor Cyan
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dependency installation failed." -ForegroundColor Red
        Read-Host "Review the error above, then press Enter to close"
        exit $LASTEXITCODE
    }
}

Write-Host "Starting AstraCode Workbench. Close the app window to stop it..." -ForegroundColor Cyan
npm run tauri dev -- --no-watch

if ($LASTEXITCODE -ne 0) {
    Write-Host "Desktop launch failed with exit code $LASTEXITCODE." -ForegroundColor Red
    Read-Host "Review the error above, then press Enter to close"
    exit $LASTEXITCODE
}
