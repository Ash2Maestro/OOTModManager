param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.tools\engine-python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error 'Outils de developpement absents. Executez Build.cmd -Setup avant Release.cmd.'
    exit 1
}
$arguments = @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'release.py'))
if ($NoOpen) { $arguments += '--no-open' }
& $python @arguments
exit $LASTEXITCODE
