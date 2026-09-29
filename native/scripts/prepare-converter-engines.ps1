$ErrorActionPreference = "Stop"

$nativeRoot = Split-Path -Parent $PSScriptRoot
$downloadRoot = Join-Path $nativeRoot "build\converter-engines"
$bundleRoot = Join-Path $nativeRoot "third-party\converter-engines"
$componentRoot = Join-Path $bundleRoot "ffmpeg"
$archiveName = "ffmpeg-n9.0.2-10-g51c4a23d74-win64-lgpl-shared-9.0.zip"
$archivePath = Join-Path $downloadRoot $archiveName
$archiveUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-26-13-03/$archiveName"
$archiveSha256 = "8f3a5190804eed8c0f4927dbac688bcc35a1d2b9c36d7bf9a4386ec7bd1627ed"
$sourceName = "ffmpeg-g51c4a23d74.tar.gz"
$sourcePath = Join-Path $downloadRoot $sourceName
$sourceUrl = "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/51c4a23d74"
$sourceArchiveSha256 = "10323f69c6a2b69e035c5cfdd3a1ab366af784e3bbe25d1cb64534027791b384"
$copyingPath = Join-Path $downloadRoot "COPYING.LGPLv3"
$copyingUrl = "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n9.0.2/COPYING.LGPLv3"

New-Item -ItemType Directory -Force -Path $downloadRoot, $bundleRoot | Out-Null

if (-not (Test-Path -LiteralPath $archivePath)) {
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing -TimeoutSec 240
}
$actualArchiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualArchiveHash -ne $archiveSha256) {
    throw "FFmpeg source archive SHA-256 did not match the pinned BtbN release."
}

if (Test-Path -LiteralPath $sourcePath) {
    $sourceInfo = Get-Item -LiteralPath $sourcePath
    $sourceStream = [IO.File]::OpenRead($sourcePath)
    try {
        $gzipMagic = $sourceStream.ReadByte() -eq 0x1f -and $sourceStream.ReadByte() -eq 0x8b
    } finally {
        $sourceStream.Dispose()
    }
    if ($sourceInfo.Length -lt 100KB -or -not $gzipMagic) {
        Remove-Item -LiteralPath $sourcePath -Force
    }
}
if (-not (Test-Path -LiteralPath $sourcePath)) {
    $providedSource = $env:FLUKE_FFMPEG_SOURCE_ARCHIVE
    if ($providedSource -and (Test-Path -LiteralPath $providedSource)) {
        Copy-Item -LiteralPath $providedSource -Destination $sourcePath
    } else {
        Invoke-WebRequest -Uri $sourceUrl -OutFile $sourcePath -UseBasicParsing -TimeoutSec 120
    }
}
$sourceInfo = Get-Item -LiteralPath $sourcePath
$sourceStream = [IO.File]::OpenRead($sourcePath)
try {
    $gzipMagic = $sourceStream.ReadByte() -eq 0x1f -and $sourceStream.ReadByte() -eq 0x8b
} finally {
    $sourceStream.Dispose()
}
if ($sourceInfo.Length -lt 100KB -or -not $gzipMagic) {
    throw "The pinned FFmpeg source archive is invalid; the LGPL engine was not packaged."
}
$actualSourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSourceHash -ne $sourceArchiveSha256) {
    throw "FFmpeg source archive SHA-256 did not match the pinned source commit."
}
if (-not (Test-Path -LiteralPath $copyingPath)) {
    Invoke-WebRequest -Uri $copyingUrl -OutFile $copyingPath -UseBasicParsing -TimeoutSec 30
}
$copyingText = Get-Content -LiteralPath $copyingPath -Raw
if ($copyingText -notmatch "GNU LESSER GENERAL PUBLIC LICENSE" -or $copyingText -notmatch "Version 3") {
    throw "The fetched FFmpeg LGPLv3 license text is invalid."
}

