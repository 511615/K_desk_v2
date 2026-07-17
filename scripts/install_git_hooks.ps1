$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

Push-Location -LiteralPath $Root
try {
    & git config core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) { throw 'Failed to configure Git hooks.' }
    $configured = (& git config --get core.hooksPath).Trim()
    if ($LASTEXITCODE -ne 0 -or $configured -ne '.githooks') {
        throw "Unexpected Git hooks path: $configured"
    }
} finally {
    Pop-Location
}

Write-Host 'K_desk Git hooks installed.'
