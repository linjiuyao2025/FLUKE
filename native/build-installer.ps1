$ErrorActionPreference = "Stop"

$nativeRoot = $PSScriptRoot
$projectFile = Join-Path $nativeRoot "pyproject.toml"
$projectText = Get-Content -LiteralPath $projectFile -Raw
$versionMatch = [regex]::Match($projectText, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the FLUKE version from pyproject.toml."
}
$version = $versionMatch.Groups[1].Value
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

    $appExecutable = Join-Path $nativeRoot "dist\FLUKE\FLUKE.exe"
    if (-not (Test-Path -LiteralPath $appExecutable)) {
        throw "PyInstaller completed without producing dist\FLUKE\FLUKE.exe."
    }

    $converterExecutable = Join-Path $nativeRoot "dist\FLUKE\FLUKE-convert.exe"
    if (-not (Test-Path -LiteralPath $converterExecutable)) {
        throw "PyInstaller completed without producing dist\FLUKE\FLUKE-convert.exe."
    }

    & (Join-Path $nativeRoot "scripts\package-converter-engine-updates.ps1") -Version $version

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
Get-Item -LiteralPath $installer | Select-Object FullName, Length, LastWriteTime
