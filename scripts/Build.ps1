param([switch]$Setup, [switch]$Smoke, [switch]$Deploy)
$ErrorActionPreference = 'Stop'
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
        if ($LASTEXITCODE) { throw 'Création de l’environnement du moteur impossible.' }
    }
    & $enginePython -m pip install -r (Join-Path $projectRoot 'src\core\requirements.txt')
    if ($LASTEXITCODE) { throw 'Installation des dépendances du moteur impossible.' }
    if (-not (Test-Path -LiteralPath $python)) {
        $bootstrap = Join-Path $projectRoot '.tools\engine-python\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $bootstrap)) { $bootstrap = (Get-Command python.exe).Source }
        & $bootstrap -m venv (Join-Path $projectRoot '.tools\python')
        if ($LASTEXITCODE) { throw 'Création de l’environnement de compilation impossible.' }
    }
    & $python -m pip install 'aqtinstall==3.3.0' 'cmake==4.4.4' 'ninja==1.13.2'
    if ($LASTEXITCODE) { throw 'Installation des outils impossible.' }
    if (-not (Test-Path -LiteralPath (Join-Path $sdk 'bin\qmake.exe'))) {
        & $python -m aqt install-qt windows desktop 6.8.3 win64_msvc2022_64 --outputdir (Join-Path $projectRoot '.tools\qt') --archives qtbase qtdeclarative
        if ($LASTEXITCODE) { throw 'Téléchargement de Qt impossible.' }
    }
}
if (-not (Test-Path -LiteralPath $cmake) -or -not (Test-Path -LiteralPath $sdk)) {
    throw 'Outils manquants. Exécutez Build.cmd -Setup avec Visual Studio C++ installé.'
}
$previousPath = $env:PATH
try {
    $env:PATH = (Join-Path $sdk 'bin') + ';' + $env:PATH
    $env:MSBUILDDISABLENODEREUSE = '1'
    & $cmake -S $projectRoot -B (Join-Path $projectRoot 'build') -A x64 "-DCMAKE_PREFIX_PATH=$sdk"
    if ($LASTEXITCODE) { throw 'Configuration CMake impossible.' }
    & $cmake --build (Join-Path $projectRoot 'build') --config Release --parallel 4
    if ($LASTEXITCODE) { throw 'Compilation C++ impossible.' }
    & $ctest --test-dir (Join-Path $projectRoot 'build') -C Release --output-on-failure
    if ($LASTEXITCODE) { throw 'Un test C++ a échoué.' }
    if ($Smoke) {
        & (Join-Path $projectRoot 'scripts\Launch.ps1') -Development -Smoke
    }
    if ($Deploy) {
        $destination = Join-Path $projectRoot 'dist'
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $projectRoot 'build\Release\OOTModManager.exe') -Destination $destination
        & (Join-Path $sdk 'bin\windeployqt.exe') --release --qmldir (Join-Path $projectRoot 'src\ui\qml') --no-translations (Join-Path $destination 'OOTModManager.exe')
        if ($LASTEXITCODE) { throw 'Déploiement du runtime Qt impossible.' }
    }
}
finally { $env:PATH = $previousPath }
