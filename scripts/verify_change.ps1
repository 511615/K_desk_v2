[CmdletBinding()]
param(
    [ValidateSet('Fast', 'Full', 'Release')]
    [string]$Mode = 'Fast',
    [string]$Base = ''
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$CopyPoolRuntime = Join-Path $Root 'services\copy_pool_runtime'
$CopyPoolExternalDeps = 'D:\risk\pydeps'
$Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
$BundledNode = 'C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'

if (-not (Get-Command node -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath (Join-Path $BundledNode 'node.exe'))) {
    $env:PATH = "$BundledNode;$env:PATH"
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python environment is missing. Run scripts\bootstrap_dev.ps1 first.'
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$WorkingDirectory = $Root,
        [hashtable]$Environment = @{}
    )
    Write-Host "==> $Label"
    $savedEnvironment = @{}
    foreach ($key in $Environment.Keys) {
        $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], 'Process')
    }
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
        }
    }
}

$governanceArguments = @('scripts\governance.py', 'validate')
if ($Base) { $governanceArguments += @('--base', $Base) }
Invoke-NativeChecked -FilePath $Python -Arguments $governanceArguments -Label 'Governance and generated contracts'
Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'compileall', '-q', 'src', 'tests', 'scripts\governance.py') -Label 'Python compile'
Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'ruff', 'check', 'src', 'tests', 'scripts\governance.py') -Label 'Ruff'
if (Test-Path -LiteralPath $CopyPoolRuntime) {
    Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'compileall', '-q', '.') -Label 'Copy-pool Producer compile' -WorkingDirectory $CopyPoolRuntime
    Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'ruff', 'check', '--select', 'E9,F63,F7,F82', '.') -Label 'Copy-pool Producer safety lint' -WorkingDirectory $CopyPoolRuntime
}

if ($Mode -in @('Full', 'Release')) {
    $rootPythonPath = Join-Path $Root 'src'
    if ($env:PYTHONPATH) {
        $rootPythonPath = "$rootPythonPath;$env:PYTHONPATH"
    }
    Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'pytest') -Label 'Python and legacy tests' -Environment @{ PYTHONPATH = $rootPythonPath }
    if (Test-Path -LiteralPath $CopyPoolRuntime) {
        $runtimePythonPath = "$CopyPoolRuntime;$CopyPoolExternalDeps"
        if ($env:PYTHONPATH) {
            $runtimePythonPath = "$runtimePythonPath;$env:PYTHONPATH"
        }
        Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'pytest', '-q', 'tests') -Label 'Copy-pool Producer tests' -WorkingDirectory $CopyPoolRuntime -Environment @{ PYTHONPATH = $runtimePythonPath }
    }
    if (-not $Pnpm) { throw 'pnpm is required for Full and Release verification.' }
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('install', '--frozen-lockfile') -Label 'Frontend locked install' -WorkingDirectory (Join-Path $Root 'frontend')
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('test') -Label 'Frontend tests' -WorkingDirectory (Join-Path $Root 'frontend')
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('build') -Label 'Frontend production build' -WorkingDirectory (Join-Path $Root 'frontend')
}

if ($Mode -eq 'Release') {
    if ($env:KDESK_ENABLE_LIVE_CONTRACTS -ne '1') {
        throw 'Release verification requires KDESK_ENABLE_LIVE_CONTRACTS=1 and the read-only local contract fixture.'
    }
    $fixture = Join-Path $Root 'runtime\prod\contracts\server-matrix.json'
    if (-not (Test-Path -LiteralPath $fixture)) {
        throw "Read-only release contract fixture is missing: $fixture"
    }
    Invoke-NativeChecked -FilePath $Python -Arguments @('scripts\verify_live_matrix.py', '--fixture', $fixture) -Label 'Read-only ten-server contract matrix'
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('exec', 'playwright', 'install', 'chromium') -Label 'Playwright Chromium install' -WorkingDirectory (Join-Path $Root 'frontend')
    # Release preflight runs before the service is restarted, so it can only
    # assert the legacy page against the currently deployed process. New
    # runtime behaviour belongs in verify_deployed_release after the candidate
    # process has started.
    Invoke-NativeChecked -FilePath $Pnpm.Source -Arguments @('exec', 'playwright', 'test', 'e2e/legacy-account.spec.ts') -Label 'Production legacy-page E2E' -WorkingDirectory (Join-Path $Root 'frontend')
    & (Join-Path $Root 'scripts\health_check_prod.ps1') | ForEach-Object {
        if (-not $_.Ready) { throw "Production health check failed: $($_.Name) $($_.Status)" }
    }
}

Write-Host "K_desk $Mode verification passed."
