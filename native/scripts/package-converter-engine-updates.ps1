param(
    [Parameter(Mandatory = $true)][string]$Version
)

$ErrorActionPreference = "Stop"
$nativeRoot = Split-Path -Parent $PSScriptRoot
$bundleRoot = Join-Path $nativeRoot "third-party\converter-engines"
$outputRoot = Join-Path $nativeRoot "release\engine-updates"
$releaseTag = "v$Version"

if (Test-Path -LiteralPath $outputRoot) {
    $resolvedOutput = [IO.Path]::GetFullPath($outputRoot)
    $resolvedRelease = [IO.Path]::GetFullPath((Join-Path $nativeRoot "release"))
    if (-not $resolvedOutput.StartsWith($resolvedRelease + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean engine update artifacts outside the release directory."
    }
    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$components = @()
foreach ($engineId in @("ffmpeg", "tesseract", "calibre")) {
    $engineRoot = Join-Path $bundleRoot $engineId
    $metadataPath = Join-Path $engineRoot "engine.json"
    if (-not (Test-Path -LiteralPath $metadataPath)) { continue }
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    if ($metadata.id -ne $engineId -or [string]::IsNullOrWhiteSpace([string]$metadata.version)) {
        throw "Invalid metadata for converter engine $engineId."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $engineRoot "THIRD-PARTY-NOTICES.md"))) {
        throw "Converter engine $engineId is missing its third-party license notice."
    }
    if (($engineId -eq "ffmpeg" -or $engineId -eq "tesseract" -or $engineId -eq "calibre") -and
        -not (Get-ChildItem -LiteralPath (Join-Path $engineRoot "source") -File -ErrorAction SilentlyContinue)) {
        throw "Converter engine $engineId is missing its corresponding source archive."
    }
    $asset = "fluke-engine-$engineId-win-x64-$($metadata.version).zip"
    $assetPath = Join-Path $outputRoot $asset
    Compress-Archive -Path (Join-Path $engineRoot "*") -DestinationPath $assetPath -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $size = (Get-Item -LiteralPath $assetPath).Length
    if ($size -gt 1GB) { throw "Converter engine package $engineId exceeds the update channel limit." }
    $components += [ordered]@{
        id = $engineId
        version = [string]$metadata.version
        asset = $asset
        sha256 = $hash
        sizeBytes = $size
    }
}
if ($components.Count -eq 0) {
    throw "No converter engine bundles are available to publish."
}

$manifest = [ordered]@{
    schemaVersion = 1
    releaseTag = $releaseTag
    components = $components
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputRoot "fluke-engines.json") -Encoding utf8
Write-Output "Prepared $($components.Count) updateable converter engine package(s) in release/engine-updates."
