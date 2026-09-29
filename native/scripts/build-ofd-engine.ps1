param(
    [switch]$SkipRuntime
)

$ErrorActionPreference = "Stop"
$nativeRoot = Split-Path -Parent $PSScriptRoot
$engineRoot = Join-Path $nativeRoot "engine\ofd"
$buildRoot = Join-Path $engineRoot "build"
$cacheRoot = Join-Path $nativeRoot "qa-sandbox\ofd-engine-build"
$toolsRoot = Join-Path $cacheRoot "tools"
$jdkVersion = "21.0.12.1+1"
$jdkArchiveName = "OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip"
$jdkArchive = Join-Path $toolsRoot $jdkArchiveName
$jdkSha256 = "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e"
$jdkUrl = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/$jdkArchiveName"
$jdkHome = Join-Path $toolsRoot "jdk-21.0.12.1+1"
$mavenVersion = "3.9.16"
$mavenArchiveName = "apache-maven-$mavenVersion-bin.zip"
$mavenArchive = Join-Path $toolsRoot $mavenArchiveName
$mavenUrl = "https://dlcdn.apache.org/maven/maven-3/$mavenVersion/binaries/$mavenArchiveName"
$mavenHome = Join-Path $toolsRoot "apache-maven-$mavenVersion"

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null

function Assert-Sha256([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 verification failed for $Path."
    }
}

if (-not (Test-Path -LiteralPath $jdkHome)) {
    if (-not (Test-Path -LiteralPath $jdkArchive)) {
        Invoke-WebRequest -Uri $jdkUrl -OutFile $jdkArchive
    }
    Assert-Sha256 -Path $jdkArchive -Expected $jdkSha256
    Expand-Archive -LiteralPath $jdkArchive -DestinationPath $toolsRoot -Force
    $extracted = Get-ChildItem -LiteralPath $toolsRoot -Directory -Filter "jdk-21.0.12.1+1*" | Select-Object -First 1
    if (-not $extracted) {
        throw "The verified Temurin archive did not contain the expected JDK directory."
    }
    if ($extracted.FullName -ne $jdkHome) {
        Move-Item -LiteralPath $extracted.FullName -Destination $jdkHome
    }
}

if (-not (Test-Path -LiteralPath $mavenHome)) {
    if (-not (Test-Path -LiteralPath $mavenArchive)) {
        Invoke-WebRequest -Uri $mavenUrl -OutFile $mavenArchive
    }
    $mavenChecksumText = (Invoke-WebRequest -Uri "$mavenUrl.sha512").Content
    $mavenExpectedSha512 = ([regex]::Match($mavenChecksumText, "(?i)\b[0-9a-f]{128}\b")).Value
    if (-not $mavenExpectedSha512) {
        throw "Could not read the official Apache Maven SHA-512 checksum."
    }
    $mavenActualSha512 = (Get-FileHash -LiteralPath $mavenArchive -Algorithm SHA512).Hash.ToLowerInvariant()
    if ($mavenActualSha512 -ne $mavenExpectedSha512.ToLowerInvariant()) {
        throw "SHA-512 verification failed for the Maven archive."
    }
    Expand-Archive -LiteralPath $mavenArchive -DestinationPath $toolsRoot -Force
}

$env:JAVA_HOME = $jdkHome
$env:PATH = (Join-Path $jdkHome "bin") + [IO.Path]::PathSeparator + $env:PATH
$maven = Join-Path $mavenHome "bin\mvn.cmd"
if (-not (Test-Path -LiteralPath $maven)) {
    throw "Apache Maven $mavenVersion was not extracted correctly."
}

$localRepository = Join-Path $cacheRoot "maven-repository"
& $maven --batch-mode --no-transfer-progress "-Dmaven.repo.local=$localRepository" -f (Join-Path $engineRoot "pom.xml") clean package
if ($LASTEXITCODE -ne 0) {
    throw "The OFD bridge build failed with exit code $LASTEXITCODE."
}

& $maven --batch-mode --no-transfer-progress "-Dmaven.repo.local=$localRepository" `
    org.apache.maven.plugins:maven-dependency-plugin:3.8.1:get `
    "-Dartifact=org.ujmp:ujmp-core:0.3.0:jar:sources" `
    "-Dtransitive=false"
if ($LASTEXITCODE -ne 0) {
    throw "Could not obtain the source archive for the LGPL UJMP runtime library."
}

$artifact = Join-Path $engineRoot "target\fluke-ofd-bridge-0.1.0.jar"
$dependencies = Join-Path $engineRoot "target\dist\lib"
if (-not (Test-Path -LiteralPath $artifact) -or -not (Test-Path -LiteralPath $dependencies)) {
    throw "The OFD bridge build did not produce its JAR and runtime libraries."
}

if (Test-Path -LiteralPath $buildRoot) {
    $resolvedBuild = [IO.Path]::GetFullPath($buildRoot)
    $resolvedEngine = [IO.Path]::GetFullPath($engineRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedBuild.StartsWith($resolvedEngine, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace an OFD build directory outside the engine workspace."
    }
    Remove-Item -LiteralPath $resolvedBuild -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $buildRoot "lib") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $buildRoot "licenses") | Out-Null
Copy-Item -LiteralPath $artifact -Destination (Join-Path $buildRoot "bridge.jar")
Copy-Item -Path (Join-Path $dependencies "*.jar") -Destination (Join-Path $buildRoot "lib")
Copy-Item -LiteralPath (Join-Path $engineRoot "THIRD-PARTY-NOTICES.md") -Destination $buildRoot
Copy-Item -LiteralPath (Join-Path $engineRoot "LICENSE-OFDRW.txt") -Destination $buildRoot
Copy-Item -Path (Join-Path $engineRoot "licenses\*") -Destination (Join-Path $buildRoot "licenses") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $engineRoot "LICENSE-OFDRW.txt") -Destination (Join-Path $buildRoot "licenses\Apache-2.0.txt") -Force
$ujmpSources = Join-Path $localRepository "org\ujmp\ujmp-core\0.3.0\ujmp-core-0.3.0-sources.jar"
if (-not (Test-Path -LiteralPath $ujmpSources)) {
    throw "The matching UJMP source archive was not present in the Maven cache."
}
Copy-Item -LiteralPath $ujmpSources -Destination (Join-Path $buildRoot "licenses\ujmp-core-0.3.0-sources.jar") -Force

if (-not $SkipRuntime) {
    $jlink = Join-Path $jdkHome "bin\jlink.exe"
    $runtime = Join-Path $buildRoot "java-runtime"
    & $jlink `
        --add-modules "java.base,java.datatransfer,java.desktop,java.logging,java.management,java.naming,java.prefs,java.scripting,java.security.jgss,java.xml,jdk.charsets,jdk.crypto.ec,jdk.unsupported" `
        --strip-debug `
        --no-man-pages `
        --no-header-files `
        --compress=2 `
        --output $runtime
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the bundled Java runtime."
    }
    Copy-Item -LiteralPath (Join-Path $jdkHome "legal") -Destination $runtime -Recurse -Force
    & (Join-Path $runtime "bin\java.exe") -version
    if ($LASTEXITCODE -ne 0) {
        throw "The generated OFD Java runtime failed its startup check."
    }
}

Write-Output "OFD bridge and runtime are ready at $buildRoot"
