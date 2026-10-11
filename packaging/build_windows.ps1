param(
    [switch]$SkipDependencyInstall,
    [switch]$SidecarOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $ProjectRoot "desktop"
$TauriRoot = Join-Path $DesktopRoot "src-tauri"
$BuildRoot = Join-Path $ProjectRoot "packaging\build"
$SidecarDist = Join-Path $BuildRoot "sidecar-dist"
$SidecarWork = Join-Path $BuildRoot "sidecar-work"
$SidecarSpec = Join-Path $BuildRoot "sidecar-spec"
$BuildVenv = Join-Path $BuildRoot "release-venv"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$ResourceRoot = Join-Path $TauriRoot "resources"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$Version = "0.8.1"

if (-not (Test-Path -LiteralPath $BuildPython -PathType Leaf)) {
    python -m venv $BuildVenv
}
if (-not $SkipDependencyInstall) {
    & $BuildPython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements-release.txt")
}

New-Item -ItemType Directory -Force -Path $SidecarDist, $SidecarWork, $SidecarSpec, $ResourceRoot, $ReleaseRoot | Out-Null

& $BuildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name astracode-sidecar `
    --paths $ProjectRoot `
    --add-data "$(Join-Path $ProjectRoot 'skills');skills" `
    --distpath $SidecarDist `
    --workpath $SidecarWork `
    --specpath $SidecarSpec `
    (Join-Path $ProjectRoot "packaging\sidecar_entry.py")

$BuiltSidecar = Join-Path $SidecarDist "astracode-sidecar.exe"
if (-not (Test-Path -LiteralPath $BuiltSidecar -PathType Leaf)) {
    throw "Python sidecar build did not produce $BuiltSidecar"
}
Copy-Item -LiteralPath $BuiltSidecar -Destination (Join-Path $ResourceRoot "astracode-sidecar.exe") -Force

if ($SidecarOnly) {
    Write-Host "Sidecar ready: $BuiltSidecar"
    exit 0
}

Push-Location $DesktopRoot
try {
    npm run tauri build -- --bundles nsis
} finally {
    Pop-Location
}

$Installer = Get-ChildItem -LiteralPath (Join-Path $TauriRoot "target\release\bundle\nsis") -Filter "*-setup.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $Installer) {
    throw "Tauri did not produce an NSIS setup executable."
}

$ReleaseInstaller = Join-Path $ReleaseRoot "AstraCode-Workbench-v$Version-Windows-x64-Setup.exe"
Copy-Item -LiteralPath $Installer.FullName -Destination $ReleaseInstaller -Force
$Hash = (Get-FileHash -LiteralPath $ReleaseInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$ReleaseInstaller.sha256" -Value "$Hash  $([IO.Path]::GetFileName($ReleaseInstaller))" -Encoding ascii

Write-Host "Installer: $ReleaseInstaller"
Write-Host "SHA256: $Hash"
