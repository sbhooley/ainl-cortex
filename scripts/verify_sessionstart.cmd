@echo off
REM Quick check: SessionStart hook prints JSON with [AINL Cortex] on stdout.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "CLAUDE_PLUGIN_ROOT=%ROOT%"
echo Plugin root: %ROOT%
echo.
set "HOOK_IN={\"session_id\":\"verify-sessionstart\",\"cwd\":\"%CD%\"}"
if exist "%ROOT%\.venv\Scripts\python.exe" (
  echo %HOOK_IN%| "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\run_hook.py" startup
) else (
  echo %HOOK_IN%| "%ROOT%\scripts\run_hook.cmd" startup
)
echo.
echo Exit code: %ERRORLEVEL%
endlocal
