@echo off
REM Windows MCP launcher — Claude Code may invoke this when bash is unavailable.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\mcp_launch.py" %*
) else (
  python "%ROOT%\mcp_launch.py" %*
)
endlocal
