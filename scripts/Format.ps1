param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

# Formatting is deliberately limited to this application's maintained sources.
$formatter = Get-Command clang-format.exe -ErrorAction SilentlyContinue
if ($formatter) {
    $clangFormat = $formatter.Source
} else {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $installation = & $vswhere -latest -products '*' -property installationPath
    $clangFormat = Join-Path $installation 'VC\Tools\Llvm\x64\bin\clang-format.exe'
}
$qmlFormat = Join-Path $projectRoot '.tools\qt\6.8.3\msvc2022_64\bin\qmlformat.exe'
if (-not (Test-Path -LiteralPath $clangFormat) -or -not (Test-Path -LiteralPath $qmlFormat)) {
    throw 'Install Visual Studio C++/LLVM and run Build.cmd -Setup first.'
}
foreach ($directory in @('src/ui/cpp', 'tests')) {
    Get-ChildItem -LiteralPath (Join-Path $projectRoot $directory) -File |
        Where-Object { $_.Extension -in @('.cpp', '.h') } |
        ForEach-Object {
            & $clangFormat -i $_.FullName
            if ($LASTEXITCODE) { throw "C++ formatting failed: $($_.Name)" }
        }
}
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'src/ui/qml') -Filter '*.qml' -File |
    ForEach-Object {
        & $qmlFormat -i -n --objects-spacing --functions-spacing -w 4 -l unix $_.FullName
        if ($LASTEXITCODE) { throw "QML formatting failed: $($_.Name)" }
    }
