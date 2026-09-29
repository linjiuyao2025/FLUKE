param(
    [string]$DestinationRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) "third-party\converter-engines")
)

$ErrorActionPreference = "Stop"
$nativeRoot = Split-Path -Parent $PSScriptRoot
$candidateRoot = Join-Path $nativeRoot "vendor\ffmpeg-no-zvbi"
$buildRoot = Join-Path $nativeRoot "build\ffmpeg-no-zvbi"
$cacheRoot = Join-Path $buildRoot "source\msys2"
$manifestPath = Join-Path $candidateRoot "source-manifest.json"
$runtimePath = Join-Path $candidateRoot "runtime-dependencies.json"
$binSource = Join-Path $candidateRoot "bin"

$destinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
$defaultDestination = [IO.Path]::GetFullPath((Join-Path $nativeRoot "third-party\converter-engines"))
$buildArea = [IO.Path]::GetFullPath((Join-Path $nativeRoot "build"))
$buildAreaPrefix = $buildArea + [IO.Path]::DirectorySeparatorChar
if ($destinationRoot -ne $defaultDestination -and
    -not $destinationRoot.StartsWith($buildAreaPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The package destination must be third-party\converter-engines or an isolated directory under native\build."
}

foreach ($requiredPath in @($candidateRoot, $manifestPath, $runtimePath, $binSource)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Required FFmpeg candidate input is missing: $requiredPath" }
}

$sourceManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
if ($sourceManifest.ffmpeg.version -ne "9.0.2-10-g51c4a23d74" -or
    $sourceManifest.ffmpeg.sourceSha256 -ne "10323f69c6a2b69e035c5cfdd3a1ab366af784e3bbe25d1cb64534027791b384") {
    throw "The FFmpeg source manifest does not match the reviewed source commit."
}

New-Item -ItemType Directory -Force -Path $cacheRoot, $destinationRoot | Out-Null
foreach ($package in $sourceManifest.externalPackages) {
    if ([string]$package.sourceOnlyArchive -notmatch "^[A-Za-z0-9._+-]+\.src\.tar\.zst$") {
        throw "Unsafe source-only archive name in source manifest."
    }
    $archiveName = [string]$package.sourceOnlyArchive
    $candidateArchive = Join-Path (Join-Path $candidateRoot "source\msys2") $archiveName
    $cacheArchive = Join-Path $cacheRoot $archiveName
    if (Test-Path -LiteralPath $candidateArchive -PathType Leaf) {
        $archivePath = $candidateArchive
    } elseif (Test-Path -LiteralPath $cacheArchive -PathType Leaf) {
        $archivePath = $cacheArchive
    } else {
        if ([string]::IsNullOrWhiteSpace([string]$package.sourceOnlyUrl) -or
            [string]$package.sourceOnlyUrl -notmatch "^https://mirror\.msys2\.org/mingw/sources/[A-Za-z0-9._+-]+\.src\.tar\.zst$") {
            throw "No pinned MSYS2 mirror URL is available for $archiveName."
        }
        $partialPath = "$cacheArchive.partial"
        if (Test-Path -LiteralPath $partialPath) { Remove-Item -LiteralPath $partialPath -Force }
        Invoke-WebRequest -Uri ([string]$package.sourceOnlyUrl) -OutFile $partialPath -UseBasicParsing -TimeoutSec 600
        $downloadHash = (Get-FileHash -LiteralPath $partialPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($downloadHash -ne [string]$package.sourceOnlyArchiveSha256) {
            Remove-Item -LiteralPath $partialPath -Force
            throw "Downloaded source archive SHA-256 mismatch for $archiveName."
        }
        Move-Item -LiteralPath $partialPath -Destination $cacheArchive
        $archivePath = $cacheArchive
    }
    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($archiveHash -ne [string]$package.sourceOnlyArchiveSha256) {
        throw "Source-only archive SHA-256 mismatch for $archiveName."
    }
    if ($package.srcInfoFile) {
        $srcInfo = Join-Path (Join-Path $candidateRoot "source\msys2") ([string]$package.srcInfoFile)
        if (-not (Test-Path -LiteralPath $srcInfo -PathType Leaf) -or
            (Get-FileHash -LiteralPath $srcInfo -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$package.srcInfoSha256) {
            throw "Pinned MSYS2 .SRCINFO is missing or changed for $archiveName."
        }
    }
}

$ffmpegSource = Join-Path $candidateRoot "source\ffmpeg\ffmpeg-g51c4a23d74.tar.gz"
if (-not (Test-Path -LiteralPath $ffmpegSource -PathType Leaf) -or
    (Get-FileHash -LiteralPath $ffmpegSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$sourceManifest.ffmpeg.sourceSha256) {
    throw "The pinned FFmpeg source archive is missing or changed."
}
foreach ($license in $sourceManifest.licenseTexts) {
    $relativeLicense = [string]$license.path
    if ($relativeLicense -notmatch "^notices/[A-Za-z0-9._+-]+$") { throw "Unsafe license path in source manifest." }
    $licensePath = Join-Path $candidateRoot ($relativeLicense.Replace("/", [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $licensePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$license.sha256) {
        throw "License text is missing or changed: $relativeLicense"
    }
}

if (@($runtimeManifest.unresolved).Count -ne 0) {
    throw "The recorded FFmpeg PE dependency closure contains unresolved imports."
}
$candidateFiles = @{}
foreach ($file in $runtimeManifest.pe_files) {
    if ([string]$file.file -notmatch "^[A-Za-z0-9._+-]+\.(exe|dll)$") { throw "Unsafe PE filename in runtime manifest." }
    $candidateFiles[[string]$file.file] = [string]$file.sha256
    $path = Join-Path $binSource ([string]$file.file)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$file.sha256) {
        throw "Candidate PE hash mismatch: $($file.file)"
    }
}
foreach ($import in $runtimeManifest.imports) {
    if ($import.kind -eq "candidate-stage" -and -not $candidateFiles.ContainsKey([string]$import.dll)) {
        throw "PE dependency closure omits required candidate DLL $($import.dll)."
    }
    if ($import.kind -notin @("candidate-stage", "windows-system32", "windows-api-set")) {
        throw "Unexpected PE dependency classification $($import.kind) for $($import.dll)."
    }
}

$configurationPath = Join-Path $candidateRoot "BUILD-CONFIGURATION.txt"
$encodersPath = Join-Path $candidateRoot "encoders.txt"
$muxersPath = Join-Path $candidateRoot "muxers.txt"
$buildConfiguration = Get-Content -LiteralPath $configurationPath -Raw
$encoderListing = Get-Content -LiteralPath $encodersPath -Raw
$muxerListing = Get-Content -LiteralPath $muxersPath -Raw
if ($buildConfiguration -match "--enable-(gpl|nonfree)" -or
    $buildConfiguration -notmatch "--disable-libzvbi" -or
    $buildConfiguration -notmatch "--enable-shared" -or
    $buildConfiguration -notmatch "--enable-mediafoundation" -or
    $buildConfiguration -notmatch "--enable-d3d11va") {
    throw "FFmpeg build flags do not match the reviewed LGPL/no-libzvbi candidate."
}
foreach ($encoder in @("libmp3lame", "libopus", "libvorbis", "libvpx-vp9", "h264_mf", "hevc_mf", "aac", "aac_mf", "flac", "wmav2", "mpeg4")) {
    if ($encoderListing -notmatch "(?m)^\s+[A-Z\.]{6}\s+$([regex]::Escape($encoder))\s") {
        throw "Required FFmpeg encoder is missing: $encoder"
    }
}
foreach ($muxer in @("mp3", "wav", "flac", "adts", "ogg", "opus", "asf", "avi", "mp4", "matroska", "mov", "webm")) {
    if ($muxerListing -notmatch "(?m)^\s+E\s+$([regex]::Escape($muxer))\s") {
        throw "Required FFmpeg muxer is missing: $muxer"
    }
}

$packageRoot = Join-Path $buildRoot "package-ffmpeg"
if (Test-Path -LiteralPath $packageRoot) {
    $resolvedPackage = [IO.Path]::GetFullPath($packageRoot)
    $buildPrefix = [IO.Path]::GetFullPath($buildRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPackage.StartsWith($buildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a FFmpeg package staging directory outside native\build."
    }
    Remove-Item -LiteralPath $resolvedPackage -Recurse -Force
}
$packageBin = Join-Path $packageRoot "bin"
$packageSources = Join-Path $packageRoot "source"
New-Item -ItemType Directory -Force -Path $packageBin, (Join-Path $packageSources "ffmpeg"), (Join-Path $packageSources "msys2"), (Join-Path $packageRoot "notices") | Out-Null
foreach ($file in $runtimeManifest.pe_files) {
    Copy-Item -LiteralPath (Join-Path $binSource ([string]$file.file)) -Destination $packageBin
}
Copy-Item -LiteralPath $ffmpegSource -Destination (Join-Path $packageSources "ffmpeg")
foreach ($package in $sourceManifest.externalPackages) {
    $archiveName = [string]$package.sourceOnlyArchive
    $candidateArchive = Join-Path (Join-Path $candidateRoot "source\msys2") $archiveName
    $cacheArchive = Join-Path $cacheRoot $archiveName
    $archivePath = if (Test-Path -LiteralPath $candidateArchive -PathType Leaf) { $candidateArchive } else { $cacheArchive }
    Copy-Item -LiteralPath $archivePath -Destination (Join-Path $packageSources "msys2")
    if ($package.srcInfoFile) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $candidateRoot "source\msys2") ([string]$package.srcInfoFile)) -Destination (Join-Path $packageSources "msys2")
    }
}
Copy-Item -LiteralPath $manifestPath -Destination $packageRoot
Copy-Item -LiteralPath $runtimePath -Destination $packageRoot
foreach ($name in @("BUILD-CONFIGURATION.txt", "FFMPEG-VERSION.txt", "encoders.txt", "muxers.txt")) {
    Copy-Item -LiteralPath (Join-Path $candidateRoot $name) -Destination $packageRoot
}
foreach ($noticeFile in Get-ChildItem -LiteralPath (Join-Path $candidateRoot "notices") -File) {
    Copy-Item -LiteralPath $noticeFile.FullName -Destination (Join-Path $packageRoot "notices")
}
Copy-Item -LiteralPath (Join-Path (Join-Path $candidateRoot "notices") "THIRD-PARTY-NOTICES.md") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $candidateRoot "provenance") -Destination $packageRoot -Recurse
Copy-Item -LiteralPath (Join-Path $candidateRoot "validation") -Destination $packageRoot -Recurse
Copy-Item -LiteralPath (Join-Path $candidateRoot "CANDIDATE-STATUS.md") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $candidateRoot "engine.json") -Destination $packageRoot

$oldPath = $env:Path
try {
    $env:Path = "$packageBin;$env:SystemRoot\System32;$env:SystemRoot"
    $versionOutput = (& (Join-Path $packageBin "ffmpeg.exe") -version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "ffmpeg version 9\.0\.2") {
        throw "The standalone FFmpeg executable failed its clean-PATH version check."
    }
    $cleanBuildConfiguration = (& (Join-Path $packageBin "ffmpeg.exe") -buildconf 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $cleanBuildConfiguration -match "--enable-(gpl|nonfree)" -or
        $cleanBuildConfiguration -notmatch "--disable-libzvbi") {
        throw "The clean-PATH executable's build configuration is invalid."
    }
    $cleanEncoders = (& (Join-Path $packageBin "ffmpeg.exe") -hide_banner -encoders 2>&1 | Out-String)
    $cleanMuxers = (& (Join-Path $packageBin "ffmpeg.exe") -hide_banner -muxers 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $cleanEncoders -notmatch "libvpx-vp9" -or $cleanEncoders -notmatch "libmp3lame" -or
        $cleanMuxers -notmatch "(?m)^\s+E\s+webm\s" -or $cleanMuxers -notmatch "(?m)^\s+E\s+mp3\s") {
        throw "The clean-PATH executable failed the encoder/muxer check."
    }
} finally {
    $env:Path = $oldPath
}
Set-Content -LiteralPath (Join-Path $packageRoot "BUILD-CONFIGURATION.txt") -Value $cleanBuildConfiguration.TrimEnd() -Encoding utf8

$componentRoot = Join-Path $destinationRoot "ffmpeg"
if (Test-Path -LiteralPath $componentRoot) {
    $resolvedComponent = [IO.Path]::GetFullPath($componentRoot)
    if (-not $resolvedComponent.StartsWith($destinationRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace an FFmpeg component outside the requested destination."
    }
    Remove-Item -LiteralPath $resolvedComponent -Recurse -Force
}
Move-Item -LiteralPath $packageRoot -Destination $componentRoot
Write-Output "Prepared standalone FLUKE FFmpeg candidate at $componentRoot."
Write-Output "The verified GCC source archive remains in ignored native\build cache and was included in the candidate package."
