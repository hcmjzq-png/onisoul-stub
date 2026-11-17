[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InputAssembly,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$ReferenceDirectory,
    [Parameter(Mandatory)][string]$CecilPath
)
$ErrorActionPreference = 'Stop'
[System.Runtime.Loader.AssemblyLoadContext]::Default.LoadFromAssemblyPath((Resolve-Path -LiteralPath $CecilPath).Path) | Out-Null
$compileRefs = @(Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll' | ForEach-Object FullName) + @($CecilPath)
Add-Type -Path (Join-Path $PSScriptRoot 'patch_startup_client.cs') -ReferencedAssemblies $compileRefs
[PatchStartupClient]::Run((Resolve-Path -LiteralPath $InputAssembly).Path, [IO.Path]::GetFullPath($Output), (Resolve-Path -LiteralPath $ReferenceDirectory).Path)
