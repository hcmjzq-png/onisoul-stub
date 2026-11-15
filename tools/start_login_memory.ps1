[CmdletBinding()]
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
$uri = 'http://127.0.0.1:19765/health'
function Test-LoginMemory {
    try {
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Proxy = $null
        $request.Timeout = 1500
        $response = $request.GetResponse()
        try {
            $reader = [IO.StreamReader]::new($response.GetResponseStream())
            try { $result = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
            return $result.service -eq 'onisoul-login-memory' -and $result.version -eq 1
        } finally { $response.Dispose() }
    } catch { return $false }
}
if (Test-LoginMemory) { Write-Output 'Login memory is ready'; return }
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 19765 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw 'Port 19765 belongs to another service; it was not stopped.' }
$script = Join-Path $PSScriptRoot 'login_memory.py'
Start-Process -FilePath $PythonPath -ArgumentList @(('"'+$script+'"')) -WindowStyle Hidden | Out-Null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if (Test-LoginMemory) { Write-Output 'Login memory is ready'; return }
    Start-Sleep -Milliseconds 150
}
throw 'Login memory did not start'
