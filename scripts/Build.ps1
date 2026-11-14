param([switch]$Setup, [switch]$SetupOnly, [switch]$Smoke, [switch]$Deploy)
$ErrorActionPreference = 'Stop'
if ($SetupOnly -and -not $Setup) { throw '-SetupOnly requires -Setup.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.tools\python\Scripts\python.exe'
$cmake = Join-Path $projectRoot '.tools\python\Lib\site-packages\cmake\data\bin\cmake.exe'
$ctest = Join-Path $projectRoot '.tools\python\Lib\site-packages\cmake\data\bin\ctest.exe'
$sdk = Join-Path $projectRoot '.tools\qt\6.8.3\msvc2022_64'
if ($Setup) {
    $enginePython = Join-Path $projectRoot '.tools\engine-python\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $enginePython)) {
        $systemPython = (Get-Command python.exe).Source
        & $systemPython -m venv (Join-Path $projectRoot '.tools\engine-python')
        if ($LASTEXITCODE) { throw 'Could not create the engine Python environment.' }
    }
    & $enginePython -m pip install -r (Join-Path $projectRoot 'src\core\requirements.txt')
    if ($LASTEXITCODE) { throw 'Could not install engine dependencies.' }
    if (-not (Test-Path -LiteralPath $python)) {
        $bootstrap = Join-Path $projectRoot '.tools\engine-python\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $bootstrap)) { $bootstrap = (Get-Command python.exe).Source }
        & $bootstrap -m venv (Join-Path $projectRoot '.tools\python')
        if ($LASTEXITCODE) { throw 'Could not create the build Python environment.' }
    }
    & $python -m pip install 'aqtinstall==3.3.0' 'cmake==4.4.4' 'ninja==1.13.2'
    if ($LASTEXITCODE) { throw 'Could not install build tools.' }
    if (-not (Test-Path -LiteralPath (Join-Path $sdk 'bin\qmake.exe'))) {
        & $python -m aqt install-qt windows desktop 6.8.3 win64_msvc2022_64 --outputdir (Join-Path $projectRoot '.tools\qt') --archives qtbase qtdeclarative
        if ($LASTEXITCODE) { throw 'Could not download Qt.' }
    }
}
if (-not (Test-Path -LiteralPath $cmake) -or -not (Test-Path -LiteralPath $sdk)) {
    throw 'Missing tools. Run Build.cmd -Setup with Visual Studio C++ installed.'
}
if ($SetupOnly) { return }
$previousPath = $env:PATH
try {
    $env:PATH = (Join-Path $sdk 'bin') + ';' + $env:PATH
    $env:MSBUILDDISABLENODEREUSE = '1'
    & $cmake -S $projectRoot -B (Join-Path $projectRoot 'build') -A x64 "-DCMAKE_PREFIX_PATH=$sdk"
    if ($LASTEXITCODE) { throw 'CMake configuration failed.' }
    & $cmake --build (Join-Path $projectRoot 'build') --config Release --parallel 4
    if ($LASTEXITCODE) { throw 'C++ build failed.' }
    & $ctest --test-dir (Join-Path $projectRoot 'build') -C Release --output-on-failure
    if ($LASTEXITCODE) { throw 'C++ tests failed.' }
    if ($Smoke) {
        & (Join-Path $projectRoot 'scripts\Launch.ps1') -Development -Smoke
    }
    if ($Deploy) {
        $destination = Join-Path $projectRoot 'dist'
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $projectRoot 'build\Release\OOTModManager.exe') -Destination $destination
        & (Join-Path $sdk 'bin\windeployqt.exe') --release --qmldir (Join-Path $projectRoot 'src\ui\qml') --no-translations (Join-Path $destination 'OOTModManager.exe')
        if ($LASTEXITCODE) { throw 'Qt runtime deployment failed.' }
    }
}
finally { $env:PATH = $previousPath }
