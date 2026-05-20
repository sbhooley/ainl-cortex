@echo off
REM Windows MCP launcher — works even when python.exe is not on PATH.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap_no_python.ps1" "%ROOT%"
  if errorlevel 1 (
    echo ainl-cortex: Python bootstrap failed. See docs/INSTALL_WINDOWS.md >&2
    exit /b 1
  )
)
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\mcp_launch.py" %*
exit /b %ERRORLEVEL%
endlocal
