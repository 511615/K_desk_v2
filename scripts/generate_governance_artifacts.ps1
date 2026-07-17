$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment is missing.' }

& $Python (Join-Path $Root 'scripts\governance.py') registry
if ($LASTEXITCODE -ne 0) { throw 'Feature registry generation failed.' }
& $Python (Join-Path $Root 'scripts\governance.py') openapi
if ($LASTEXITCODE -ne 0) { throw 'OpenAPI generation failed.' }
