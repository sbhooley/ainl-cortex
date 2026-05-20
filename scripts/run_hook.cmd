@echo off
setlocal
REM Resolve plugin root (this file lives in scripts\). Do NOT use %~dp0.. + substring — that yields scripts\. on Windows.
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
REM Self-heal: legacy installs left ROOT at scripts\. (hooks could not find .venv or startup.py).
if not exist "%ROOT%\hooks\startup.py" (
  for %%J in ("%~dp0..") do set "ROOT=%%~fJ"
)
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
  exit /b %ERRORLEVEL%
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap_no_python.ps1" "%ROOT%"
if errorlevel 1 exit /b 1
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" %*
exit /b %ERRORLEVEL%
