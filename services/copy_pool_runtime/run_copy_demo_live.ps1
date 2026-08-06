#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Shadow', 'StagedLive', 'Live')]
    [string] $Mode = 'StagedLive',

    [ValidateSet('Micro', 'Capital10k')]
    [string] $RiskProfile = 'Capital10k',

    [ValidateRange(0, 1440)]
    [double] $ShadowMinutes = 30,

    [ValidateRange(250, 10000)]
    [int] $PollMs = 500,

    [ValidateRange(0, 31536000)]
    [double] $RunSeconds = 0,

    [switch] $EnableLiveTrading,

    [switch] $AllowDemoMinLotOverride,

    [switch] $DemoFastActivation,

    [switch] $PreflightOnly,

    [switch] $ForceRebuild,

    [string] $InputDir = 'D:\risk\_tmp_copy_demo_20260727',

    [string] $OutputDir = 'D:\risk\output_data\copy_live_demo_capital10k',

    [string] $TerminalPath = 'D:\risk\mt5_backtest_terminal\terminal64.exe',

    [ValidateRange(1, [long]::MaxValue)]
    [long] $DemoLogin = 33304642,

    [string] $PythonPath = 'C:\Users\amber\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runtimeRoot = $PSScriptRoot
$producerPath = Join-Path $runtimeRoot 'copy_trading_multi_demo.py'

function Get-WorkbenchConnection {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $ConnectionsPath
    )

    [xml] $document = Get-Content -LiteralPath $ConnectionsPath -Raw -Encoding UTF8
    $nodes = @($document.SelectNodes("//value[@type='object' and @struct-name='db.mgmt.Connection']"))
    $match = $nodes | Where-Object {
        $_.SelectSingleNode("value[@key='name']").InnerText -eq $Name
    } | Select-Object -First 1
    if ($null -eq $match) {
        throw "Workbench connection '$Name' was not found."
    }
    $parameters = $match.SelectSingleNode("value[@key='parameterValues']")
    [pscustomobject]@{
        HostName = $parameters.SelectSingleNode("value[@key='hostName']").InnerText
        Port = [int] $parameters.SelectSingleNode("value[@key='port']").InnerText
        UserName = $parameters.SelectSingleNode("value[@key='userName']").InnerText
    }
}

function Get-WorkbenchCredential {
    param(
        [Parameter(Mandatory)] [string] $CredentialPath,
        [Parameter(Mandatory)] [string] $HostName,
        [Parameter(Mandatory)] [int] $Port,
        [Parameter(Mandatory)] [string] $UserName
    )

    $encrypted = [System.IO.File]::ReadAllBytes($CredentialPath)
    $decrypted = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $encrypted,
        $null,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    try {
        $text = [System.Text.Encoding]::UTF8.GetString($decrypted).TrimEnd([char] 0, [char] 10, [char] 13)
        $records = @(
            foreach ($line in ($text -split "`r?`n")) {
                $match = [regex]::Match($line, '^(?<key>.+)\x02(?<user>.+)\x03(?<password>.*)$')
                if ($match.Success) {
                    [pscustomobject]@{
                        Key = $match.Groups['key'].Value
                        UserName = $match.Groups['user'].Value
                        Password = $match.Groups['password'].Value
                    }
                }
            }
        )
        $key = "Mysql@${HostName}:$Port"
        $credential = $records | Where-Object {
            $_.Key -eq $key -and $_.UserName -eq $UserName
        } | Select-Object -First 1
        if ($null -eq $credential) {
            $credential = $records | Where-Object {
                $_.UserName -eq $UserName
            } | Select-Object -First 1
        }
        if ($null -eq $credential) {
            throw "No saved Workbench credential is available for the requested read-only user."
        }
        return $credential
    }
    finally {
        [Array]::Clear($decrypted, 0, $decrypted.Length)
    }
}

$requiredFiles = @(
    $TerminalPath,
    $PythonPath,
    (Join-Path $runtimeRoot 'copy_pool_multisource.py'),
    $producerPath
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path was not found: $path"
    }
}

$workbenchRoot = Join-Path $env:APPDATA 'MySQL\Workbench'
$connectionsPath = Join-Path $workbenchRoot 'connections.xml'
$credentialPath = Join-Path $workbenchRoot 'workbench_user_data.dat'
$connections = @{
    AC = Get-WorkbenchConnection -Name 'AC Intern' -ConnectionsPath $connectionsPath
    DBG = Get-WorkbenchConnection -Name 'DBG Intern' -ConnectionsPath $connectionsPath
}
$credentials = @{}
foreach ($key in $connections.Keys) {
    $connection = $connections[$key]
    $credentials[$key] = Get-WorkbenchCredential `
        -CredentialPath $credentialPath `
        -HostName $connection.HostName `
        -Port $connection.Port `
        -UserName $connection.UserName
}

$savedEnvironment = @{}
$environmentNames = @(
    'COPY_AC_DB_HOST',
    'COPY_AC_DB_PORT',
    'COPY_AC_DB_USER',
    'COPY_AC_DB_PASSWORD',
    'COPY_DBG_DB_HOST',
    'COPY_DBG_DB_PORT',
    'COPY_DBG_DB_USER',
    'COPY_DBG_DB_PASSWORD',
    'PYTHONPATH'
)
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    foreach ($key in $connections.Keys) {
        $connection = $connections[$key]
        $credential = $credentials[$key]
        [Environment]::SetEnvironmentVariable("COPY_${key}_DB_HOST", $connection.HostName, 'Process')
        [Environment]::SetEnvironmentVariable("COPY_${key}_DB_PORT", [string] $connection.Port, 'Process')
        [Environment]::SetEnvironmentVariable("COPY_${key}_DB_USER", $connection.UserName, 'Process')
        [Environment]::SetEnvironmentVariable("COPY_${key}_DB_PASSWORD", $credential.Password, 'Process')
    }
    $existingPythonPath = $savedEnvironment['PYTHONPATH']
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
        "$runtimeRoot;D:\risk\pydeps"
    }
    else {
        "$runtimeRoot;D:\risk\pydeps;$existingPythonPath"
    }

    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $arguments = @(
        $producerPath,
        '--input-dir', $InputDir,
        '--output-dir', $OutputDir,
        '--terminal', $TerminalPath,
        '--demo-login', [string] $DemoLogin,
        '--risk-profile', $RiskProfile,
        '--mode', $Mode,
        '--shadow-minutes', $ShadowMinutes.ToString([System.Globalization.CultureInfo]::InvariantCulture),
        '--poll-ms', [string] $PollMs,
        '--run-seconds', $RunSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    )
    if ($EnableLiveTrading) {
        $arguments += '--enable-live-trading'
    }
    if ($AllowDemoMinLotOverride) {
        $arguments += '--allow-demo-min-lot-override'
    }
    if ($DemoFastActivation) {
        $arguments += '--demo-fast-activation'
    }
    if ($PreflightOnly) {
        $arguments += '--preflight-only'
    }
    if ($ForceRebuild) {
        $arguments += '--force-rebuild'
    }
    & $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "The live copy service exited with code $LASTEXITCODE."
    }
}
finally {
    foreach ($name in $environmentNames) {
        $previous = $savedEnvironment[$name]
        if ($null -eq $previous) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $previous, 'Process')
        }
    }
    $credentials = $null
    $connections = $null
    $credential = $null
    $connection = $null
}
