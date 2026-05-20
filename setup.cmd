@echo off
REM Safe Windows setup entry (always parses under PS 5.1). Forwards all args to setup.ps1.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\setup.ps1" %*
exit /b %ERRORLEVEL%
