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

$tesseractPackage = Join-Path $downloadRoot "package-tesseract"
& (Join-Path $PSScriptRoot "prepare-msys2-tesseract.ps1") -DownloadRoot $downloadRoot -OutputRoot $tesseractPackage
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
