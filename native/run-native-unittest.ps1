param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$nativeRoot = $PSScriptRoot
$python = Join-Path $nativeRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Native Python environment was not found: $python"
}

$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "software"
$env:QT_QUICK_CONTROLS_STYLE = "Basic"
$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"

$arguments = @("-m", "unittest", "discover", "-s", "tests")
if ($Verbose) {
    $arguments += "-v"
}

Push-Location $nativeRoot
try {
    & $python @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitCode
