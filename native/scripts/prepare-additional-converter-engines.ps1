$ErrorActionPreference = "Stop"

$nativeRoot = Split-Path -Parent $PSScriptRoot
$downloadRoot = Join-Path $nativeRoot "build\converter-engines"
$bundleRoot = Join-Path $nativeRoot "third-party\converter-engines"
New-Item -ItemType Directory -Force -Path $downloadRoot, $bundleRoot | Out-Null

function Get-VerifiedAsset {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Sha256
    )

    if ([IO.Path]::GetFileName($Name) -cne $Name -or $Name -in @(".", "..")) {
        throw "Pinned converter asset name must be a file name: $Name."
    }
    $resolvedDownloadRoot = [IO.Path]::GetFullPath($downloadRoot)
    $downloadPrefix = $resolvedDownloadRoot + [IO.Path]::DirectorySeparatorChar
    $path = [IO.Path]::GetFullPath((Join-Path $resolvedDownloadRoot $Name))
    if (-not $path.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to cache a pinned converter asset outside the build download directory."
    }
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $cachedHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($cachedHash -eq $Sha256) { return $path }
        Remove-Item -LiteralPath $path -Force
    }

    $partialPath = "$path.partial"
    if (Test-Path -LiteralPath $partialPath) { Remove-Item -LiteralPath $partialPath -Force }
    try {
        $null = Invoke-WebRequest -Uri $Uri -OutFile $partialPath -UseBasicParsing -TimeoutSec 300
        $actual = (Get-FileHash -LiteralPath $partialPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $Sha256) {
            throw "SHA-256 mismatch for pinned converter asset $Name."
        }
        Move-Item -LiteralPath $partialPath -Destination $path
        return $path
    } catch {
        if (Test-Path -LiteralPath $partialPath) { Remove-Item -LiteralPath $partialPath -Force }
        throw
    }
}

function Test-CalibrePackageChecksums {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $manifestPath = Join-Path $PackageRoot "FILE-SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $true }
    try {
        $expected = @{}
        foreach ($line in Get-Content -LiteralPath $manifestPath) {
            if ([string]$line -cnotmatch "^([0-9a-f]{64})  (.+)$") { return $false }
            $relativePath = $Matches[2]
            if ($relativePath.StartsWith("/") -or $relativePath.Contains("\") -or
                $relativePath.Contains(":") -or $relativePath -match "(^|/)\.{1,2}(/|$)" -or
                $expected.ContainsKey($relativePath)) {
                return $false
            }
            $expected[$relativePath] = $Matches[1]
        }

        $actualFiles = @(Get-ChildItem -LiteralPath $PackageRoot -Recurse -File -Force |
            Where-Object { [IO.Path]::GetFullPath($_.FullName) -ine [IO.Path]::GetFullPath($manifestPath) })
        if ($expected.Count -ne $actualFiles.Count) { return $false }
        foreach ($file in $actualFiles) {
            $relativePath = $file.FullName.Substring($PackageRoot.Length + 1).Replace("\", "/")
            if (-not $expected.ContainsKey($relativePath)) { return $false }
            if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$relativePath]) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    }
}

function Test-CalibrePackagePayload {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$SourceArchive,
        [Parameter(Mandatory = $true)][string]$SourceSha256,
        [scriptblock]$ProbeCommand
    )

    try {
        $metadata = Get-Content -LiteralPath (Join-Path $PackageRoot "engine.json") -Raw | ConvertFrom-Json
        if ($metadata.id -cne "calibre" -or [string]$metadata.version -cne $Version -or
            [string]$metadata.executable -cne "Calibre/ebook-convert.exe" -or
            [string]$metadata.probeArgument -cne "--version" -or
            [string]$metadata.sourceArchive -cne $SourceArchive -or
            [string]$metadata.sourceSha256 -ine $SourceSha256) {
            return $false
        }
        if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot "THIRD-PARTY-NOTICES.md") -PathType Leaf)) {
            return $false
        }
        if (-not (Test-CalibrePackageChecksums -PackageRoot $PackageRoot)) { return $false }

        $sourcePath = Join-Path $PackageRoot ($SourceArchive.Replace("/", [IO.Path]::DirectorySeparatorChar))
        $executable = Join-Path $PackageRoot "Calibre\ebook-convert.exe"
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceSha256 -or
            -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            return $false
        }

        if ($ProbeCommand) {
            $versionOutput = (& $ProbeCommand $executable | Out-String)
            $probeExitCode = 0
        } else {
            $versionOutput = (& $executable --version 2>&1 | Out-String)
            $probeExitCode = $LASTEXITCODE
        }
        $versionPattern = "(?m)^ebook-convert\.exe\s+\(calibre\s+$([regex]::Escape($Version))\)\s*$"
        return $probeExitCode -eq 0 -and $versionOutput -match $versionPattern
    } catch {
        return $false
    }
}

