<#
.SYNOPSIS
Read-only verification of data.bin from OniSoul_Setup_20140712.exe.
.DESCRIPTION
Replays the seeded .NET Random stream and compares every byte. Prints JSON.
Exit 0 means the entire known file matches; exit 1 means size/content mismatch.
No client binaries are executed and no game files are written.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
if (-not ('OniSoulDataBinVerifier' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Security.Cryptography;

public sealed class OniSoulDataBinResult
{
    public int Seed = 19142570;
    public long ExpectedLength = 528374000;
    public long BytesChecked;
    public long MismatchingBytes;
    public long FirstMismatchOffset = -1;
    public string SourceSHA256;
    public string RegeneratedSHA256;
    public bool Verified;
}

public static class OniSoulDataBinVerifier
{
    public static OniSoulDataBinResult Verify(string path)
    {
        var result = new OniSoulDataBinResult();
        var random = new Random(result.Seed);
        var actual = new byte[1024 * 1024];
        var expected = new byte[actual.Length];
        using (var source = File.OpenRead(path))
        using (var actualHash = SHA256.Create())
        using (var expectedHash = SHA256.Create())
        {
            int count;
            while ((count = source.Read(actual, 0, actual.Length)) > 0)
            {
                for (int i = 0; i < count; i++)
                {
                    expected[i] = (byte)random.Next(0, 254);
                    if (actual[i] != expected[i])
                    {
                        if (result.FirstMismatchOffset < 0)
                            result.FirstMismatchOffset = result.BytesChecked + i;
                        result.MismatchingBytes++;
                    }
                }
                actualHash.TransformBlock(actual, 0, count, actual, 0);
                expectedHash.TransformBlock(expected, 0, count, expected, 0);
                result.BytesChecked += count;
            }
            actualHash.TransformFinalBlock(new byte[0], 0, 0);
            expectedHash.TransformFinalBlock(new byte[0], 0, 0);
            result.SourceSHA256 = BitConverter.ToString(actualHash.Hash).Replace("-", "").ToLowerInvariant();
            result.RegeneratedSHA256 = BitConverter.ToString(expectedHash.Hash).Replace("-", "").ToLowerInvariant();
        }
        result.Verified = result.BytesChecked == result.ExpectedLength
            && result.MismatchingBytes == 0
            && result.SourceSHA256 == "c017a1eb4a01c826b8761faa0c48494ece0c64684399d51b69fc3d7893e639c6"
            && result.SourceSHA256 == result.RegeneratedSHA256;
        return result;
    }
}
'@
}

$resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
$result = [OniSoulDataBinVerifier]::Verify($resolved)
$result | ConvertTo-Json
if (-not $result.Verified) {
    exit 1
}
exit 0
