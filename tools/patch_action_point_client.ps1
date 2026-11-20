[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InputAssembly,
    [Parameter(Mandatory)][string]$OutputAssembly,
    [Parameter(Mandatory)][string]$ReferenceDirectory,
    [Parameter(Mandatory)][string]$CecilPath
)
$ErrorActionPreference = 'Stop'
$cecil = (Resolve-Path -LiteralPath $CecilPath).Path
[System.Runtime.Loader.AssemblyLoadContext]::Default.LoadFromAssemblyPath($cecil) | Out-Null
$references = @(Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll' | ForEach-Object FullName) + @($cecil)
Add-Type -Path (Join-Path $PSScriptRoot 'patch_action_point_client.cs') -ReferencedAssemblies $references
[PatchActionPointClient]::Run((Resolve-Path -LiteralPath $InputAssembly).Path, [IO.Path]::GetFullPath($OutputAssembly),
    (Resolve-Path -LiteralPath $ReferenceDirectory).Path)
