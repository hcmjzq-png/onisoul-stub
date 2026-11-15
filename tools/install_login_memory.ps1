[CmdletBinding()]
param([Parameter(Mandatory)][string]$ClientRoot)
$ErrorActionPreference = 'Stop'
$ClientRoot = (Resolve-Path -LiteralPath $ClientRoot).Path
$exe = Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Client executable is missing.' }
$destination = Join-Path $ClientRoot 'OniSoul-LoginMemory'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('login_memory.py','start_login_memory.ps1','start_client.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $destination $name) -Force
}
$launcher = '@echo off' + "`r`n" + 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0OniSoul-LoginMemory\start_client.ps1" -ClientRoot "%~dp0."' + "`r`n" + 'if errorlevel 1 pause' + "`r`n"
[IO.File]::WriteAllText((Join-Path $ClientRoot 'Start-OniSoul.cmd'), $launcher, [Text.Encoding]::ASCII)
Write-Output (Join-Path $ClientRoot 'Start-OniSoul.cmd')
