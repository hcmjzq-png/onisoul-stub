[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'OniSoul\development.local.json'),
    [string]$Output
)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
foreach ($path in @($settings.PythonPath, $settings.MySQLPath)) {
    if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Fill PythonPath and MySQLPath in the private development configuration.' }
}
$repo = Split-Path $PSScriptRoot -Parent
if (-not $Output) { $Output = Join-Path $repo ('work\local-sql-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')) }
& $settings.PythonPath (Join-Path $PSScriptRoot 'run_isolated_mysql_tests.py') --mysqld $settings.MySQLPath --output $Output
if ($LASTEXITCODE -ne 0) { throw "Local regression failed; see $Output" }
Write-Output "Local regression passed. Evidence=$Output"
