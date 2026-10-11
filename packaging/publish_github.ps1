param(
    [string]$Owner = "1Shuangjiang1",
    [string]$Repository = "AstraCode",
    [string]$Source,
    [switch]$InspectOnly,
    [string[]]$ReleaseAssets
)

$ErrorActionPreference = "Stop"
if ($Owner -notmatch '^[A-Za-z0-9-]+$' -or $Repository -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "Invalid GitHub owner or repository name."
}
$previousPrompt = $env:GIT_TERMINAL_PROMPT
$previousInteractive = $env:GCM_INTERACTIVE
try {
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'Never'
    # Use the already signed-in Git account; do not print or persist credentials.
    $query = "protocol=https`nhost=github.com`nusername=$Owner`n`n"
    $lines = $query | git credential fill
    if ($LASTEXITCODE -ne 0) { throw "No usable GitHub Git credential. Sign in with Git Credential Manager first." }
    $credential = @{}
    foreach ($line in $lines) {
        $pair = $line -split '=', 2
        if ($pair.Length -eq 2) { $credential[$pair[0]] = $pair[1] }
    }
    if (-not $credential['password']) { throw "GitHub credential has no token." }
    $headers = @{
        Authorization = "Bearer $($credential['password'])"
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $account = Invoke-RestMethod -Uri 'https://api.github.com/user' -Headers $headers -TimeoutSec 30
    if ($account.login -ne $Owner) { throw "Authenticated account does not match requested owner." }
    $repo = $null
    try {
        $repo = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repository" -Headers $headers -TimeoutSec 30
    } catch {
        if ([int]$_.Exception.Response.StatusCode -ne 404) { throw "GitHub repository lookup failed; check access and network." }
    }
    if ($InspectOnly) {
        [pscustomobject]@{ Account = $account.login; Repository = "$Owner/$Repository"; Exists = [bool]$repo; RemoteChanged = $false } | ConvertTo-Json
        return
    }
    if (-not $Source) { throw "Specify -Source with a validated public export directory." }
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'PUBLIC_SOURCE_MANIFEST.json'))) { throw "Source is not a public export." }
    if (Test-Path -LiteralPath (Join-Path $sourceRoot '.env')) { throw "Refusing to publish a directory containing .env." }
    $manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'PUBLIC_SOURCE_MANIFEST.json') -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $file = Join-Path $sourceRoot $entry.path
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw "Export changed after verification: $($entry.path)"
        }
    }
    $remote = "https://github.com/$Owner/$Repository.git"
    if ($repo) {
        $refs = git ls-remote $remote
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect remote refs." }
        if ($refs) { throw "Repository already has history. Refusing to overwrite; use a normal reviewed integration." }
        if ($repo.private) { throw "Existing repository is private. Refusing to change visibility automatically." }
    } else {
        $body = @{name=$Repository; description='Local desktop coding agent with plans, permissions, memory, multi-agent collaboration, verification and file previews.'; private=$false; auto_init=$false} | ConvertTo-Json
        $repo = Invoke-RestMethod -Method Post -Uri 'https://api.github.com/user/repos' -Headers $headers -Body $body -ContentType 'application/json' -TimeoutSec 30
        Write-Host "Created public repository: $($repo.html_url)"
    }
    Push-Location -LiteralPath $sourceRoot
    try {
        git init -b main
        if ($LASTEXITCODE -ne 0) { throw "git init failed" }
        git config user.name $Owner
        git config core.autocrlf false
        git config user.email "$($account.id)+$Owner@users.noreply.github.com"
        # Stage only files described by the verified manifest, plus the manifest.
        foreach ($entry in $manifest.files) {
            git add -- $entry.path
            if ($LASTEXITCODE -ne 0) { throw "git add failed" }
        }
        git add -- PUBLIC_SOURCE_MANIFEST.json
        git commit -m 'release: publish AstraCode Workbench 0.8.1 source'
        if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
        git remote add origin $remote
        if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
        git push -u origin main
        if ($LASTEXITCODE -ne 0) { throw "git push failed; inspect local and remote state before retrying" }
        Write-Host "Published: $($repo.html_url)"
        git rev-parse HEAD
        if ($ReleaseAssets) {
            foreach ($asset in $ReleaseAssets) {
                if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw "Release asset missing." }
            }
            $releaseBody = @{
                tag_name='v0.8.1'; target_commitish='main'; name='AstraCode Workbench 0.8.1'
                body="Windows x64 desktop coding agent. Download Setup.exe to install; Source.zip is for developers. Configure your own API Key in Settings. Includes plans, Todo, skills, multi-agent monitoring, file previews, Diff, undo and diagnostic logs. Installer is currently unsigned. See README for setup, usage and limitations. Offline checks: 84 passed; frontend production build passed. The installer is the existing 0.8.1 build, verified by SHA-256; not rebuilt in this publication."
                draft=$false; prerelease=$true
            } | ConvertTo-Json
            $release = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Owner/$Repository/releases" -Headers $headers -Body $releaseBody -ContentType 'application/json' -TimeoutSec 30
            foreach ($asset in $ReleaseAssets) {
                $assetPath = (Resolve-Path -LiteralPath $asset).Path
                $assetName = [IO.Path]::GetFileName($assetPath)
                $uploadUrl = ($release.upload_url -split '\{')[0] + '?name=' + [Uri]::EscapeDataString($assetName)
                $null = Invoke-RestMethod -Method Post -Uri $uploadUrl -Headers $headers -InFile $assetPath -ContentType 'application/octet-stream' -TimeoutSec 300
                Write-Host "Uploaded release asset: $assetName"
            }
            Write-Host "Release: $($release.html_url)"
        }
    } finally { Pop-Location }
} finally {
    $env:GIT_TERMINAL_PROMPT = $previousPrompt
    $env:GCM_INTERACTIVE = $previousInteractive
    if ($headers) { $headers.Clear() }
    if ($credential) { $credential.Clear() }
    $lines = $null
}
