param(
    [Parameter(Mandatory = $true)][string]$DownloadRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot
)

$ErrorActionPreference = "Stop"
$lockPath = Join-Path $PSScriptRoot "tesseract-msys2-lock.json"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
if ($lock.schemaVersion -ne 1 -or $lock.rootPackage -ne "mingw-w64-x86_64-tesseract-ocr") {
    throw "The Tesseract MSYS2 lock file has an unsupported schema or root package."
}

function Get-VerifiedAsset {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Sha256
    )

    $isMsys2Asset = $Uri -match "^https://mirror\.msys2\.org/mingw/(mingw64|sources)/[A-Za-z0-9._+/%-]+$"
    $isPinnedModel = $Uri -match "^https://raw\.githubusercontent\.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/(eng\.traineddata|chi_sim\.traineddata|LICENSE)$"
    if ($Sha256 -notmatch "^[0-9a-fA-F]{64}$" -or (-not $isMsys2Asset -and -not $isPinnedModel)) {
        throw "The locked asset has an invalid URL or SHA-256."
    }
    $path = Join-Path $DownloadRoot $Name
    if (-not (Test-Path -LiteralPath $path)) {
        $null = Invoke-WebRequest -Uri $Uri -OutFile $path -UseBasicParsing -TimeoutSec 600
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for locked MSYS2 asset $Name."
    }
    return $path
}

