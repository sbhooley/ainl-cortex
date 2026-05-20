# AINL Cortex setup for Windows (PowerShell).
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly
param(
    [switch]$PythonOnly,
    [switch]$EnableNative,
    [switch]$Yes,
    [switch]$AutoInstallRust
)

$ErrorActionPreference = "Stop"
$PluginDir = $PSScriptRoot

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
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "ERROR: Python 3.10+ not found. Install from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "       Enable 'Add python.exe to PATH' in the installer." -ForegroundColor Red
    exit 1
}

$setupArgs = @("$PluginDir\scripts\setup_install.py", "--plugin-dir", $PluginDir)
if ($PythonOnly) { $setupArgs += "--python-only" }

Write-Host "=== AINL Cortex Windows setup ===" -ForegroundColor Cyan
Write-Host "  Using Python: $py"
& $py @setupArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Marketplace + settings (same as setup.sh tail; symlinks/junction on Windows)
$Settings = Join-Path $env:USERPROFILE ".claude\settings.json"
$Marketplace = Join-Path $env:USERPROFILE ".claude\ainl-local-marketplace"
$LinkPath = Join-Path $Marketplace "plugins\ainl-cortex"

Write-Host "  Setting up plugin marketplace..."
New-Item -ItemType Directory -Force -Path (Join-Path $Marketplace ".claude-plugin") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Marketplace "plugins") | Out-Null
if (Test-Path $LinkPath) { Remove-Item -Force -Recurse $LinkPath -ErrorAction SilentlyContinue }
try {
    New-Item -ItemType Junction -Path $LinkPath -Target $PluginDir | Out-Null
} catch {
    cmd /c mklink /J "$LinkPath" "$PluginDir" 2>$null
    if (-not (Test-Path $LinkPath)) {
        Write-Host "  [warn] Could not create marketplace junction; copying path reference in marketplace.json only" -ForegroundColor Yellow
    }
}

$marketplaceJson = @{
    name = "ainl-local"
    version = "1.0.0"
    description = "Local marketplace: AINL Cortex"
    owner = @{ name = "local" }
    plugins = @(
        @{
            name = "ainl-cortex"
            description = "Graph-native memory for Claude Code"
            source = "./plugins/ainl-cortex"
        }
    )
} | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $Marketplace ".claude-plugin\marketplace.json") -Value $marketplaceJson -Encoding UTF8

Write-Host "  Registering plugin in settings.json..."
$settings = @{}
if (Test-Path $Settings) {
    try { $settings = Get-Content $Settings -Raw | ConvertFrom-Json -AsHashtable } catch { $settings = @{} }
}
if (-not $settings.extraKnownMarketplaces) { $settings.extraKnownMarketplaces = @{} }
$settings.extraKnownMarketplaces["ainl-local"] = @{ source = @{ source = "directory"; path = $Marketplace } }
if (-not $settings.enabledPlugins) { $settings.enabledPlugins = @{} }
$settings.enabledPlugins["ainl-cortex@ainl-local"] = $true
New-Item -ItemType Directory -Force -Path (Split-Path $Settings) | Out-Null
$settings | ConvertTo-Json -Depth 10 | Set-Content -Path $Settings -Encoding UTF8

if ($EnableNative) {
    Write-Host ""
    Write-Host "=== Upgrading to native Rust backend ===" -ForegroundColor Cyan
    $nativeArgs = @("$PluginDir\scripts\upgrade_to_native.py", "--yes")
    if ($AutoInstallRust) { $nativeArgs += "--auto-install-rust" }
    & $py @nativeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [warn] Native upgrade failed — Python backend still works." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Setup complete (Windows) ===" -ForegroundColor Green
Write-Host "  Restart Claude Code, then run /reload-plugins if upgrading."
Write-Host "  MCP entry: python mcp_launch.py (see install_manifest.json)"
if (-not $EnableNative) {
    Write-Host "  Native backend later: powershell -File scripts/upgrade_to_native.ps1 -Yes"
}
