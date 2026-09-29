param(
    [string]$CandidateRoot = (Join-Path $PSScriptRoot '..')
)

$ErrorActionPreference = 'Stop'
$CandidateRoot = [IO.Path]::GetFullPath($CandidateRoot)
$StageBin = Join-Path $CandidateRoot 'staging\bin'
$MsysRoot = Join-Path (Split-Path -Parent $CandidateRoot) 'msys64\msys64'
$MingwBin = Join-Path $MsysRoot 'mingw64\bin'
$MsysBin = Join-Path $MsysRoot 'usr\bin'
$Objdump = Join-Path $MingwBin 'objdump.exe'
$System32 = Join-Path $env:SystemRoot 'System32'
$ManifestPath = Join-Path $CandidateRoot 'runtime-dependencies.json'

foreach ($path in @($StageBin, $MingwBin, $Objdump, $System32)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required runtime scan path is missing: $path" }
}

$queue = [Collections.Generic.Queue[string]]::new()
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$files = [Collections.Generic.List[object]]::new()
$imports = [Collections.Generic.List[object]]::new()
$unresolved = [Collections.Generic.List[object]]::new()

foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
    $path = Join-Path $StageBin $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Built executable is missing: $path" }
    $queue.Enqueue($path)
}

while ($queue.Count -gt 0) {
    $current = $queue.Dequeue()
    $key = [IO.Path]::GetFullPath($current)
    if (-not $seen.Add($key)) { continue }

    $relative = [IO.Path]::GetRelativePath($StageBin, $current)
    $files.Add([pscustomobject]@{
        file = $relative
        sha256 = (Get-FileHash -LiteralPath $current -Algorithm SHA256).Hash.ToLowerInvariant()
    })

    $output = & $Objdump -p $current
    foreach ($line in $output) {
        if ($line -notmatch '^\s*DLL Name:\s*(.+?)\s*$') { continue }
        $name = $Matches[1]
        $kind = ''
        $resolvedPath = ''

        if ($name -match '^(api-ms-win-|ext-ms-win-)') {
            $kind = 'windows-api-set'
        } elseif (Test-Path -LiteralPath (Join-Path $System32 $name)) {
            $kind = 'windows-system32'
        } else {
            $candidate = Join-Path $StageBin $name
            if (Test-Path -LiteralPath $candidate) {
                $kind = 'candidate-stage'
                $resolvedPath = $candidate
            } else {
                $candidate = Join-Path $MingwBin $name
                if (Test-Path -LiteralPath $candidate) {
                    $kind = 'mingw64-runtime'
                    $resolvedPath = $candidate
                    Copy-Item -LiteralPath $candidate -Destination (Join-Path $StageBin $name)
                    $resolvedPath = Join-Path $StageBin $name
                } else {
                    $candidate = Join-Path $MsysBin $name
                    if (Test-Path -LiteralPath $candidate) {
                        $kind = 'msys-runtime'
                        $resolvedPath = $candidate
                        Copy-Item -LiteralPath $candidate -Destination (Join-Path $StageBin $name)
                        $resolvedPath = Join-Path $StageBin $name
                    } else {
                        $kind = 'unresolved'
                    }
                }
            }
        }

        $imports.Add([pscustomobject]@{ from = $relative; dll = $name; kind = $kind })
        if ($kind -eq 'unresolved') {
            $unresolved.Add([pscustomobject]@{ from = $relative; dll = $name })
        } elseif ($resolvedPath -and ([IO.Path]::GetExtension($resolvedPath) -ieq '.dll')) {
            $queue.Enqueue($resolvedPath)
        }
    }
}

$manifest = [pscustomobject]@{
    generated_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    executables = @('ffmpeg.exe', 'ffprobe.exe')
    pe_files = $files
    imports = $imports
    unresolved = $unresolved
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ManifestPath -Encoding utf8

$files | Sort-Object file | Format-Table -AutoSize
if ($unresolved.Count -gt 0) {
    $unresolved | Format-Table -AutoSize
    throw "Runtime dependency closure has $($unresolved.Count) unresolved import(s). See $ManifestPath"
}
Write-Host "All non-Windows PE imports resolved. Manifest: $ManifestPath"
