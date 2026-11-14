@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Release.ps1" %*
set "releaseExit=%errorlevel%"
echo.
if not "%releaseExit%"=="0" echo La creation du livrable a echoue. Consultez le journal indique ci-dessus.
pause
exit /b %releaseExit%
