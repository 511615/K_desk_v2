[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProductionRoot = 'D:\risk\K_desk_v2_main'
$DevelopmentRoot = 'D:\risk\K_desk_v2_dev'

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed in ${Root}: git $($Arguments -join ' ')"
    }
    return $output
}

foreach ($root in @($ProductionRoot, $DevelopmentRoot)) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "Required K_desk worktree is missing: $root"
    }
}

$mainBranch = (Invoke-Git -Root $ProductionRoot -Arguments @('branch', '--show-current'))[0].Trim()
$devBranch = (Invoke-Git -Root $DevelopmentRoot -Arguments @('branch', '--show-current'))[0].Trim()
if ($mainBranch -ne 'main') { throw "Production worktree must be on main, found '$mainBranch'." }
if ($devBranch -ne 'dev') { throw "Development worktree must be on dev, found '$devBranch'." }

$mainStatus = @(Invoke-Git -Root $ProductionRoot -Arguments @('status', '--porcelain'))
$devStatus = @(Invoke-Git -Root $DevelopmentRoot -Arguments @('status', '--porcelain'))
if ($mainStatus.Count -gt 0) { throw 'Production worktree must be clean before promotion.' }
if ($devStatus.Count -gt 0) { throw 'Development worktree must be clean before promotion.' }

$backWorktree = @(Invoke-Git -Root $ProductionRoot -Arguments @('worktree', 'list', '--porcelain')) |
    Where-Object { $_ -eq 'branch refs/heads/back' }
if ($backWorktree.Count -gt 0) { throw 'The back branch must not have a dedicated worktree.' }

& (Join-Path $DevelopmentRoot 'scripts\verify_change.ps1') -Mode Full
if ($LASTEXITCODE -ne 0) { throw 'Development Full verification failed.' }

& git -C $DevelopmentRoot merge-base --is-ancestor main dev
if ($LASTEXITCODE -ne 0) {
    throw 'dev is not based on the current main. Fast-forward dev from main and verify again.'
}

$mainSha = (Invoke-Git -Root $ProductionRoot -Arguments @('rev-parse', 'main'))[0].Trim()
$devSha = (Invoke-Git -Root $DevelopmentRoot -Arguments @('rev-parse', 'dev'))[0].Trim()
if ($mainSha -eq $devSha) {
    Write-Output "No promotion required: main and dev already point to $mainSha."
    exit 0
}

Invoke-Git -Root $ProductionRoot -Arguments @('branch', '-f', 'back', $mainSha) | Out-Null
Invoke-Git -Root $ProductionRoot -Arguments @('merge', '--ff-only', 'dev') | Out-Null
$promotedSha = (Invoke-Git -Root $ProductionRoot -Arguments @('rev-parse', 'main'))[0].Trim()
if ($promotedSha -ne $devSha) { throw 'Promotion completed with an unexpected main revision.' }

Write-Output "Promotion ready: back=$mainSha main=$promotedSha dev=$devSha"
Write-Output 'Run scripts\release_prod.ps1 from the production worktree to deploy main.'
