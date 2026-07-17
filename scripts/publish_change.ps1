[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()]
    [string]$Message,
    [switch]$Push
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

& (Join-Path $Root 'scripts\verify_change.ps1') -Mode Full
if ($LASTEXITCODE -ne 0) { throw 'Full verification failed.' }

Push-Location -LiteralPath $Root
try {
    $status = @(& git status --short)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git status.' }
    if ($status.Count -eq 0) { throw 'There are no changes to publish.' }
    & git add --all
    if ($LASTEXITCODE -ne 0) { throw 'git add failed.' }
    & git commit -m $Message
    if ($LASTEXITCODE -ne 0) { throw 'git commit failed.' }
    if ($Push) {
        $remotes = @(& git remote)
        if ($LASTEXITCODE -ne 0 -or $remotes.Count -eq 0) {
            throw 'Push was requested but no Git remote is configured.'
        }
        & git push
        if ($LASTEXITCODE -ne 0) { throw 'git push failed.' }
    }
} finally {
    Pop-Location
}
