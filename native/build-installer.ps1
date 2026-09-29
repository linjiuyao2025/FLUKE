param(
    [string]$ReleaseTag
)

$ErrorActionPreference = "Stop"

$nativeRoot = $PSScriptRoot
$projectFile = Join-Path $nativeRoot "pyproject.toml"
$projectText = Get-Content -LiteralPath $projectFile -Raw
$versionMatch = [regex]::Match($projectText, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the FLUKE version from pyproject.toml."
}
$version = $versionMatch.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($ReleaseTag)) {
    $ReleaseTag = "native-v$version-preview.1"
}
$python = Join-Path $nativeRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python environment not found. Create .venv and install the project with: pip install -e ".[build]"'
}

$innoCompiler = $null
$command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($command) {
    $innoCompiler = $command.Source
}
if (-not $innoCompiler) {
    $candidatePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidatePaths) {
        if (Test-Path -LiteralPath $candidate) {
            $innoCompiler = $candidate
            break
        }
    }
}
if (-not $innoCompiler) {
    throw "Inno Setup 6.7 or newer is required to compile the FLUKE installer."
}

Push-Location $nativeRoot
try {
    & (Join-Path $nativeRoot "installer\build-wizard-image.ps1")

    & (Join-Path $nativeRoot "scripts\build-ofd-engine.ps1")
    if (-not (Test-Path -LiteralPath (Join-Path $nativeRoot "engine\ofd\build\bridge.jar"))) {
        throw "The bundled OFD engine build completed without producing its bridge."
    }

    & (Join-Path $nativeRoot "scripts\prepare-converter-engines.ps1")
    & (Join-Path $nativeRoot "scripts\prepare-additional-converter-engines.ps1")

    & $python -m PyInstaller --clean --noconfirm "FLUKE.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $internalOutput = Join-Path $nativeRoot "dist\FLUKE\_internal"
    if (-not (Test-Path -LiteralPath $internalOutput -PathType Container)) {
        throw "PyInstaller completed without producing dist\FLUKE\_internal."
    }
    $engineSource = Join-Path $nativeRoot "third-party\converter-engines"
    $engineOutput = Join-Path $internalOutput "engines"
    if (-not (Test-Path -LiteralPath $engineSource -PathType Container)) {
        throw "Prepared converter engines were not found at third-party\converter-engines."
    }
    if (Test-Path -LiteralPath $engineOutput) {
        throw "Refusing to merge converter engines into an existing build output: $engineOutput"
    }
    Copy-Item -LiteralPath $engineSource -Destination $engineOutput -Recurse

    $requiredEngineFiles = @(
        (Join-Path $engineOutput "ffmpeg\bin\ffmpeg.exe"),
        (Join-Path $engineOutput "tesseract\tesseract.exe"),
        (Join-Path $engineOutput "calibre\Calibre\ebook-convert.exe")
    )
    foreach ($engineFile in $requiredEngineFiles) {
        if (-not (Test-Path -LiteralPath $engineFile -PathType Leaf)) {
            throw "A required converter engine is missing from dist\FLUKE\_internal\engines: $engineFile"
        }
    }

    $pythonRuntimeInfo = @(& $python -c "import pathlib, sys; print('python%d%d.dll' % sys.version_info[:2]); print(sys.base_prefix); print(pathlib.Path(sys.base_prefix, 'python3.dll'))")
    if ($LASTEXITCODE -ne 0 -or $pythonRuntimeInfo.Count -ne 3) {
        throw "Could not determine the Python runtime DLL from the build virtual environment."
    }
    $pythonRuntimeName = $pythonRuntimeInfo[0].Trim()
    $pythonStableRuntimeSource = $pythonRuntimeInfo[2].Trim()
    $pythonRuntime = Join-Path $internalOutput $pythonRuntimeName.Trim()
    if (-not (Test-Path -LiteralPath $pythonRuntime -PathType Leaf)) {
        throw "The expected Python runtime DLL $pythonRuntimeName is missing from dist\FLUKE\_internal."
    }
    $pythonStableRuntime = Join-Path $internalOutput "python3.dll"
    if (-not (Test-Path -LiteralPath $pythonStableRuntimeSource -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pythonStableRuntime -PathType Leaf)) {
        throw "The Python stable-ABI DLL python3.dll is missing from the build runtime."
    }
    $stableSourceHash = (Get-FileHash -LiteralPath $pythonStableRuntimeSource -Algorithm SHA256).Hash
    $stableOutputHash = (Get-FileHash -LiteralPath $pythonStableRuntime -Algorithm SHA256).Hash
    if ($stableSourceHash -ne $stableOutputHash) {
        throw "The shared python3.dll does not match the build virtual environment."
    }
    $unexpectedPythonRuntimes = @(
        Get-ChildItem -LiteralPath $internalOutput -File -Filter "python3*.dll" |
            Where-Object { $_.Name -notin @($pythonRuntimeName, "python3.dll") }
    )
    if ($unexpectedPythonRuntimes.Count -gt 0) {
        $names = ($unexpectedPythonRuntimes | ForEach-Object Name) -join ", "
        throw "Unexpected Python runtime DLLs leaked into the shared application runtime: $names"
    }

    $appExecutable = Join-Path $nativeRoot "dist\FLUKE\FLUKE.exe"
    if (-not (Test-Path -LiteralPath $appExecutable)) {
        throw "PyInstaller completed without producing dist\FLUKE\FLUKE.exe."
    }

    $converterExecutable = Join-Path $nativeRoot "dist\FLUKE\FLUKE-convert.exe"
    if (-not (Test-Path -LiteralPath $converterExecutable)) {
        throw "PyInstaller completed without producing dist\FLUKE\FLUKE-convert.exe."
    }

    & (Join-Path $nativeRoot "scripts\package-converter-engine-updates.ps1") -Version $version -ReleaseTag $ReleaseTag

    $installerScript = Join-Path $nativeRoot "installer\FLUKE.iss"
    & $innoCompiler "/DAppVersion=$version" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$installer = Join-Path $nativeRoot "release\FLUKE-$version-Setup.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "The FLUKE installer was not created at the expected output path."
}
& (Join-Path $nativeRoot "scripts\verify-release-artifacts.ps1") -Version $version -ReleaseTag $ReleaseTag
Get-Item -LiteralPath $installer | Select-Object FullName, Length, LastWriteTime
