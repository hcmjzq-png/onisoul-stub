[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Local','Lan','Cloud','CloudRelay')][string]$Mode,
    [string]$ServerAddress,
    [string]$ClientRoot = 'D:\鬼武者魂',
    [string]$BackupRoot,
    [switch]$SkipHosts,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
if (-not $BackupRoot) { $BackupRoot = Join-Path $PSScriptRoot '..\work\client-backups' }
if ($Mode -eq 'Local') {
    if ($ServerAddress -and $ServerAddress -ne '127.0.0.1') { throw 'Local mode requires 127.0.0.1' }
    $ServerAddress = '127.0.0.1'
}
$address = $null
if (-not [Net.IPAddress]::TryParse($ServerAddress, [ref]$address) -or
    $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Supply an IPv4 ServerAddress for Lan or Cloud mode.'
}
$domains = @('passport.86joy.com','game-onisoul.86joy.com','client-onisoul.86joy.com','test12242013.86joy.com')
$targetAddress = if ($Mode -eq 'CloudRelay') { '127.0.0.1' } else { $ServerAddress }
$hostsPath = Join-Path $env:windir 'System32\drivers\etc\hosts'
$encoding = [Text.Encoding]::GetEncoding(28591) # byte-preserving for GBK/UTF-8 INI comments
$changes = @()
foreach ($relative in @('config.ini','Cantainer\config.ini')) {
    $path = Join-Path $ClientRoot $relative
    $bytes = [IO.File]::ReadAllBytes($path)
    $fileEncoding = $encoding
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 255 -and $bytes[1] -eq 254) { $fileEncoding = [Text.Encoding]::Unicode }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 254 -and $bytes[1] -eq 255) { $fileEncoding = [Text.Encoding]::BigEndianUnicode }
    $text = $fileEncoding.GetString($bytes)
    foreach ($key in @('StartUrl','FinalUrl')) {
        if ([regex]::Matches($text, "(?m)^$key=.*$").Count -ne 1) { throw "Expected one $key in $path" }
    }
    $text = [regex]::Replace($text, '(?m)^StartUrl=[^\r\n]*', 'StartUrl=http://passport.86joy.com/index.php/gwz/client/login/')
    $text = [regex]::Replace($text, '(?m)^FinalUrl=[^\r\n]*', 'FinalUrl=http://game-onisoul.86joy.com/client/app.html')
    $changes += @{Path=$path; Text=$text; Encoding=$fileEncoding; Backup=($relative -replace '\\','-')}
}
$lines = [Collections.Generic.List[string]]::new()
foreach ($line in ($encoding.GetString([IO.File]::ReadAllBytes($hostsPath)) -split '\r?\n')) {
    $pieces = $line -split '#',2
    $tokens = @($pieces[0].Trim() -split '\s+' | Where-Object { $_ })
    if ($tokens.Count -lt 2) { $lines.Add($line); continue }
    $remaining = @($tokens[1..($tokens.Count-1)] | Where-Object { $_ -notin $domains })
    if ($remaining.Count -eq $tokens.Count-1) { $lines.Add($line); continue }
    if ($remaining.Count) { $lines.Add($tokens[0] + ' ' + ($remaining -join ' ')) }
    if ($pieces.Count -eq 2) { $lines.Add('#' + $pieces[1]) }
}
if ($SkipHosts) {
    $originalHosts = $encoding.GetString([IO.File]::ReadAllBytes($hostsPath))
    foreach ($domain in $domains) {
        $mapped = @()
        foreach ($line in ($originalHosts -split '\r?\n')) {
            $tokens = @((($line -split '#',2)[0].Trim() -split '\s+') | Where-Object { $_ })
            if ($tokens.Count -ge 2 -and $tokens[1..($tokens.Count-1)] -contains $domain) { $mapped += $tokens[0] }
        }
        if (-not $mapped.Count -or @($mapped | Where-Object { $_ -ne $targetAddress }).Count) {
            throw "Existing hosts mapping for $domain is not $targetAddress; cannot skip hosts."
        }
    }
} else {
    $lines.Add("# OniSoul mode: $Mode")
    foreach ($domain in $domains) { $lines.Add("$targetAddress $domain") }
    $changes += @{Path=$hostsPath; Text=(($lines -join "`r`n") + "`r`n"); Encoding=$encoding; Backup='hosts'}
}
Write-Output "Mode=$Mode Server=$ServerAddress Client=$ClientRoot"
Write-Output 'StartUrl=http://passport.86joy.com/index.php/gwz/client/login/'
Write-Output 'FinalUrl=http://game-onisoul.86joy.com/client/app.html'
if (-not $Apply) { Write-Output 'Preview only. Add -Apply in an administrator PowerShell to write with backups.'; return }
$backup = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($change in $changes) { Copy-Item -LiteralPath $change.Path -Destination (Join-Path $backup $change.Backup) }
# Write hosts first: lack of administrator rights must not leave partially changed INIs.
$ordered = @($changes | Sort-Object { if ($_.Path -eq $hostsPath) { 0 } else { 1 } })
$written = @()
try {
    foreach ($change in $ordered) {
        [IO.File]::WriteAllBytes($change.Path, $change.Encoding.GetBytes($change.Text))
        $written += $change
    }
} catch {
    foreach ($change in $written) {
        try { Copy-Item -LiteralPath (Join-Path $backup $change.Backup) -Destination $change.Path -Force } catch { Write-Warning "Restore from $backup if needed: $($change.Path)" }
    }
    throw
}
if (-not $SkipHosts) { ipconfig /flushdns | Out-Null }
Write-Output "Applied. Backup=$backup"
