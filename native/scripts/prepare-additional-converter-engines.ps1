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

    $path = Join-Path $downloadRoot $Name
    if (-not (Test-Path -LiteralPath $path)) {
        $null = Invoke-WebRequest -Uri $Uri -OutFile $path -UseBasicParsing -TimeoutSec 300
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256) {
        throw "SHA-256 mismatch for pinned converter asset $Name."
    }
    return $path
}

$tesseractVersion = "5.5.3.20260724"
$tesseractInstallerName = "tesseract-ocr-w64-setup-$tesseractVersion.exe"
$tesseractInstallerUri = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/$tesseractInstallerName"
$tesseractInstallerHash = "bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4"
$tesseractInstaller = Get-VerifiedAsset -Name $tesseractInstallerName -Uri $tesseractInstallerUri -Sha256 $tesseractInstallerHash

$tesseractSourceName = "tesseract-5.5.3.tar.gz"
$tesseractSourceUri = "https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/refs/tags/5.5.3"
$tesseractSourceHash = "9218e62793116d42a9f6d14cd9348518b27f382096eea3d0f2d1a24616bb5884"
$tesseractSource = Get-VerifiedAsset -Name $tesseractSourceName -Uri $tesseractSourceUri -Sha256 $tesseractSourceHash

$tessdataFastBase = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main"
$chiSimName = "chi_sim.traineddata"
$engName = "eng.traineddata"
$chiSimHash = "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730"
$engHash = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
$tessdataLicenseHash = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
$chiSimPath = Get-VerifiedAsset -Name $chiSimName -Uri "$tessdataFastBase/$chiSimName" -Sha256 $chiSimHash
$engPath = Get-VerifiedAsset -Name $engName -Uri "$tessdataFastBase/$engName" -Sha256 $engHash
$tessdataLicense = Get-VerifiedAsset -Name "tessdata_fast-LICENSE" -Uri "$tessdataFastBase/LICENSE" -Sha256 $tessdataLicenseHash

