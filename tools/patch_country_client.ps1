[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Original,
    [Parameter(Mandatory)][string]$Helper,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$CecilPath
)
$ErrorActionPreference = 'Stop'
[System.Runtime.Loader.AssemblyLoadContext]::Default.LoadFromAssemblyPath((Resolve-Path -LiteralPath $CecilPath).Path) | Out-Null
$compileRefs = @(Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll' | ForEach-Object FullName) + @($CecilPath)
Add-Type -Path (Join-Path $PSScriptRoot 'patch_country_client.cs') -ReferencedAssemblies $compileRefs
[PatchCountryClient]::Run((Resolve-Path -LiteralPath $Original).Path, (Resolve-Path -LiteralPath $Helper).Path, [IO.Path]::GetFullPath($Output))
