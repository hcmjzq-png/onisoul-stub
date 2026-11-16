[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ClientRoot,
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'OniSoul\connection.local.json')
)
$ErrorActionPreference = 'Stop'
$ClientRoot = (Resolve-Path -LiteralPath $ClientRoot).Path
$exe = Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Client executable is missing.' }
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'Create the private connection.local.json before installation.' }
$settings = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$address = $null
if (-not [Net.IPAddress]::TryParse($settings.ServerAddress,[ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'Fill ServerAddress in the private connection configuration.' }
if ((Resolve-Path -LiteralPath $settings.ClientRoot).Path -ne $ClientRoot) { throw 'ClientRoot differs from the private connection configuration.' }
if (-not (Test-Path -LiteralPath $settings.PythonPath -PathType Leaf)) { throw 'Fill PythonPath in the private connection configuration.' }
$repo = Split-Path $PSScriptRoot -Parent
$destination = Join-Path $ClientRoot 'OniSoul-CloudClient'
$launcherPath = Join-Path $ClientRoot 'Start-OniSoul.cmd'
$backupRoot = Join-Path $env:LOCALAPPDATA 'OniSoul\client-backups'
$backup = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
New-Item -ItemType Directory -Path $backup -Force | Out-Null
if (Test-Path -LiteralPath $launcherPath) { Copy-Item -LiteralPath $launcherPath -Destination $backup }
if (Test-Path -LiteralPath $destination) { Copy-Item -LiteralPath $destination -Destination $backup -Recurse }
New-Item -ItemType Directory -Path (Join-Path $destination 'tools'),(Join-Path $destination 'app\protocol') -Force | Out-Null
foreach ($name in @('start_cloud_client.ps1','configure_client.ps1','proxy80.py','start_login_memory.ps1','login_memory.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $destination 'tools') -Force
}
foreach ($name in @('app\__init__.py','app\protocol\__init__.py','app\protocol\envelope.py')) {
    Copy-Item -LiteralPath (Join-Path $repo $name) -Destination (Join-Path $destination $name) -Force
}
# The launcher stores only the local configuration path, never the actual server or credentials.
$lines = @('@echo off',('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0OniSoul-CloudClient\tools\start_cloud_client.ps1" -ConfigPath "'+$ConfigPath+'"'),'if errorlevel 1 pause')
[IO.File]::WriteAllLines($launcherPath, $lines, [Text.Encoding]::ASCII)
Write-Output "Installed cloud launcher. Backup=$backup"
