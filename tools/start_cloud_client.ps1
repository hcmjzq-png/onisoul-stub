[CmdletBinding()]
param(
    [string]$ServerAddress,
    [string]$ClientRoot,
    [string]$PythonPath,
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'OniSoul\connection.local.json'),
    [switch]$RestartRelay,
    [switch]$RelayOnly
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $ConfigPath) {
    $settings = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    if (-not $ServerAddress) { $ServerAddress = $settings.ServerAddress }
    if (-not $ClientRoot) { $ClientRoot = $settings.ClientRoot }
    if (-not $PythonPath) { $PythonPath = $settings.PythonPath }
}
if (-not $ServerAddress -or -not $ClientRoot) { throw 'Supply ServerAddress and ClientRoot, or fill the private connection.local.json.' }
$address = $null
if (-not [Net.IPAddress]::TryParse($ServerAddress,[ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'ServerAddress must be IPv4' }
$repo = Split-Path $PSScriptRoot -Parent
$privateRoot = Join-Path $env:LOCALAPPDATA 'OniSoul'
$statePath = Join-Path $privateRoot 'cloud-relay.local.json'
$logDir = Join-Path $privateRoot 'logs'
$proxyScript = Join-Path $PSScriptRoot 'proxy80.py'
if (-not $PythonPath) {
    $installed = @(Get-ChildItem -Path "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
    if ($installed.Count) { $PythonPath = $installed[0].FullName }
    else { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
}
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Supply the real Python 3.12+ executable via -PythonPath' }
$exe = Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')
if (-not (Test-Path -LiteralPath $exe)) { throw 'Game executable is missing under ClientRoot' }
& (Join-Path $PSScriptRoot 'configure_client.ps1') -Mode CloudRelay -ServerAddress $ServerAddress -ClientRoot $ClientRoot -SkipHosts

function Assert-CloudHealth([string]$BaseUrl) {
    $request = [Net.HttpWebRequest]::Create($BaseUrl + '/client/status')
    $request.Proxy = $null
    $request.Timeout = 10000
    $response = $request.GetResponse()
    try {
        $reader = [IO.StreamReader]::new($response.GetResponseStream())
        try { $status = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($status.service -ne 'onisoul-stub' -or $status.status -ne 'up') { throw 'Cloud health check failed' }
    } finally { $response.Dispose() }
}

$sock = [Net.Sockets.TcpClient]::new()
$occupied = $false
try { $sock.Connect('127.0.0.1',80); $occupied=$true } catch {} finally { $sock.Dispose() }
if ($occupied) {
    if (-not (Test-Path -LiteralPath $statePath)) { throw 'Port 80 is already in use by an untracked process; verify it before proceeding.' }
    $record = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    $listener = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 80 -State Listen -ErrorAction SilentlyContinue)
    $details = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"
    $recordedScript = if ($record.script) { $record.script } else { $proxyScript }
    $commandMatches = $details.CommandLine -and $details.CommandLine.Contains($recordedScript)
    if (-not $process -or $process.ProcessName -notmatch '^python(w)?$' -or -not $commandMatches -or
        $listener.Count -ne 1 -or $listener[0].OwningProcess -ne $record.pid -or
        $process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$record.started).ToUniversalTime().Ticks) { throw 'Port 80 does not match the recorded cloud relay.' }
    if ($record.server -ne $ServerAddress -and -not $RestartRelay) { throw 'The recorded relay points to a different server. Use -RestartRelay after verifying the destination.' }
    if ($RestartRelay) {
        Assert-CloudHealth "http://$ServerAddress"
        Stop-Process -Id $process.Id -ErrorAction Stop
        $process.WaitForExit(5000) | Out-Null
        if (-not $process.HasExited) { throw 'Tracked relay did not stop.' }
        $occupied = $false
    }
}
if (-not $occupied) {
    Assert-CloudHealth "http://$ServerAddress"
    New-Item -ItemType Directory -Force $privateRoot,$logDir | Out-Null
    $previousLogDir = $env:ONI_LOG_DIR
    try {
        $env:ONI_LOG_DIR = $logDir
        $process = Start-Process -FilePath $PythonPath -ArgumentList @('-u',('"'+$proxyScript+'"'),'--host','127.0.0.1','--listen','80','--upstream-host',$ServerAddress,'--upstream','80') -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'relay.stdout.log') -RedirectStandardError (Join-Path $logDir 'relay.stderr.log') -PassThru
    } finally { $env:ONI_LOG_DIR = $previousLogDir }
    Start-Sleep -Milliseconds 700
    $process.Refresh()
    if ($process.HasExited) { throw 'Relay exited; see the private relay.stderr.log.' }
    @{pid=$process.Id;server=$ServerAddress;script=$proxyScript;started=$process.StartTime.ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}
Assert-CloudHealth 'http://127.0.0.1'
Write-Output "Cloud relay ready. PID=$($process.Id)"
& (Join-Path $PSScriptRoot 'start_login_memory.ps1') -PythonPath $PythonPath
if (-not $RelayOnly) { Start-Process -FilePath $exe -WorkingDirectory $ClientRoot }