$stagingRoot = Join-Path $downloadRoot "extract-ffmpeg"
$packageRoot = Join-Path $downloadRoot "package-ffmpeg"
foreach ($temporaryRoot in @($stagingRoot, $packageRoot)) {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
        $resolvedDownloadRoot = [IO.Path]::GetFullPath($downloadRoot)
        if (-not $resolvedTemporary.StartsWith($resolvedDownloadRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a temporary directory outside the converter-engine download area."
        }
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
Expand-Archive -LiteralPath $archivePath -DestinationPath $stagingRoot -Force
$upstreamRoot = Get-ChildItem -LiteralPath $stagingRoot -Directory | Select-Object -First 1
if (-not $upstreamRoot) {
    throw "The FFmpeg archive did not contain its expected top-level folder."
}
$upstreamBin = Join-Path $upstreamRoot.FullName "bin"
if (-not (Test-Path -LiteralPath (Join-Path $upstreamBin "ffmpeg.exe")) -or
    -not (Test-Path -LiteralPath (Join-Path $upstreamBin "ffprobe.exe"))) {
    throw "The FFmpeg archive is missing ffmpeg.exe or ffprobe.exe."
}

New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "bin"), (Join-Path $packageRoot "source") | Out-Null
Copy-Item -LiteralPath (Join-Path $upstreamBin "ffmpeg.exe") -Destination (Join-Path $packageRoot "bin")
Copy-Item -LiteralPath (Join-Path $upstreamBin "ffprobe.exe") -Destination (Join-Path $packageRoot "bin")
Get-ChildItem -LiteralPath $upstreamBin -Filter "*.dll" -File | Copy-Item -Destination (Join-Path $packageRoot "bin")
Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $packageRoot "source")
Copy-Item -LiteralPath $copyingPath -Destination (Join-Path $packageRoot "COPYING.LGPLv3")

$ffmpegExe = Join-Path $packageRoot "bin\ffmpeg.exe"
$versionOutput = (& $ffmpegExe -version 2>&1 | Out-String)
$buildConfiguration = (& $ffmpegExe -buildconf 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "ffmpeg version n9\.0\.2-10-g51c4a23d74") {
    throw "The packaged FFmpeg executable did not report the pinned upstream build."
}
if ($buildConfiguration -match "--enable-(gpl|nonfree)") {
    throw "The pinned FFmpeg binary unexpectedly enables GPL or nonfree components."
}
Set-Content -LiteralPath (Join-Path $packageRoot "BUILD-CONFIGURATION.txt") -Value $buildConfiguration.TrimEnd() -Encoding utf8

$sourceSha256 = (Get-FileHash -LiteralPath (Join-Path $packageRoot "source\$sourceName") -Algorithm SHA256).Hash.ToLowerInvariant()
$metadata = [ordered]@{
    id = "ffmpeg"
    version = "9.0.2-10-g51c4a23d74"
    executable = "bin/ffmpeg.exe"
    probeArgument = "-version"
    upstream = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-26-13-03/$archiveName"
    upstreamSha256 = $archiveSha256
    ffmpegSource = $sourceUrl
    ffmpegSourceSha256 = $sourceSha256
    license = "LGPL-3.0-or-later"
}
$metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $packageRoot "engine.json") -Encoding utf8

$notice = @"
FFmpeg engine bundled by FLUKE

This folder contains FFmpeg $($metadata.version), built and distributed as the separate win64 LGPL shared package from BtbN/FFmpeg-Builds. Its configuration enables version 3 terms. The FFmpeg process is invoked as a separate executable; FLUKE does not link to its libraries.

FFmpeg is licensed under LGPL 3 or later. The exact corresponding FFmpeg source snapshot is included at source/$sourceName (SHA-256: $sourceSha256). The upstream build recipe and binary package are pinned at:
$archiveUrl

The binary package SHA-256 is $archiveSha256. The exact FFmpeg source commit is:
$($metadata.ffmpegSource)

The captured build configuration is in BUILD-CONFIGURATION.txt. This distribution uses the LGPL shared build; the configuration is checked to reject --enable-gpl and --enable-nonfree. See COPYING.LGPLv3 and the upstream FFmpeg legal information at https://ffmpeg.org/legal.html. BtbN build scripts and other upstream notices are available at https://github.com/BtbN/FFmpeg-Builds/tree/autobuild-2026-09-26-13-03.
"@
Set-Content -LiteralPath (Join-Path $packageRoot "THIRD-PARTY-NOTICES.md") -Value $notice -Encoding utf8

if (Test-Path -LiteralPath $componentRoot) {
    $resolvedComponent = [IO.Path]::GetFullPath($componentRoot)
    $resolvedBundleRoot = [IO.Path]::GetFullPath($bundleRoot)
    if (-not $resolvedComponent.StartsWith($resolvedBundleRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace a component outside third-party/converter-engines."
    }
    Remove-Item -LiteralPath $resolvedComponent -Recurse -Force
}
Move-Item -LiteralPath $packageRoot -Destination $componentRoot
Write-Output "Prepared FFmpeg $($metadata.version) in third-party/converter-engines/ffmpeg."