function Copy-VerifiedCalibreReleasePackage {
    param(
        [Parameter(Mandatory = $true)][string]$ReleaseRoot,
        [Parameter(Mandatory = $true)][string]$DownloadRoot,
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$AssetName,
        [Parameter(Mandatory = $true)][string]$AssetSha256,
        [Parameter(Mandatory = $true)][long]$AssetSizeBytes,
        [Parameter(Mandatory = $true)][string]$SourceArchive,
        [Parameter(Mandatory = $true)][string]$SourceSha256,
        [scriptblock]$ProbeCommand
    )

    $downloadPath = [IO.Path]::GetFullPath($DownloadRoot)
    $packagePath = [IO.Path]::GetFullPath($PackageRoot)
    if (-not $packagePath.StartsWith($downloadPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }

    $createdPackage = $false
    try {
        $manifestPath = Join-Path $ReleaseRoot "fluke-engines.json"
        $assetPath = Join-Path $ReleaseRoot $AssetName
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
            return $false
        }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $entries = @($manifest.components | Where-Object { $_.id -ceq "calibre" })
        if ($manifest.schemaVersion -ne 1 -or $entries.Count -ne 1) { return $false }
        $entry = $entries[0]
        $manifestSize = 0L
        if ([string]$entry.version -cne $Version -or [string]$entry.asset -cne $AssetName -or
            [string]$entry.sha256 -ine $AssetSha256 -or
            -not [long]::TryParse([string]$entry.sizeBytes, [ref]$manifestSize) -or
            $manifestSize -ne $AssetSizeBytes) {
            return $false
        }
        $assetFile = Get-Item -LiteralPath $assetPath
        if ($assetFile.Length -ne $AssetSizeBytes -or
            (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $AssetSha256) {
            return $false
        }

        if (Test-Path -LiteralPath $packagePath) { Remove-Item -LiteralPath $packagePath -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $packagePath | Out-Null
        $createdPackage = $true
        Expand-Archive -LiteralPath $assetPath -DestinationPath $packagePath -Force
        if (-not (Test-CalibrePackagePayload -PackageRoot $packagePath -Version $Version `
            -SourceArchive $SourceArchive -SourceSha256 $SourceSha256 -ProbeCommand $ProbeCommand)) {
            Remove-Item -LiteralPath $packagePath -Recurse -Force
            return $false
        }
        return $true
    } catch {
        if ($createdPackage -and (Test-Path -LiteralPath $packagePath)) {
            Remove-Item -LiteralPath $packagePath -Recurse -Force
        }
        return $false
    }
}

function Add-TesseractNoJbigLibtiffOverride {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $packagePath = [IO.Path]::GetFullPath($PackageRoot)
    $downloadPrefix = [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $packagePath.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to alter a Tesseract package outside the converter-engine build area."
    }

    $vendorRoot = Join-Path $nativeRoot "vendor\tesseract-libtiff-nojbig"
    $manifestPath = Join-Path $vendorRoot "override.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "The pinned no-JBIG libtiff override manifest is missing."
    }
    $override = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $expectedDllHash = "4339d63bceb39630fda804b00f345d217c3893e75ae9618ba93438bf26b49161"
    if ($override.schemaVersion -ne 1 -or $override.binary.sha256 -ne $expectedDllHash -or
        $override.binary.sizeBytes -ne 874122 -or $override.binary.license -ne "MIT") {
        throw "The no-JBIG libtiff override metadata does not match the reviewed build."
    }

    $pinnedInputs = @(
        @{ Path = $override.binary.path; Sha256 = $expectedDllHash },
        @{ Path = $override.sourceArchive.path; Sha256 = $override.sourceArchive.sha256 },
        @{ Path = $override.licenseFile.path; Sha256 = $override.licenseFile.sha256 },
        @{ Path = $override.build.officialRecipe; Sha256 = $override.build.officialRecipeSha256 },
        @{ Path = $override.build.officialPatch; Sha256 = $override.build.officialPatchSha256 },
        @{ Path = $override.build.localPatch; Sha256 = $override.build.localPatchSha256 },
        @{ Path = $override.build.script; Sha256 = $override.build.scriptSha256 }
    )
    foreach ($pinnedAsset in $pinnedInputs) {
        if ([string]$pinnedAsset.Path -notmatch "^[A-Za-z0-9._/-]+$" -or $pinnedAsset.Path.Contains("..")) {
            throw "Unsafe path in the no-JBIG libtiff override manifest."
        }
        $inputPath = Join-Path $vendorRoot ($pinnedAsset.Path.Replace("/", [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $inputPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash -ne $pinnedAsset.Sha256) {
            throw "SHA-256 validation failed for no-JBIG libtiff input $($pinnedAsset.Path)."
        }
    }
    foreach ($dependency in $override.dependencies) {
        if ([string]$dependency.source -notmatch "^source/dependencies/[A-Za-z0-9._+-]+\.src\.tar\.zst$" -or
            [string]$dependency.sourceSha256 -notmatch "^[0-9a-f]{64}$") {
            throw "Invalid dependency source metadata for $($dependency.name)."
        }
        $dependencyPath = Join-Path $vendorRoot ($dependency.source.Replace("/", [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $dependencyPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $dependencyPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sourceSha256) {
            throw "SHA-256 validation failed for dependency source $($dependency.name)."
        }
    }

    $dllTarget = Join-Path $packagePath "libtiff-6.dll"
    if (-not (Test-Path -LiteralPath $dllTarget -PathType Leaf)) {
        throw "The pinned Tesseract runtime did not contain its expected libtiff-6.dll."
    }
    Copy-Item -LiteralPath (Join-Path $vendorRoot "libtiff-6.dll") -Destination $dllTarget -Force
    if ((Get-FileHash -LiteralPath $dllTarget -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedDllHash) {
        throw "The packaged no-JBIG libtiff DLL did not retain its pinned SHA-256."
    }

    $supportTarget = Join-Path $packagePath "source\overrides\libtiff-nojbig"
    New-Item -ItemType Directory -Force -Path $supportTarget | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $vendorRoot -Recurse -File) {
        $relativePath = $file.FullName.Substring($vendorRoot.Length + 1)
        if ($relativePath -eq "libtiff-6.dll") { continue }
        $destination = Join-Path $supportTarget $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
    $overrideLicenseTarget = Join-Path $packagePath "licenses\override-libtiff\LICENSE.md"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $overrideLicenseTarget) | Out-Null
    Copy-Item -LiteralPath (Join-Path $vendorRoot "LICENSE.md") -Destination $overrideLicenseTarget -Force

    $jbigDll = Join-Path $packagePath "libjbig-0.dll"
    if (Test-Path -LiteralPath $jbigDll) { Remove-Item -LiteralPath $jbigDll -Force }
    foreach ($relativePath in @(
        "licenses\msys2\mingw-w64-x86_64-jbigkit",
        "source\msys2\mingw-w64-jbigkit-2.1-6.src.tar.zst"
    )) {
        $target = Join-Path $packagePath $relativePath
        if (Test-Path -LiteralPath $target) {
            $resolvedTarget = [IO.Path]::GetFullPath($target)
            if (-not $resolvedTarget.StartsWith($packagePath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove a generated JBIG payload outside the Tesseract package."
            }
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        }
    }

    $sourcePrefix = "source/overrides/libtiff-nojbig/"
    $tiffSourcePath = $sourcePrefix + $override.sourceArchive.path
    $sbomPath = Join-Path $packagePath "tesseract-msys2-sbom.json"
    $sbom = Get-Content -LiteralPath $sbomPath -Raw | ConvertFrom-Json
    $sbom.packages = @($sbom.packages | Where-Object { $_.name -ne "mingw-w64-x86_64-jbigkit" })
    $tiffPackage = @($sbom.packages | Where-Object { $_.name -eq "mingw-w64-x86_64-libtiff" })
    if ($tiffPackage.Count -ne 1) { throw "The Tesseract SBOM has no unique libtiff package row." }
    $tiffPackage = $tiffPackage[0]
    $tiffPackage.files = @($tiffPackage.files | Where-Object { $_.packagePath -ne "mingw64/bin/libtiff-6.dll" })
    $tiffPackage.sourceSha256 = $override.sourceArchive.sha256
    $tiffPackage.sourcePath = $tiffSourcePath
    foreach ($dependency in $override.dependencies) {
        $dependencyRow = @($sbom.packages | Where-Object { $_.name -eq $dependency.name })
        if ($dependencyRow.Count -ne 1) { throw "The Tesseract SBOM has no unique dependency row for $($dependency.name)." }
        $dependencyRow[0].sourceSha256 = $dependency.sourceSha256
        $dependencyRow[0].sourcePath = $sourcePrefix + $dependency.source
    }
    $overrideRow = [ordered]@{
        name = $override.name
        version = $override.version
        license = $override.binary.license
        binaryUrl = "native/vendor/tesseract-libtiff-nojbig/$($override.binary.path)"
        binarySha256 = $expectedDllHash
        sourceUrl = $override.sourceArchive.url
        sourceSha256 = $override.sourceArchive.sha256
        sourcePath = $tiffSourcePath
        files = @([ordered]@{
            packagePath = "native/vendor/tesseract-libtiff-nojbig/$($override.binary.path)"
            bundlePath = "libtiff-6.dll"
            sha256 = $expectedDllHash
        }, [ordered]@{
            packagePath = "native/vendor/tesseract-libtiff-nojbig/$($override.licenseFile.path)"
            bundlePath = "licenses/override-libtiff/LICENSE.md"
            sha256 = $override.licenseFile.sha256
        })
        imports = @($override.imports)
        disabledCodec = "TIFF JBIG compression"
        buildRecipe = $sourcePrefix + $override.build.officialRecipe
        patches = @(
            $sourcePrefix + $override.build.localPatch
            $sourcePrefix + $override.build.officialPatch
        )
        configureFlags = @($override.build.configureFlags)
        dependencies = @($override.dependencies | ForEach-Object {
            [ordered]@{
                name = $_.name
                version = $_.version
                license = $_.license
                sourcePath = $sourcePrefix + $_.source
                sourceSha256 = $_.sourceSha256
            }
        })
    }
    $sbom.packages = @($sbom.packages) + @($overrideRow)
    $sbom | Add-Member -NotePropertyName "removedRuntimePackages" -NotePropertyValue @(
        [ordered]@{ name = "mingw-w64-x86_64-jbigkit"; reason = "The pinned no-JBIG libtiff override has no libjbig DLL import." }
    ) -Force
    $sbom | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $sbomPath -Encoding utf8

    $noticePath = Join-Path $packagePath "THIRD-PARTY-NOTICES.md"
    $notice = Get-Content -LiteralPath $noticePath -Raw
    $notice = [regex]::Replace($notice, "(?m)^- \*\*mingw-w64-x86_64-jbigkit\b[^\r\n]*(?:\r?\n|$)", "")
    $notice = $notice.Replace(
        "Source archive: $($override.sourceArchive.url) (not bundled).",
        "Source archive: $tiffSourcePath (SHA-256 $($override.sourceArchive.sha256))."
    )
    foreach ($dependency in $override.dependencies) {
        $notice = $notice.Replace(
            "Source archive: $($dependency.sourceUrl) (not bundled).",
            "Source archive: $sourcePrefix$($dependency.source) (SHA-256 $($dependency.sourceSha256))."
        )
    }
    $notice += @"

## FLUKE libtiff override

FLUKE replaces the upstream MSYS2 libtiff 4.7.2-1 C DLL with a hash-pinned build that disables the TIFF JBIG codec. The build input is MIT-licensed libtiff 4.7.2-1; its source archive, official PKGBUILD and patch, local JBIG-disable patch, configure flags, build command, dependency source archives and hashes are included under source/overrides/libtiff-nojbig/. The matching license text is licenses/override-libtiff/LICENSE.md. Dependency license texts remain under licenses/msys2/.

The runtime no longer ships libjbig-0.dll or the JBIGKit GPL license/source package. TIFF files that require JBIG decompression are unsupported by this override. Other bundled TIFF codecs and Tesseract OCR were smoke-checked against the pinned DLL.
"@
    Set-Content -LiteralPath $noticePath -Value $notice -Encoding utf8

    $metadataPath = Join-Path $packagePath "engine.json"
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    $metadata.version = "5.5.3.20260929.2"
    $metadata | Add-Member -NotePropertyName "libtiffOverride" -NotePropertyValue ([ordered]@{
        path = "libtiff-6.dll"
        sha256 = $expectedDllHash
        version = $override.version
        license = $override.binary.license
        sourceArchive = $tiffSourcePath
        sourceSha256 = $override.sourceArchive.sha256
        buildNotes = $sourcePrefix + "BUILDING.md"
        disabledCodec = "TIFF JBIG compression"
    }) -Force
    $metadata | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $metadataPath -Encoding utf8

    $tesseractExe = Join-Path $packagePath "tesseract.exe"
    $versionOutput = (& $tesseractExe --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "(?m)^tesseract\s+5\.5\.3(\s|$)" -or
        $versionOutput -notmatch "libtiff 4\.7\.2") {
        throw "The Tesseract runtime failed its version/import smoke after replacing libtiff. Probe output: $versionOutput"
    }
    $languageOutput = (& $tesseractExe --list-langs --tessdata-dir (Join-Path $packagePath "tessdata") 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $languageOutput -notmatch "\bchi_sim\b" -or $languageOutput -notmatch "\beng\b") {
        throw "The Tesseract language-data smoke failed after replacing libtiff. Probe output: $languageOutput"
    }
}

$tesseractPackage = Join-Path $downloadRoot "package-tesseract"
& (Join-Path $PSScriptRoot "prepare-msys2-tesseract.ps1") -DownloadRoot $downloadRoot -OutputRoot $tesseractPackage
Add-TesseractNoJbigLibtiffOverride -PackageRoot $tesseractPackage
$calibreVersion = "9.15.0"
$calibreInstallerName = "calibre-portable-installer-$calibreVersion.exe"
$calibreInstallerUri = "https://download.calibre-ebook.com/$calibreVersion/$calibreInstallerName"
$calibreInstallerHash = "55a8c89bc0739a2dc6d496742ea625fccc6dfdec1413eb805805a28e7227536c"
$calibreSourceName = "calibre-$calibreVersion.tar.xz"
$calibreSourceUri = "https://download.calibre-ebook.com/$calibreVersion/$calibreSourceName"
$calibreSourceHash = "9f02d36decaf46b176a1bef74349232508bcc2b4b06d1662bbd1fd426c57d559"
$calibrePackage = Join-Path $downloadRoot "package-calibre"
$calibreReleaseRoot = Join-Path $nativeRoot "release\engine-updates"
$calibreReleaseAssetName = "fluke-engine-calibre-win-x64-$calibreVersion.zip"
$calibreReleaseAssetSha256 = "c45eeb4620ccec80e0bd14969035abb3457bf13d88b532a45f78496aa7fc36e4"
$calibreReleaseAssetSizeBytes = 335776391L
$calibreSourceArchive = "source/$calibreSourceName"
$licenseExtractRoot = $null
$calibreReused = Copy-VerifiedCalibreReleasePackage `
    -ReleaseRoot $calibreReleaseRoot `
    -DownloadRoot $downloadRoot `
    -PackageRoot $calibrePackage `
    -Version $calibreVersion `
    -AssetName $calibreReleaseAssetName `
    -AssetSha256 $calibreReleaseAssetSha256 `
    -AssetSizeBytes $calibreReleaseAssetSizeBytes `
    -SourceArchive $calibreSourceArchive `
    -SourceSha256 $calibreSourceHash

if ($calibreReused) {
    Write-Output "Reused the verified Calibre $calibreVersion package from release/engine-updates."
} else {
    $calibreInstaller = Get-VerifiedAsset -Name $calibreInstallerName -Uri $calibreInstallerUri -Sha256 $calibreInstallerHash
    $calibreSource = Get-VerifiedAsset -Name $calibreSourceName -Uri $calibreSourceUri -Sha256 $calibreSourceHash
if (Test-Path -LiteralPath $calibrePackage) {
    $resolvedPackage = [IO.Path]::GetFullPath($calibrePackage)
    $downloadPrefix = [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedPackage.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a Calibre staging directory outside the download root."
    }
    Remove-Item -LiteralPath $resolvedPackage -Recurse -Force
}
$calibreRuntime = Join-Path $calibrePackage "Calibre"
New-Item -ItemType Directory -Force -Path $calibrePackage, (Join-Path $calibrePackage "source") | Out-Null
$substExe = Join-Path $env:SystemRoot "System32\subst.exe"
$occupiedDrives = @((Get-PSDrive -PSProvider FileSystem | ForEach-Object Name) + (Get-CimInstance Win32_LogicalDisk | ForEach-Object DeviceID | ForEach-Object { $_.TrimEnd(':') }))
$driveLetter = @("Z", "Y", "X", "W", "V", "U", "T", "S", "R", "Q") | Where-Object { $_ -notin $occupiedDrives } | Select-Object -First 1
if (-not $driveLetter) {
    throw "No temporary drive letter is available to stage the Calibre portable bundle."
}
$stageDrive = "{0}:" -f $driveLetter
$substCreated = $false
$calibreStageRoot = $null
try {
    & $substExe $stageDrive $env:TEMP
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create a temporary drive for the Calibre portable installer."
    }
    $substCreated = $true
    $calibreStageToken = "C9$([Guid]::NewGuid().ToString('N').Substring(0, 6))"
    $calibreStageRoot = "$stageDrive\$calibreStageToken"
    $calibreCleanupRoot = Join-Path $env:TEMP $calibreStageToken
    $portablePath = Join-Path $calibreStageRoot "Calibre Portable"
    if ($portablePath.Length -ge 59) {
        throw "The Calibre portable staging path exceeds the official installer's path limit."
    }
    $calibreInstall = Start-Process -FilePath $calibreInstaller -ArgumentList @($calibreStageRoot) -Wait -PassThru
    $portableRuntime = Join-Path $portablePath "Calibre"
    if ($calibreInstall.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $portableRuntime "ebook-convert.exe"))) {
        throw "The official Calibre portable installer did not produce ebook-convert.exe."
    }
    Copy-Item -LiteralPath $portableRuntime -Destination $calibrePackage -Recurse
    Copy-Item -LiteralPath $calibreSource -Destination (Join-Path $calibrePackage "source\$calibreSourceName")
    $calibreExe = Join-Path $calibreRuntime "ebook-convert.exe"
    $calibreVersionOutput = (& $calibreExe --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $calibreVersionOutput -notmatch [regex]::Escape($calibreVersion)) {
        throw "The packaged Calibre executable did not report the pinned version."
    }

    $licenseExtractRoot = Join-Path $downloadRoot "calibre-source-license"
    if (Test-Path -LiteralPath $licenseExtractRoot) {
        $resolvedLicenseRoot = [IO.Path]::GetFullPath($licenseExtractRoot)
        $downloadPrefix = [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedLicenseRoot.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a Calibre source staging directory outside the download root."
        }
        Remove-Item -LiteralPath $resolvedLicenseRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $licenseExtractRoot | Out-Null
    & tar.exe -xJf $calibreSource -C $licenseExtractRoot "calibre-$calibreVersion/LICENSE"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not extract the Calibre GPLv3 license text from its source archive."
    }
    $calibreLicense = Join-Path $licenseExtractRoot "calibre-$calibreVersion\LICENSE"
    if (-not (Test-Path -LiteralPath $calibreLicense)) {
        throw "The Calibre source archive did not contain its expected LICENSE file."
    }
    Copy-Item -LiteralPath $calibreLicense -Destination (Join-Path $calibrePackage "COPYING.GPLv3")

    & tar.exe -xJf $calibreSource -C $licenseExtractRoot "calibre-$calibreVersion/COPYRIGHT"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not extract the Calibre third-party copyright inventory from its source archive."
    }
    $calibreCopyright = Join-Path $licenseExtractRoot "calibre-$calibreVersion\COPYRIGHT"
    if (-not (Test-Path -LiteralPath $calibreCopyright)) {
        throw "The Calibre source archive did not contain its expected COPYRIGHT file."
    }
    Copy-Item -LiteralPath $calibreCopyright -Destination (Join-Path $calibrePackage "COPYRIGHT")

    $metadata = [ordered]@{
        id = "calibre"
        version = $calibreVersion
        executable = "Calibre/ebook-convert.exe"
        probeArgument = "--version"
        upstream = $calibreInstallerUri
        upstreamSha256 = $calibreInstallerHash
        source = $calibreSourceUri
        sourceArchive = "source/$calibreSourceName"
        sourceSha256 = $calibreSourceHash
        license = "GPL-3.0-only"
    }
    $metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $calibrePackage "engine.json") -Encoding utf8
    $notice = @"
Calibre command-line conversion engine bundled by FLUKE

This component includes the Calibre $calibreVersion portable Windows runtime, copied from the official portable download. The portable build targets Windows 10 or later. FLUKE invokes ebook-convert.exe as a separate process.

The upstream Calibre project is licensed under GNU GPL v3. COPYING.GPLv3 contains the license text. COPYRIGHT is copied from the exact upstream source archive and contains its copyright and source-tree third-party license inventory. These files identify Calibre's project/source licensing; they do not establish the complete license inventory for every precompiled dependency bundled in the portable runtime. FLUKE has not independently verified every such dependency.

The exact upstream Calibre $calibreVersion source archive is included at source/$calibreSourceName (SHA-256: $calibreSourceHash). It is the corresponding source archive for this version; do not substitute another release's source.

Portable installer: $calibreInstallerUri
Portable installer SHA-256: $calibreInstallerHash
Upstream license information: https://manual.calibre-ebook.com/faq.html
Upstream source-tree copyright inventory: https://github.com/kovidgoyal/calibre/blob/v9.15.0/COPYRIGHT

FILE-SHA256SUMS.txt lists the SHA-256 of every file in this component package except FILE-SHA256SUMS.txt itself. Each line contains a lowercase SHA-256, two spaces, and a package-relative path using forward slashes. The published engine ZIP SHA-256 covers the manifest itself.

The Calibre runtime occupies approximately 663 MB uncompressed. FLUKE distributes the official portable runtime and corresponding source archive; the dependency inventory remains subject to independent verification.
"@
    Set-Content -LiteralPath (Join-Path $calibrePackage "THIRD-PARTY-NOTICES.md") -Value $notice -Encoding utf8

    $fileManifest = Join-Path $calibrePackage "FILE-SHA256SUMS.txt"
    $fileManifestLines = Get-ChildItem -LiteralPath $calibrePackage -Recurse -File |
        Where-Object { $_.FullName -ne $fileManifest } |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($calibrePackage.Length + 1).Replace("\", "/")
            $fileHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "{0}  {1}" -f $fileHash, $relativePath
        }
    Set-Content -LiteralPath $fileManifest -Value $fileManifestLines -Encoding utf8
} finally {
    if ($substCreated) {
        & $substExe $stageDrive /D
        if ($LASTEXITCODE -ne 0) {
            throw "Could not remove the temporary Calibre staging drive."
        }
    }
    if ($calibreCleanupRoot -and (Test-Path -LiteralPath $calibreCleanupRoot)) {
        $resolvedCalibreStage = [IO.Path]::GetFullPath($calibreCleanupRoot)
        $tempPrefix = [IO.Path]::GetFullPath($env:TEMP) + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedCalibreStage.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a Calibre staging directory outside the system temporary folder."
        }
        Remove-Item -LiteralPath $resolvedCalibreStage -Recurse -Force
    }
}
}

