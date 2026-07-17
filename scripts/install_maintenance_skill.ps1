$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Source = Join-Path $Root 'skills\kdesk-maintenance'
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$Target = Join-Path $CodexHome 'skills\kdesk-maintenance'

if (-not (Test-Path -LiteralPath (Join-Path $Source 'SKILL.md'))) {
    throw "Version-controlled maintenance Skill is missing: $Source"
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $Target))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
}
if (Test-Path -LiteralPath $Target) {
    $resolvedTarget = (Resolve-Path -LiteralPath $Target).Path
    $resolvedSkillsRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $Target)).Path
    if (-not $resolvedTarget.StartsWith($resolvedSkillsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace unexpected Skill path: $resolvedTarget"
    }
    Remove-Item -LiteralPath $Target -Recurse -Force
}
Copy-Item -LiteralPath $Source -Destination $Target -Recurse

$sourceHash = (Get-FileHash -LiteralPath (Join-Path $Source 'SKILL.md') -Algorithm SHA256).Hash
$targetHash = (Get-FileHash -LiteralPath (Join-Path $Target 'SKILL.md') -Algorithm SHA256).Hash
if ($sourceHash -ne $targetHash) { throw 'Installed Skill verification failed.' }
Write-Host "K_desk maintenance Skill installed: $Target"