function Remove-GeneratedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetFullPath($DownloadRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a Tesseract build path outside its download root."
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

$null = New-Item -ItemType Directory -Force -Path $DownloadRoot
$resolvedDownloadRoot = [IO.Path]::GetFullPath($DownloadRoot)
$resolvedOutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (-not $resolvedOutputRoot.StartsWith($resolvedDownloadRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The generated Tesseract package must stay inside the converter-engine build directory."
}

$packageStageRoot = Join-Path $DownloadRoot "msys2-tesseract-stage"
$tesseractVersion = "5.5.3"
$bundleVersion = "5.5.3.20260929.1"
$tessdataFastCommit = "87416418657359cb625c412a48b6e1d6d41c29bd"
$tessdataFastBase = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$tessdataFastCommit"
$models = @(
    @{ Name = "eng.traineddata"; Sha256 = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2" },
    @{ Name = "chi_sim.traineddata"; Sha256 = "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730" }
)
$tessdataLicenseHash = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
$rootPackage = @($lock.packages | Where-Object { $_.name -eq $lock.rootPackage })
$runtimePackages = @($lock.packages | Where-Object { $_.shipped })
if ($rootPackage.Count -ne 1 -or $runtimePackages.Count -lt 1) {
    throw "The Tesseract MSYS2 lock is missing its root package or runtime packages."
}
$rootPackage = $rootPackage[0]

Remove-GeneratedPath -Path $packageStageRoot
Remove-GeneratedPath -Path $OutputRoot
New-Item -ItemType Directory -Force -Path $packageStageRoot, $OutputRoot | Out-Null
$tessdataTarget = Join-Path $OutputRoot "tessdata"
$licenseTarget = Join-Path $OutputRoot "licenses\msys2"
$sourceTarget = Join-Path $OutputRoot "source\msys2"
New-Item -ItemType Directory -Force -Path $tessdataTarget, $licenseTarget, $sourceTarget | Out-Null
$dllOwners = @{}
$packageFiles = @{}
$packageSources = @{}
$lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()

try {
    foreach ($package in $runtimePackages) {
        if ([string]::IsNullOrWhiteSpace([string]$package.version) -or
            [string]::IsNullOrWhiteSpace([string]$package.binary) -or
            [string]::IsNullOrWhiteSpace([string]$package.binarySha256)) {
            throw "The lock entry for $($package.name) is incomplete."
        }
        $assetName = "msys2-$($package.name)-$($package.version).pkg.tar.zst"
        $asset = Get-VerifiedAsset -Name $assetName -Uri $package.binary -Sha256 $package.binarySha256
        $pkgInfo = (& tar.exe -xOf $asset ".PKGINFO" 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            throw "The locked package $($package.name) has no readable .PKGINFO."
        }
        $pkgName = [regex]::Match($pkgInfo, "(?m)^pkgname = (.+)$").Groups[1].Value.Trim()
        $pkgVersion = [regex]::Match($pkgInfo, "(?m)^pkgver = (.+)$").Groups[1].Value.Trim()
        if ($pkgName -ne $package.name -or $pkgVersion -ne $package.version) {
            throw "The archive identity for $($package.name) does not match the lock."
        }

        $packageStage = Join-Path $packageStageRoot $package.name
        New-Item -ItemType Directory -Force -Path $packageStage | Out-Null
        $paths = @($package.runtimeFiles)
        foreach ($relativePath in $paths) {
            if ($relativePath -notmatch "^mingw64/[A-Za-z0-9._+/-]+$" -or $relativePath.Contains("..")) {
                throw "The lock contains an unsafe archive path for $($package.name)."
            }
        }
        if ($paths.Count -gt 0) {
            & tar.exe -xf $asset -C $packageStage @paths
            if ($LASTEXITCODE -ne 0) {
                throw "Could not extract the locked runtime files for $($package.name)."
            }
        }

        $packageRows = @()
        foreach ($relativePath in $paths) {
            $sourcePath = Join-Path $packageStage ($relativePath.Replace("/", [IO.Path]::DirectorySeparatorChar))
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { continue }

            if ($relativePath -match "^mingw64/bin/([^/]+\.dll)$") {
                $fileName = $Matches[1]
                if ($dllOwners.ContainsKey($fileName)) {
                    throw "Two pinned MSYS2 packages provide the same DLL name: $fileName."
                }
                $destination = Join-Path $OutputRoot $fileName
                Copy-Item -LiteralPath $sourcePath -Destination $destination
                $dllOwners[$fileName] = $package.name
                $bundlePath = $fileName
            } elseif ($relativePath -eq "mingw64/bin/tesseract.exe") {
                $destination = Join-Path $OutputRoot "tesseract.exe"
                Copy-Item -LiteralPath $sourcePath -Destination $destination
                $bundlePath = "tesseract.exe"
            } elseif ($relativePath.StartsWith("mingw64/share/tessdata/", [StringComparison]::OrdinalIgnoreCase)) {
                $tail = $relativePath.Substring("mingw64/share/tessdata/".Length)
                $destination = Join-Path $tessdataTarget ($tail.Replace("/", [IO.Path]::DirectorySeparatorChar))
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
                Copy-Item -LiteralPath $sourcePath -Destination $destination
                $bundlePath = "tessdata/$tail"
            } elseif ($relativePath.StartsWith("mingw64/share/licenses/", [StringComparison]::OrdinalIgnoreCase)) {
                $tail = $relativePath.Substring("mingw64/share/licenses/".Length)
                $destination = Join-Path (Join-Path $licenseTarget $package.name) ($tail.Replace("/", [IO.Path]::DirectorySeparatorChar))
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
                Copy-Item -LiteralPath $sourcePath -Destination $destination
                $bundlePath = "licenses/msys2/$($package.name)/$tail"
            } else {
                $destination = Join-Path $OutputRoot ($relativePath.Replace("/", [IO.Path]::DirectorySeparatorChar))
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
                Copy-Item -LiteralPath $sourcePath -Destination $destination
                $bundlePath = $relativePath
            }

            $fileHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
            $packageRows += [ordered]@{
                packagePath = $relativePath
                bundlePath = $bundlePath
                sha256 = $fileHash
            }
        }
        $packageFiles[$package.name] = @($packageRows)
    }

    $sourceAssets = @{}
    foreach ($package in @($lock.packages | Where-Object { $_.includeSourceArchive })) {
        if ([string]::IsNullOrWhiteSpace([string]$package.sourceSha256)) {
            throw "The source archive hash for $($package.name) is not pinned."
        }
        if ($sourceAssets.ContainsKey($package.source)) {
            if ($sourceAssets[$package.source].sha256 -ne $package.sourceSha256) {
                throw "Packages sharing a source URL have inconsistent source hashes."
            }
            $sourcePath = $sourceAssets[$package.source].path
        } else {
            $sourceName = [System.Uri]::UnescapeDataString([IO.Path]::GetFileName(([Uri]$package.source).AbsolutePath))
            $assetName = "source-$sourceName"
            $asset = Get-VerifiedAsset -Name $assetName -Uri $package.source -Sha256 $package.sourceSha256
            $archiveListing = (& tar.exe -tf $asset 2>&1 | Out-String)
            if ($LASTEXITCODE -ne 0 -or $archiveListing -notmatch "(?m)(^|/)PKGBUILD(\r?$)") {
                throw "The source archive for $($package.name) is missing its package build recipe."
            }
            $sourcePath = Join-Path $sourceTarget $sourceName
            Copy-Item -LiteralPath $asset -Destination $sourcePath
            $sourceAssets[$package.source] = [ordered]@{
                sha256 = $package.sourceSha256
                path = $sourcePath
                relativePath = "source/msys2/$sourceName"
            }
        }
        $packageSources[$package.name] = [ordered]@{
            url = $package.source
            sha256 = $package.sourceSha256
            path = $sourceAssets[$package.source].relativePath
        }
    }

    foreach ($model in $models) {
        $asset = Get-VerifiedAsset -Name $model.Name -Uri "$tessdataFastBase/$($model.Name)" -Sha256 $model.Sha256
        Copy-Item -LiteralPath $asset -Destination (Join-Path $tessdataTarget $model.Name) -Force
    }
    $licenseAsset = Get-VerifiedAsset -Name "tessdata_fast-LICENSE" -Uri "$tessdataFastBase/LICENSE" -Sha256 $tessdataLicenseHash
    Copy-Item -LiteralPath $licenseAsset -Destination (Join-Path $OutputRoot "LICENSE.tessdata_fast.txt") -Force

    $tesseractExe = Join-Path $OutputRoot "tesseract.exe"
    if (-not (Test-Path -LiteralPath $tesseractExe) -or $dllOwners.Count -lt 1) {
        throw "The locked MSYS2 package set did not produce the Tesseract runtime."
    }
    $versionOutput = (& $tesseractExe --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "(?m)^tesseract\s+$([regex]::Escape($tesseractVersion))(\s|$)") {
        throw "The packaged Tesseract executable did not report version $tesseractVersion. Probe output: $versionOutput"
    }
    $languageOutput = (& $tesseractExe --list-langs --tessdata-dir $tessdataTarget 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $languageOutput -notmatch "\bchi_sim\b" -or $languageOutput -notmatch "\beng\b") {
        throw "The packaged Tesseract models did not pass the language-data self-check."
    }
    $languageOutput | Set-Content -LiteralPath (Join-Path $OutputRoot "OCR-LANGUAGES.txt") -Encoding utf8

    $sbomPackages = @()
    foreach ($package in $runtimePackages) {
        $sourceInfo = $packageSources[$package.name]
        $sbomPackages += [ordered]@{
            name = $package.name
            version = $package.version
            license = $package.license
            licenseChoice = $package.licenseChoice
            officialPage = $package.officialPage
            binaryUrl = $package.binary
            binarySha256 = $package.binarySha256
            sourceUrl = $package.source
            sourceSha256 = if ($sourceInfo) { $sourceInfo.sha256 } else { $null }
            sourcePath = if ($sourceInfo) { $sourceInfo.path } else { $null }
            files = @($packageFiles[$package.name])
        }
    }
    $modelRows = @($models | ForEach-Object {
        [ordered]@{
            path = "tessdata/$($_.Name)"
            repository = "https://github.com/tesseract-ocr/tessdata_fast/tree/$tessdataFastCommit"
            license = "Apache-2.0"
            sha256 = $_.Sha256
        }
    })
    $modelRows += [ordered]@{
        path = "LICENSE.tessdata_fast.txt"
        repository = "https://github.com/tesseract-ocr/tessdata_fast/tree/$tessdataFastCommit"
        license = "Apache-2.0"
        sha256 = $tessdataLicenseHash
    }
    $sbom = [ordered]@{
        schemaVersion = 1
        lockId = $lock.snapshotId
        lockSha256 = $lockHash
        capturedAt = $lock.capturedAt
        rootPackage = $lock.rootPackage
        tesseractVersion = $tesseractVersion
        packages = $sbomPackages
        modelsAndNotices = $modelRows
    }
    $sbomPath = Join-Path $OutputRoot "tesseract-msys2-sbom.json"
    $sbom | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $sbomPath -Encoding utf8

    $noticeRows = @()
    foreach ($package in $runtimePackages) {
        $sourceInfo = $packageSources[$package.name]
        $licenseFiles = @($packageFiles[$package.name] | Where-Object { $_.packagePath -match "^mingw64/share/licenses/" } | ForEach-Object { $_.bundlePath })
        $licenseText = if ($licenseFiles.Count) { $licenseFiles -join ", " } else { "license text is present in the corresponding source archive" }
        $licenseChoice = if ($package.licenseChoice) { " (selected: $($package.licenseChoice))" } else { "" }
        $sourceNote = if ($sourceInfo) {
            "Source archive: $($sourceInfo.path) (SHA-256 $($sourceInfo.sha256))."
        } else {
            "Source archive: $($package.source) (not bundled)."
        }
        $noticeRows += "- **$($package.name) $($package.version)** — license metadata: $($package.license)$licenseChoice. [Package record]($($package.officialPage)); binary archive SHA-256: $($package.binarySha256). License text: $licenseText. $sourceNote"
    }
    $noticeList = $noticeRows -join [Environment]::NewLine
    $notice = @"
Tesseract OCR runtime bundled by FLUKE

This runtime uses the pinned MSYS2 mingw64 package set identified as $($lock.snapshotId). The exact package versions, official package URLs, package archive SHA-256 values, source URLs, redistributed file paths and per-file SHA-256 values are recorded in tesseract-msys2-sbom.json. The build lock is native/scripts/tesseract-msys2-lock.json (SHA-256: $lockHash).

Tesseract itself is version $tesseractVersion and is licensed under Apache-2.0. Its exact MSYS2 source-only package archive, including the upstream source snapshot and MSYS2 build recipe/patches, is included below. Simplified Chinese (chi_sim) and English (eng) models are pinned from tesseract-ocr/tessdata_fast and licensed under Apache-2.0; their hashes and license text are recorded in the SBOM.

The corresponding MSYS2 source-only archives for every bundled package whose published package metadata includes GPL or LGPL terms are included under source/msys2/ and SHA-256 pinned in the SBOM. The GCC runtime package source archive is included; its package metadata declares GPL-3.0-or-later WITH GCC-exception-3.1. This notice reports package metadata and the contents assembled by the build script; it is not a legal opinion.

## Pinned package inventory

$noticeList
"@
    Set-Content -LiteralPath (Join-Path $OutputRoot "THIRD-PARTY-NOTICES.md") -Value $notice -Encoding utf8

    $metadata = [ordered]@{
        id = "tesseract"
        version = $bundleVersion
        executable = "tesseract.exe"
        probeArgument = "--version"
        upstream = $rootPackage.binary
        upstreamSha256 = $rootPackage.binarySha256
        source = "https://github.com/tesseract-ocr/tesseract/tree/5.5.3"
        sourceArchive = $packageSources[$rootPackage.name].path
        sourceSha256 = $packageSources[$rootPackage.name].sha256
        languages = @("chi_sim", "eng")
        models = "tessdata_fast"
        modelLicense = "Apache-2.0"
        msys2Lock = "tesseract-msys2-sbom.json"
        license = "Apache-2.0"
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputRoot "engine.json") -Encoding utf8

    $expectedDllCount = @($runtimePackages | ForEach-Object { $_.runtimeFiles } | Where-Object { $_ -match "^mingw64/bin/[^/]+\.dll$" }).Count
    if ($dllOwners.Count -ne $expectedDllCount) {
        throw "The generated DLL count does not match the pinned package inventory."
    }
    Write-Output "Prepared Tesseract $tesseractVersion from the pinned MSYS2 package set ($($runtimePackages.Count) packages, $($dllOwners.Count) DLLs)."
} catch {
    Remove-GeneratedPath -Path $OutputRoot
    throw
} finally {
    Remove-GeneratedPath -Path $packageStageRoot
}
