# AINL Cortex setup for Windows (PowerShell).
# SETUP_SCRIPT_VERSION=2  (install_bootstrap checks this; do not remove)
# Usage (preferred):
#   setup.cmd -PythonOnly
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly
# Avoid:  & setup.ps1 -Yes   (old copies + PS 5.1 may fail to parse)
param(
    [switch]$PythonOnly,
    [switch]$EnableNative,
    [Alias("Yes")]
    [switch]$NonInteractive,
    [switch]$AutoInstallRust
)
# Note: do not use a parameter named "Yes" — PS 5.1 breaks on "-Yes" inside double-quoted strings.

$ErrorActionPreference = "Stop"
$PluginDir = $PSScriptRoot

# Fail fast if an outdated setup.ps1 is still on disk (pre-60b30d5).
# Use Select-String: "-notmatch" on a string[] returns non-matching lines (always truthy).
if (-not (Select-String -LiteralPath $PSCommandPath -Pattern 'SETUP_SCRIPT_VERSION=2' -Quiet)) {
    Write-Host "ERROR: setup.ps1 is outdated (missing SETUP_SCRIPT_VERSION=2)." -ForegroundColor Red
    Write-Host "  cd $PluginDir" -ForegroundColor Yellow
    Write-Host "  git pull" -ForegroundColor Yellow
    Write-Host "  Or run: setup.cmd -PythonOnly" -ForegroundColor Yellow
    exit 2
}

# Refuse disposable temp verification clones (mirrors setup.sh).
$pluginNorm = $PluginDir -replace '\\', '/'
if ($pluginNorm -match '(?i)(^|/)(tmp|temp)/ainl-cortex' -or $pluginNorm -match 'ainl-cortex-fresh') {
    Write-Host "ERROR: setup.ps1 was run from a temp directory:" -ForegroundColor Red
    Write-Host "  $PluginDir"
    Write-Host "  Run from: $env:USERPROFILE\.claude\plugins\ainl-cortex"
    exit 1
}

function Find-Python {
    foreach ($name in @("python", "py", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    $venvPy = Join-Path $PluginDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    return $null
}

function Ensure-VenvPython {
    $venvPy = Join-Path $PluginDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    Write-Host "  No system Python on PATH - bootstrapping via uv..." -ForegroundColor Cyan
    $boot = Join-Path $PluginDir "scripts\bootstrap_no_python.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $boot $PluginDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Python bootstrap failed." -ForegroundColor Red
        Write-Host "  Install Python 3.10+ or allow network access for uv download." -ForegroundColor Red
        exit 1
    }
    if (Test-Path $venvPy) { return $venvPy }
    Write-Host "ERROR: Bootstrap finished but .venv\Scripts\python.exe missing." -ForegroundColor Red
    exit 1
}

$py = Find-Python
if (-not $py) {
    $py = Ensure-VenvPython
}

$setupArgs = @(
    "$PluginDir\scripts\setup_install.py",
    "--plugin-dir", $PluginDir,
    "--register-claude"
)
if ($PythonOnly) { $setupArgs += "--python-only" }

Write-Host "=== AINL Cortex Windows setup ===" -ForegroundColor Cyan
Write-Host "  Using Python: $py"
& $py @setupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# -Yes: non-interactive (no prompts in this script). Does not enable native when -PythonOnly.
if ($EnableNative) {
    Write-Host ""
    Write-Host "=== Upgrading to native Rust backend ===" -ForegroundColor Cyan
    $nativeArgs = @("$PluginDir\scripts\upgrade_to_native.py", "--yes")
    if ($AutoInstallRust) { $nativeArgs += "--auto-install-rust" }
    & $py @nativeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [warn] Native upgrade failed - Python backend still works." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Setup complete (Windows) ===" -ForegroundColor Green
Write-Host "  Restart Claude Code, then run /reload-plugins if upgrading."
Write-Host "  MCP: mcp_launch.cmd (see install_manifest.json)"
if (-not $EnableNative) {
    # Single-quoted: avoid PS 5.1 parsing -Yes / -File inside double quotes as parameters.
    Write-Host '  Native backend later: powershell -ExecutionPolicy Bypass -File scripts\upgrade_to_native.ps1 -Yes'
}
