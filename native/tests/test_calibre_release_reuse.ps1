$ErrorActionPreference = "Stop"

$nativeRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $nativeRoot "build"
$scriptPath = Join-Path $nativeRoot "scripts\prepare-additional-converter-engines.ps1"
$tokens = $null
$parseErrors = $null
$scriptAst = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }

function Invoke-WebRequest {
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing, [int]$TimeoutSec)
    if (-not $OutFile.EndsWith(".partial", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Synthetic download was not directed to a partial file."
    }
    [IO.File]::WriteAllText($OutFile, $script:syntheticDownloadText, [Text.Encoding]::ASCII)
}

$functionNames = @("Get-VerifiedAsset", "Test-CalibrePackageChecksums", "Test-CalibrePackagePayload", "Copy-VerifiedCalibreReleasePackage")
$functionAsts = $scriptAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $functionNames
}, $true)
foreach ($functionName in $functionNames) {
    $functionAst = $functionAsts | Where-Object Name -EQ $functionName | Select-Object -First 1
    if (-not $functionAst) { throw "Missing production function $functionName." }
    Invoke-Expression $functionAst.Extent.Text
}

function New-SyntheticCalibreRelease {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$CorruptFileAfterChecksums
    )

    $releaseRoot = Join-Path $Root "release"
    $payloadRoot = Join-Path $Root "payload"
    $downloadRoot = Join-Path $Root "download"
    New-Item -ItemType Directory -Force -Path (Join-Path $payloadRoot "Calibre"), (Join-Path $payloadRoot "source"), $releaseRoot, $downloadRoot | Out-Null
    Set-Content -LiteralPath (Join-Path $payloadRoot "Calibre\ebook-convert.exe") -Value "synthetic executable" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $payloadRoot "source\calibre-9.15.0.tar.xz") -Value "synthetic source archive" -Encoding ascii
    Set-Content -LiteralPath (Join-Path $payloadRoot "THIRD-PARTY-NOTICES.md") -Value "synthetic notices" -Encoding utf8
    $sourceHash = (Get-FileHash -LiteralPath (Join-Path $payloadRoot "source\calibre-9.15.0.tar.xz") -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
        id = "calibre"
        version = "9.15.0"
        executable = "Calibre/ebook-convert.exe"
        probeArgument = "--version"
        sourceArchive = "source/calibre-9.15.0.tar.xz"
        sourceSha256 = $sourceHash
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $payloadRoot "engine.json") -Encoding utf8

    $sumsPath = Join-Path $payloadRoot "FILE-SHA256SUMS.txt"
    $sumLines = Get-ChildItem -LiteralPath $payloadRoot -Recurse -File |
        Where-Object { $_.FullName -ne $sumsPath } |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($payloadRoot.Length + 1).Replace("\", "/")
            "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $relativePath
        }
    Set-Content -LiteralPath $sumsPath -Value $sumLines -Encoding utf8
    if ($CorruptFileAfterChecksums) {
        Add-Content -LiteralPath (Join-Path $payloadRoot "Calibre\ebook-convert.exe") -Value "tampered"
    }

    $assetName = "fluke-engine-calibre-win-x64-9.15.0.zip"
    $assetPath = Join-Path $releaseRoot $assetName
    Compress-Archive -Path (Join-Path $payloadRoot "*") -DestinationPath $assetPath -CompressionLevel NoCompression
    $assetHash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $assetSize = (Get-Item -LiteralPath $assetPath).Length
    $manifest = [ordered]@{
        schemaVersion = 1
        releaseTag = "native-v0.1.1-preview.1"
        components = @([ordered]@{
            id = "calibre"
            version = "9.15.0"
            asset = $assetName
            sha256 = $assetHash
            sizeBytes = $assetSize
        })
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $releaseRoot "fluke-engines.json") -Encoding utf8
    return [pscustomobject]@{
        ReleaseRoot = $releaseRoot
        DownloadRoot = $downloadRoot
        AssetName = $assetName
        AssetHash = $assetHash
        AssetSize = $assetSize
        SourceHash = $sourceHash
    }
}

