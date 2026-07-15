$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BasePython = $env:KDESK_BASE_PYTHON
if (-not $BasePython) {
    $BasePython = "C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
}
$NodeBin = "C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$Pnpm = "C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BasePython)) {
    throw "Base Python not found: $BasePython"
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $BasePython -m venv --system-site-packages (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip" }
& $VenvPython -m pip install -r (Join-Path $Root "requirements.lock")
if ($LASTEXITCODE -ne 0) { throw "Failed to install locked Python dependencies" }
& $VenvPython -m pip install -e $Root --no-deps
if ($LASTEXITCODE -ne 0) { throw "Failed to install K_desk v2 package" }

if (-not (Test-Path -LiteralPath $Pnpm)) {
    throw "Bundled pnpm not found: $Pnpm"
}
$env:PATH = "$NodeBin;$env:PATH"
Push-Location (Join-Path $Root "frontend")
try {
    & $Pnpm install
    if ($LASTEXITCODE -ne 0) { throw "Failed to install frontend dependencies" }
    & $Pnpm run build
    if ($LASTEXITCODE -ne 0) { throw "Failed to build frontend" }
} finally {
    Pop-Location
}

Write-Host "K_desk v2 development dependencies are ready."
