[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '',
    [switch]$SkipGitCleanCheck
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Runtime = Join-Path $Root 'runtime\prod'
$Timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$BackupDir = Join-Path $Runtime "release_backups\$Timestamp"
$VersionFile = (Get-Content -LiteralPath (Join-Path $Root 'VERSION') -Raw).Trim()
$databaseFiles = @('kdesk.sqlite', 'jobs.sqlite', 'account_login_ips.sqlite')
$restored = $false
$deploymentStarted = $false

if (-not $Version) { $Version = $VersionFile }
if ($Version -ne $VersionFile) { throw "Requested version $Version does not match VERSION $VersionFile" }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Production Python environment is missing.' }

Push-Location -LiteralPath $Root
try {
    if (-not $SkipGitCleanCheck) {
        $status = @(& git status --porcelain)
        if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git status.' }
        if ($status.Count -gt 0) { throw 'Production release requires a clean Git worktree.' }
    }
    & (Join-Path $Root 'scripts\verify_change.ps1') -Mode Release
    if ($LASTEXITCODE -ne 0) { throw 'Release verification failed.' }

    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    foreach ($name in $databaseFiles) {
        $source = Join-Path $Runtime $name
        if (Test-Path -LiteralPath $source) {
            & $Python (Join-Path $Root 'scripts\backup_sqlite.py') $source (Join-Path $BackupDir $name)
            if ($LASTEXITCODE -ne 0) { throw "Failed to back up $name" }
        }
    }
    $compatibilityWorkbook = Join-Path $Runtime 'legacy_compat\problematic_accounts.xlsx'
    if (Test-Path -LiteralPath $compatibilityWorkbook) {
        Copy-Item -LiteralPath $compatibilityWorkbook -Destination (Join-Path $BackupDir 'problematic_accounts.xlsx')
    }

    $releaseManifest = [ordered]@{
        Version = $Version
        GitSha = (& git rev-parse HEAD).Trim()
        CreatedAt = (Get-Date).ToString('o')
        BackupDirectory = $BackupDir
    }
    $releaseManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $BackupDir 'release_manifest.json') -Encoding utf8

    $deploymentStarted = $true
    & (Join-Path $Root 'scripts\stop_prod.ps1')
    & $Python -m alembic -c (Join-Path $Root 'alembic.ini') upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed.' }
    & (Join-Path $Root 'scripts\start_prod.ps1')
    $health = @(& (Join-Path $Root 'scripts\health_check_prod.ps1'))
    if (@($health | Where-Object { -not $_.Ready }).Count -gt 0) { throw 'Production health acceptance failed.' }

    Write-Host "K_desk $Version released. Backup: $BackupDir"
} catch {
    $failure = $_
    if ($deploymentStarted) {
        try {
            & (Join-Path $Root 'scripts\stop_prod.ps1')
            foreach ($name in $databaseFiles) {
                $backup = Join-Path $BackupDir $name
                if (Test-Path -LiteralPath $backup) {
                    Copy-Item -LiteralPath $backup -Destination (Join-Path $Runtime $name) -Force
                    $restored = $true
                }
            }
            $workbookBackup = Join-Path $BackupDir 'problematic_accounts.xlsx'
            if (Test-Path -LiteralPath $workbookBackup) {
                Copy-Item -LiteralPath $workbookBackup -Destination (Join-Path $Runtime 'legacy_compat\problematic_accounts.xlsx') -Force
                $restored = $true
            }
            & (Join-Path $Root 'scripts\start_prod.ps1')
        } catch {
            Write-Error "Automatic rollback also failed: $($_.Exception.Message)"
        }
    }
    throw "Release failed: $($failure.Exception.Message). Snapshot restored: $restored"
} finally {
    Pop-Location
}