$testRoot = Join-Path $buildRoot ("calibre-reuse-test-" + [Guid]::NewGuid().ToString("N"))
$downloadRoot = Join-Path $testRoot "download-cache"
$probe = { param($executable) "ebook-convert.exe (calibre 9.15.0)" }
try {
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null
    $cacheAssetName = "cache-fallback.bin"
    $cachePath = Join-Path $downloadRoot $cacheAssetName
    Set-Content -LiteralPath $cachePath -Value "partial payload" -Encoding ascii
    $hashInput = Join-Path $testRoot "expected-download.bin"
    [IO.File]::WriteAllText($hashInput, "complete verified download", [Text.Encoding]::ASCII)
    $expectedDownloadHash = (Get-FileHash -LiteralPath $hashInput -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:syntheticDownloadText = "complete verified download"
    $cachedResult = Get-VerifiedAsset -Name $cacheAssetName -Uri "https://example.invalid/pinned" -Sha256 $expectedDownloadHash
    if ($cachedResult -ne $cachePath -or (Test-Path -LiteralPath "$cachePath.partial") -or
        (Get-FileHash -LiteralPath $cachePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedDownloadHash) {
        throw "Bad cache was not replaced through a verified partial download."
    }
    Write-Output "PASS corrupt cache was replaced through verified .partial download and rename."

    Set-Content -LiteralPath $cachePath -Value "bad cache" -Encoding ascii
    $script:syntheticDownloadText = "wrong downloaded payload"
    $failedDownload = $false
    try {
        $null = Get-VerifiedAsset -Name $cacheAssetName -Uri "https://example.invalid/pinned" -Sha256 $expectedDownloadHash
    } catch {
        $failedDownload = $true
    }
    if (-not $failedDownload -or (Test-Path -LiteralPath $cachePath) -or (Test-Path -LiteralPath "$cachePath.partial")) {
        throw "Hash-mismatched partial download was not cleaned up."
    }
    Write-Output "PASS hash-mismatched partial download and stale cache were removed."

    $valid = New-SyntheticCalibreRelease -Root (Join-Path $testRoot "valid")
    $validResult = Copy-VerifiedCalibreReleasePackage -ReleaseRoot $valid.ReleaseRoot `
        -DownloadRoot $valid.DownloadRoot -PackageRoot (Join-Path $valid.DownloadRoot "package-calibre") `
        -Version "9.15.0" -AssetName $valid.AssetName -AssetSha256 $valid.AssetHash `
        -AssetSizeBytes $valid.AssetSize -SourceArchive "source/calibre-9.15.0.tar.xz" `
        -SourceSha256 $valid.SourceHash -ProbeCommand $probe
    if (-not $validResult) { throw "Valid synthetic Calibre ZIP was not reused." }
    Write-Output "PASS valid ZIP and package were reused."

    $tampered = New-SyntheticCalibreRelease -Root (Join-Path $testRoot "tampered")
    Add-Content -LiteralPath (Join-Path $tampered.ReleaseRoot $tampered.AssetName) -Value "tampered"
    $tamperedResult = Copy-VerifiedCalibreReleasePackage -ReleaseRoot $tampered.ReleaseRoot `
        -DownloadRoot $tampered.DownloadRoot -PackageRoot (Join-Path $tampered.DownloadRoot "package-calibre") `
        -Version "9.15.0" -AssetName $tampered.AssetName -AssetSha256 $tampered.AssetHash `
        -AssetSizeBytes $tampered.AssetSize -SourceArchive "source/calibre-9.15.0.tar.xz" `
        -SourceSha256 $tampered.SourceHash -ProbeCommand $probe
    if ($tamperedResult) { throw "Tampered ZIP incorrectly passed validation." }
    Write-Output "PASS tampered ZIP was rejected."

    $hashFail = New-SyntheticCalibreRelease -Root (Join-Path $testRoot "hash-fail")
    $manifestPath = Join-Path $hashFail.ReleaseRoot "fluke-engines.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifest.components[0].sha256 = "0" * 64
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    $hashFailResult = Copy-VerifiedCalibreReleasePackage -ReleaseRoot $hashFail.ReleaseRoot `
        -DownloadRoot $hashFail.DownloadRoot -PackageRoot (Join-Path $hashFail.DownloadRoot "package-calibre") `
        -Version "9.15.0" -AssetName $hashFail.AssetName -AssetSha256 $hashFail.AssetHash `
        -AssetSizeBytes $hashFail.AssetSize -SourceArchive "source/calibre-9.15.0.tar.xz" `
        -SourceSha256 $hashFail.SourceHash -ProbeCommand $probe
    if ($hashFailResult) { throw "Manifest hash mismatch incorrectly passed validation." }
    Write-Output "PASS manifest ZIP-hash mismatch was rejected."

    $badSums = New-SyntheticCalibreRelease -Root (Join-Path $testRoot "bad-sums") -CorruptFileAfterChecksums
    $badSumsResult = Copy-VerifiedCalibreReleasePackage -ReleaseRoot $badSums.ReleaseRoot `
        -DownloadRoot $badSums.DownloadRoot -PackageRoot (Join-Path $badSums.DownloadRoot "package-calibre") `
        -Version "9.15.0" -AssetName $badSums.AssetName -AssetSha256 $badSums.AssetHash `
        -AssetSizeBytes $badSums.AssetSize -SourceArchive "source/calibre-9.15.0.tar.xz" `
        -SourceSha256 $badSums.SourceHash -ProbeCommand $probe
    if ($badSumsResult) { throw "A package with mismatched optional file sums incorrectly passed validation." }
    Write-Output "PASS mismatched optional FILE-SHA256SUMS was rejected."
} finally {
    $resolvedBuildRoot = [IO.Path]::GetFullPath($buildRoot) + [IO.Path]::DirectorySeparatorChar
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot.StartsWith($resolvedBuildRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedTestRoot)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
