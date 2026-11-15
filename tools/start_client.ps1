[CmdletBinding()]
param([Parameter(Mandatory)][string]$ClientRoot, [string]$PythonPath)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $ClientRoot ([string][char]0x9b3c+[char]0x6b66+[char]0x8005+[char]0x9b42+'.exe')
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Client executable is missing.' }
& (Join-Path $PSScriptRoot 'start_login_memory.ps1') -PythonPath $PythonPath
Start-Process -FilePath $exe -WorkingDirectory $ClientRoot
