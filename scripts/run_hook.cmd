@echo off
setlocal
set "ROOT=%~dp0.."
set "ROOT=%ROOT:~0,-1%"
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
  exit /b %ERRORLEVEL%
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap_no_python.ps1" "%ROOT%"
if errorlevel 1 exit /b 1
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
exit /b %ERRORLEVEL%
