param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$ReleaseTag
)

$ErrorActionPreference = "Stop"
$nativeRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $nativeRoot "release"
$engineRoot = Join-Path $releaseRoot "engine-updates"

if ($ReleaseTag -notmatch "^native-v$([regex]::Escape($Version))-preview\.[1-9][0-9]*$") {
    throw "Release tag '$ReleaseTag' must match native-v$Version-preview.N."
}

$setupPath = Join-Path $releaseRoot "FLUKE-$Version-Setup.exe"
if (-not (Test-Path -LiteralPath $setupPath -PathType Leaf)) {
    throw "Setup installer is missing: $setupPath"
}
$setupHash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecarPath = "$setupPath.sha256"
if (Test-Path -LiteralPath $sidecarPath -PathType Leaf) {
    $sidecar = (Get-Content -LiteralPath $sidecarPath -Raw).Trim()
    if ($sidecar -notmatch "^([A-Fa-f0-9]{64})(?:\s+\*?.+)?$") {
        throw "Setup SHA-256 sidecar has an invalid format: $sidecarPath"
    }
    $sidecarName = [regex]::Match($sidecar, "^[A-Fa-f0-9]{64}(?:\s+\*?(.+))?$").Groups[1].Value.Trim()
    if ($sidecarName -and $sidecarName -cne (Split-Path -Leaf $setupPath)) {
        throw "Setup SHA-256 sidecar names '$sidecarName', expected '$(Split-Path -Leaf $setupPath)'."
    }
    if ($Matches[1] -ine $setupHash) {
        throw "Setup SHA-256 sidecar does not match the installer: $sidecarPath"
    }
} else {
    Set-Content -LiteralPath $sidecarPath -Value "$setupHash  $(Split-Path -Leaf $setupPath)" -Encoding ascii -NoNewline
}

$manifestPath = Join-Path $engineRoot "fluke-engines.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Engine update manifest is missing: $manifestPath"
}
try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
} catch {
    throw "Could not parse engine update manifest '$manifestPath': $($_.Exception.Message)"
}
if ($manifest.schemaVersion -ne 1) {
    throw "Engine update manifest schemaVersion must be 1."
}
if ($manifest.releaseTag -cne $ReleaseTag) {
    throw "Engine update manifest targets '$($manifest.releaseTag)', expected '$ReleaseTag'."
}

$expectedIds = @("ffmpeg", "tesseract", "calibre")
$components = @($manifest.components)
if ($components.Count -ne $expectedIds.Count) {
    throw "Engine update manifest must contain exactly ffmpeg, tesseract, and calibre."
}
$foundIds = @($components | ForEach-Object { [string]$_.id })
if (@($foundIds | Select-Object -Unique).Count -ne $expectedIds.Count -or
    @($foundIds | Where-Object { $_ -notin $expectedIds }).Count -gt 0 -or
    @($expectedIds | Where-Object { $_ -notin $foundIds }).Count -gt 0) {
    throw "Engine update manifest must contain exactly one each of ffmpeg, tesseract, and calibre."
}

foreach ($component in $components) {
    $engineId = [string]$component.id
    $engineVersion = [string]$component.version
    if ($engineVersion -notmatch "^[A-Za-z0-9._+-]+$") {
        throw "Engine '$engineId' has an invalid version in the manifest."
    }
    $expectedAsset = "fluke-engine-$engineId-win-x64-$engineVersion.zip"
    if ([string]$component.asset -cne $expectedAsset) {
        throw "Engine '$engineId' asset must be named '$expectedAsset'."
    }
    if ([string]$component.sha256 -notmatch "^[A-Fa-f0-9]{64}$") {
        throw "Engine '$engineId' has an invalid SHA-256 in the manifest."
    }
    $expectedSize = 0L
    if (-not [long]::TryParse([string]$component.sizeBytes, [ref]$expectedSize) -or $expectedSize -lt 0) {
        throw "Engine '$engineId' has an invalid sizeBytes value in the manifest."
    }
    $assetPath = Join-Path $engineRoot $expectedAsset
    if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
        throw "Engine package is missing: $assetPath"
    }
    $actualSize = (Get-Item -LiteralPath $assetPath).Length
    if ($actualSize -ne $expectedSize) {
        throw "Engine '$engineId' size mismatch: manifest=$expectedSize, file=$actualSize."
    }
    if ($actualSize -ge 1GB) {
        throw "Engine '$engineId' package must be smaller than the app's 1 GB limit."
    }
    $actualHash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash
    if ($actualHash -ine [string]$component.sha256) {
        throw "Engine '$engineId' SHA-256 does not match the manifest."
    }
}

Write-Output "Verified FLUKE $Version release artifacts for $ReleaseTag."
Write-Output "Setup SHA-256: $setupHash"
Write-Output "Verified engine packages: $($components.Count)"
