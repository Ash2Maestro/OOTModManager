param([switch]$Demo, [switch]$Smoke, [switch]$Development)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$qtBin = Join-Path $projectRoot '.tools\qt\6.8.3\msvc2022_64\bin'
$executable = Join-Path $projectRoot 'dist\OOTModManager.exe'
if ($Development -or -not (Test-Path -LiteralPath $executable)) { $executable = Join-Path $projectRoot 'build\Release\OOTModManager.exe' }
if (-not (Test-Path -LiteralPath $executable)) { throw 'Exécutez Build.cmd avant de lancer cette interface.' }
$previousPath = $env:PATH
$previousStyle = $env:QT_QUICK_CONTROLS_STYLE
try {
    if ($executable -like '*\build\Release\*' -and (Test-Path -LiteralPath $qtBin)) { $env:PATH = $qtBin + ';' + $env:PATH }
    $env:QT_QUICK_CONTROLS_STYLE = 'Basic'
    $arguments = '--project-root "' + $projectRoot + '"'
    if ($Demo) { $arguments += ' --demo' }
    if ($Smoke) {
        $arguments += ' --smoke'
        $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Normal -Wait -PassThru
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Vérification QML échouée (code $($process.ExitCode))." }
        return
    }
    Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Normal | Out-Null
}
finally {
    $env:PATH = $previousPath
    $env:QT_QUICK_CONTROLS_STYLE = $previousStyle
}
