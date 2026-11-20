[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Original,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$CecilPath,
    [Parameter(Mandatory)][string]$References
)
$ErrorActionPreference = 'Stop'
$cecil = (Resolve-Path -LiteralPath $CecilPath).Path
[System.Runtime.Loader.AssemblyLoadContext]::Default.LoadFromAssemblyPath($cecil) | Out-Null
$refs = @(Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll' | ForEach-Object FullName) + @($cecil)
Add-Type -Path (Join-Path $PSScriptRoot 'patch_inbox_client.cs') -ReferencedAssemblies $refs
[PatchInboxClient]::Run((Resolve-Path -LiteralPath $Original).Path, [IO.Path]::GetFullPath($Output), (Resolve-Path -LiteralPath $References).Path)