$tesseractStageToken = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$tesseractStage = if ($env:FLUKE_TESSERACT_RUNTIME) {
    [IO.Path]::GetFullPath($env:FLUKE_TESSERACT_RUNTIME)
} else {
    Join-Path $env:TEMP "FLUKE-Engine-tesseract-5.5.3"
}
$tesseractStageCreated = $false
$tesseractRegisteredPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$tesseractRegistrations = @(Get-ItemProperty -Path $tesseractRegisteredPaths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match "Tesseract" })
if (-not (Test-Path -LiteralPath $tesseractStage) -and $tesseractRegistrations.Count -gt 0 -and -not $env:FLUKE_TESSERACT_RUNTIME) {
    throw "A Tesseract installation is already registered. Set FLUKE_TESSERACT_RUNTIME to an extracted 5.5.3 runtime so the build does not modify it."
}
$tesseractPackage = Join-Path $downloadRoot "package-tesseract"
foreach ($temporaryPath in @($tesseractPackage)) {
    if (Test-Path -LiteralPath $temporaryPath) {
        $resolved = [IO.Path]::GetFullPath($temporaryPath)
        $allowed = if ($temporaryPath -eq $tesseractStage) {
            [IO.Path]::GetFullPath($env:TEMP) + [IO.Path]::DirectorySeparatorChar
        } else {
            [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
        }
        if (-not $resolved.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a Tesseract staging path outside its temporary root."
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $tesseractPackage | Out-Null
try {
    if (-not (Test-Path -LiteralPath (Join-Path $tesseractStage "tesseract.exe"))) {
        $tesseractStage = Join-Path $env:TEMP "T5$tesseractStageToken"
        if ($tesseractStage.Contains(" ")) {
            throw "Tesseract silent installation requires a temporary path without spaces."
        }
        $installerProcess = Start-Process -FilePath $tesseractInstaller -ArgumentList "/S /D=$tesseractStage" -Wait -PassThru
        $tesseractStageCreated = $true
    }
    $tesseractExe = Join-Path $tesseractStage "tesseract.exe"
    if (($installerProcess -and $installerProcess.ExitCode -ne 0) -or -not (Test-Path -LiteralPath $tesseractExe)) {
        throw "The pinned Tesseract installer did not produce tesseract.exe."
    }
    $versionOutput = (& $tesseractExe --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch [regex]::Escape($tesseractVersion)) {
        throw "The staged Tesseract executable did not report the pinned version."
    }

    Get-ChildItem -LiteralPath $tesseractStage -Filter "*.dll" -File | Copy-Item -Destination $tesseractPackage
    Copy-Item -LiteralPath $tesseractExe -Destination $tesseractPackage
    $tessdataSource = Join-Path $tesseractStage "tessdata"
    $tessdataTarget = Join-Path $tesseractPackage "tessdata"
    if (-not (Test-Path -LiteralPath (Join-Path $tessdataSource "configs"))) {
        throw "The Tesseract installation is missing its tessdata configuration files."
    }
    Copy-Item -LiteralPath $tessdataSource -Destination $tessdataTarget -Recurse
    Copy-Item -LiteralPath $engPath -Destination (Join-Path $tessdataTarget $engName) -Force
    Copy-Item -LiteralPath $chiSimPath -Destination (Join-Path $tessdataTarget $chiSimName)
    Copy-Item -LiteralPath (Join-Path $tesseractStage "doc\LICENSE") -Destination (Join-Path $tesseractPackage "LICENSE.Tesseract.txt")
    Copy-Item -LiteralPath (Join-Path $tesseractStage "doc\AUTHORS") -Destination (Join-Path $tesseractPackage "AUTHORS.Tesseract.txt")
    Copy-Item -LiteralPath $tessdataLicense -Destination (Join-Path $tesseractPackage "LICENSE.tessdata_fast.txt")
    New-Item -ItemType Directory -Force -Path (Join-Path $tesseractPackage "source") | Out-Null
    Copy-Item -LiteralPath $tesseractSource -Destination (Join-Path $tesseractPackage "source\$tesseractSourceName")

    $languageOutput = (& $tesseractExe --list-langs --tessdata-dir $tessdataTarget 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $languageOutput -notmatch "chi_sim" -or $languageOutput -notmatch "eng") {
        throw "The packaged Tesseract models did not pass the language-data self-check."
    }
    $languageOutput | Set-Content -LiteralPath (Join-Path $tesseractPackage "OCR-LANGUAGES.txt") -Encoding utf8

    $metadata = [ordered]@{
        id = "tesseract"
        version = $tesseractVersion
        executable = "tesseract.exe"
        probeArgument = "--version"
        upstream = $tesseractInstallerUri
        upstreamSha256 = $tesseractInstallerHash
        source = "https://github.com/tesseract-ocr/tesseract/tree/5.5.3"
        sourceArchive = "source/$tesseractSourceName"
        sourceSha256 = $tesseractSourceHash
        languages = @("chi_sim", "eng")
        models = "tessdata_fast"
        modelLicense = "Apache-2.0"
        license = "Apache-2.0"
    }
    $metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $tesseractPackage "engine.json") -Encoding utf8

    $dllNames = (Get-ChildItem -LiteralPath $tesseractPackage -Filter "*.dll" -File | Sort-Object Name | ForEach-Object Name) -join "`n"
    $notice = @"
Tesseract OCR engine bundled by FLUKE

This component includes Tesseract $tesseractVersion from the UB Mannheim Windows x64 installer, with the upstream Apache-2.0 license and authors in LICENSE.Tesseract.txt and AUTHORS.Tesseract.txt. The exact Tesseract source snapshot is included at source/$tesseractSourceName.

The default language models are the Simplified Chinese (chi_sim) and English (eng) integer models from the tesseract-ocr/tessdata_fast repository. They are licensed under Apache-2.0; the repository license text is included as LICENSE.tessdata_fast.txt. Model SHA-256 values: chi_sim=$chiSimHash; eng=$engHash.

Installer provenance: $tesseractInstallerUri
Installer SHA-256: $tesseractInstallerHash
The installer supplies the Windows runtime DLLs listed below. Their original distribution package and project notices are available from the installer publisher; verify each dependency's license and corresponding source before redistributing a modified or repackaged binary set.

Bundled DLL inventory:
$dllNames
"@
    Set-Content -LiteralPath (Join-Path $tesseractPackage "THIRD-PARTY-NOTICES.md") -Value $notice -Encoding utf8
} finally {
    if ($tesseractStageCreated -and (Test-Path -LiteralPath $tesseractStage)) {
        $tesseractUninstaller = Join-Path $tesseractStage "tesseract-uninstall.exe"
        if (Test-Path -LiteralPath $tesseractUninstaller) {
            $uninstallProcess = Start-Process -FilePath $tesseractUninstaller -ArgumentList "/S" -Wait -PassThru
            if ($uninstallProcess.ExitCode -ne 0) {
                throw "The temporary Tesseract installation could not be uninstalled cleanly."
            }
        }
        $resolvedStage = [IO.Path]::GetFullPath($tesseractStage)
        $tempPrefix = [IO.Path]::GetFullPath($env:TEMP) + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedStage.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a Tesseract staging directory outside the system temporary folder."
        }
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}

$calibreVersion = "9.15.0"
$calibreInstallerName = "calibre-portable-installer-$calibreVersion.exe"
$calibreInstallerUri = "https://download.calibre-ebook.com/$calibreVersion/$calibreInstallerName"
$calibreInstallerHash = "55a8c89bc0739a2dc6d496742ea625fccc6dfdec1413eb805805a28e7227536c"
$calibreInstaller = Get-VerifiedAsset -Name $calibreInstallerName -Uri $calibreInstallerUri -Sha256 $calibreInstallerHash
$calibreSourceName = "calibre-$calibreVersion.tar.xz"
$calibreSourceUri = "https://download.calibre-ebook.com/$calibreVersion/$calibreSourceName"
$calibreSourceHash = "9f02d36decaf46b176a1bef74349232508bcc2b4b06d1662bbd1fd426c57d559"
$calibreSource = Get-VerifiedAsset -Name $calibreSourceName -Uri $calibreSourceUri -Sha256 $calibreSourceHash

$calibrePackage = Join-Path $downloadRoot "package-calibre"
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

This component includes the Calibre $calibreVersion portable Windows runtime. The portable download is self-contained and targets Windows 10 or later. FLUKE invokes ebook-convert.exe as a separate process and does not link to Calibre libraries.

Calibre is licensed under GPL-3.0-only. COPYING.GPLv3 contains the upstream license text. The exact upstream Calibre source archive is included at source/$calibreSourceName (SHA-256: $calibreSourceHash).

Portable installer: $calibreInstallerUri
Portable installer SHA-256: $calibreInstallerHash
The Calibre runtime occupies approximately 663 MB uncompressed. Its bundled third-party notices and licenses, where supplied by Calibre, remain within the Calibre runtime directory.
"@
    Set-Content -LiteralPath (Join-Path $calibrePackage "THIRD-PARTY-NOTICES.md") -Value $notice -Encoding utf8
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
        -not (Get-ChildItem -LiteralPath (Join-Path $resolvedPackage "source") -File -ErrorAction SilentlyContinue)) {
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

if (Test-Path -LiteralPath $licenseExtractRoot) {
    $resolvedLicenseRoot = [IO.Path]::GetFullPath($licenseExtractRoot)
    $downloadPrefix = [IO.Path]::GetFullPath($downloadRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedLicenseRoot.StartsWith($downloadPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a Calibre source staging directory outside the download root."
    }
    Remove-Item -LiteralPath $resolvedLicenseRoot -Recurse -Force
}
