param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$pythonw = Join-Path (Split-Path $settings.python) 'pythonw.exe'
$manager = Join-Path $settings.repo 'tools\game_environments.py'
if (!(Test-Path -LiteralPath $pythonw) -or !(Test-Path -LiteralPath $manager)) { throw '环境启动程序不完整' }
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$backup = Join-Path (Split-Path $Config) ('desktop-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($profile in @('local-test','cloud')) {
    $label = if ($profile -eq 'local-test') {'本地测试'} else {'云端正式'}
    $client = if ($profile -eq 'local-test') {$settings.local_client} else {$settings.cloud_client}
    $path = Join-Path $desktop ('鬼武者魂－' + $label + '.lnk')
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $backup }
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = '"' + $manager + '" --config "' + $Config + '" --action select --profile ' + $profile + ' --launch'
    $link.WorkingDirectory = $settings.repo
    $link.IconLocation = (Join-Path $client '鬼武者魂.exe') + ',0'
    $link.Description = '校验目标为' + $label + '后启动；请先关闭游戏再切服'
    $link.Save()
}
$oldLink = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) '鬼武者魂.lnk'
if (Test-Path -LiteralPath $oldLink) { Move-Item -LiteralPath $oldLink -Destination (Join-Path $backup '鬼武者魂.lnk') }
foreach ($profile in @('local-test','cloud')) {
    $client = if ($profile -eq 'local-test') {$settings.local_client} else {$settings.cloud_client}
    $entry = Join-Path $client 'Start-OniSoul.cmd'
    if (Test-Path -LiteralPath $entry) { Copy-Item -LiteralPath $entry -Destination (Join-Path $backup ($profile + '-Start-OniSoul.cmd')) }
    $body = '@echo off' + "`r`n" + 'start "" "' + $pythonw + '" "' + $manager + '" --config "' + $Config + '" --action select --profile ' + $profile + ' --launch' + "`r`n"
    [IO.File]::WriteAllText($entry, $body, [Text.Encoding]::GetEncoding(936))
}
Write-Host '已安装本地测试 / 云端正式两个桌面入口；原入口已备份。'
