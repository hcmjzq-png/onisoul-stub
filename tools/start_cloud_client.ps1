[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ServerAddress,
    [Parameter(Mandatory)][string]$ClientRoot,
    [string]$PythonPath,
    [switch]$RelayOnly
)
$ErrorActionPreference = 'Stop'
$address = $null
if (-not [Net.IPAddress]::TryParse($ServerAddress,[ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'ServerAddress must be IPv4' }
$repo = Split-Path $PSScriptRoot -Parent
$statePath = Join-Path $repo 'work\cloud-relay.json'
$proxyScript = Join-Path $PSScriptRoot 'proxy80.py'
if (-not $PythonPath) {
    $installed = @(Get-ChildItem -Path "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
    if ($installed.Count) { $PythonPath = $installed[0].FullName }
    else { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
}
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Supply the real Python 3.12+ executable via -PythonPath' }
if (-not (Test-Path -LiteralPath (Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')))) { throw 'Game executable is missing under ClientRoot' }
# Configuration preview also verifies all four existing loopback mappings.
& (Join-Path $PSScriptRoot 'configure_client.ps1') -Mode CloudRelay -ServerAddress $ServerAddress -ClientRoot $ClientRoot -SkipHosts
$sock = [Net.Sockets.TcpClient]::new()
$occupied = $false
try { $sock.Connect('127.0.0.1',80); $occupied=$true } catch {} finally { $sock.Dispose() }
if ($occupied) {
    if (-not (Test-Path -LiteralPath $statePath)) { throw 'Port 80 is already in use by an untracked process; stop it manually or use Cloud direct mode.' }
    $record = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if (-not $process -or $record.server -ne $ServerAddress -or $process.StartTime.ToUniversalTime().ToString('o') -ne $record.started) { throw 'Port 80 does not match the recorded cloud relay.' }
} else {
    New-Item -ItemType Directory -Force (Join-Path $repo 'work'),(Join-Path $repo 'logs') | Out-Null
    $process = Start-Process -FilePath $PythonPath -ArgumentList @('-u',('"'+$proxyScript+'"'),'--host','127.0.0.1','--listen','80','--upstream-host',$ServerAddress,'--upstream','80') -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $repo 'logs\relay.stdout.log') -RedirectStandardError (Join-Path $repo 'logs\relay.stderr.log') -PassThru
    Start-Sleep -Milliseconds 700
    $process.Refresh()
    if ($process.HasExited) { throw 'Relay exited; see logs/relay.stderr.log.' }
    @{pid=$process.Id;server=$ServerAddress;started=$process.StartTime.ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}
$request = [Net.HttpWebRequest]::Create('http://127.0.0.1/client/status')
$request.Proxy = $null
$request.Timeout = 10000
$response = $request.GetResponse()
try {
    $reader = [IO.StreamReader]::new($response.GetResponseStream())
    try { $status = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    if ($status.service -ne 'onisoul-stub' -or $status.status -ne 'up') { throw 'Cloud health check failed' }
} finally { $response.Dispose() }
Write-Output "Cloud relay ready. PID=$($process.Id) Server=$ServerAddress"
& (Join-Path $PSScriptRoot 'start_login_memory.ps1') -PythonPath $PythonPath
if (-not $RelayOnly) {
    $exe = Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')
    Start-Process -FilePath $exe -WorkingDirectory $ClientRoot
}