foreach ($entry in @(
    @{ Id = "tesseract"; Package = $tesseractPackage },
    @{ Id = "calibre"; Package = $calibrePackage }
)) {
    $componentRoot = Join-Path $bundleRoot $entry.Id
    $resolvedPackage = [IO.Path]::GetFullPath($entry.Package)
    $resolvedDownloadRoot = [IO.Path]::GetFullPath($downloadRoot)
    if (-not $resolvedPackage.StartsWith($resolvedDownloadRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to publish an engine package from outside the converter-engine build area."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedPackage "THIRD-PARTY-NOTICES.md")) -or
        -not (Get-ChildItem -LiteralPath (Join-Path $resolvedPackage "source") -Recurse -File -ErrorAction SilentlyContinue)) {
        throw "The staged $($entry.Id) component is missing its notice or source archive."
    }
    if (Test-Path -LiteralPath $componentRoot) {
        $resolvedComponent = [IO.Path]::GetFullPath($componentRoot)
        $resolvedBundleRoot = [IO.Path]::GetFullPath($bundleRoot)
        if (-not $resolvedComponent.StartsWith($resolvedBundleRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to replace an engine outside third-party/converter-engines."
        }
        Remove-Item -LiteralPath $resolvedComponent -Recurse -Force
    }
    Move-Item -LiteralPath $resolvedPackage -Destination $componentRoot
    Write-Output "Prepared $($entry.Id) in third-party/converter-engines/$($entry.Id)."
}

if ($licenseExtractRoot -and (Test-Path -LiteralPath $licenseExtractRoot)) {
    $resolvedLicenseRoot = [IO.Path]::GetFullPath($licenseExtractRoot)
    $downloadPrefix = [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedLicenseRoot.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a Calibre source staging directory outside the download root."
    }
    Remove-Item -LiteralPath $resolvedLicenseRoot -Recurse -Force
}
