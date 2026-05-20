# Bootstrap Python + .venv when NO python is on PATH (Windows MCP/hooks entry).
param(
    [string]$PluginDir = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$PluginDir = (Resolve-Path $PluginDir).Path
$venvPy = Join-Path $PluginDir ".venv\Scripts\python.exe"

if (Test-Path $venvPy) { exit 0 }

Write-Host "ainl-cortex: no Python on PATH - bootstrapping via uv..." -ForegroundColor Cyan

# Prefer curl.exe (Win10+) then Invoke-WebRequest
$uvVer = "0.6.14"
$arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "x86" }
if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $arch = "aarch64" }
$zipName = "uv-$arch-pc-windows-msvc.zip"
$url = "https://github.com/astral-sh/uv/releases/download/$uvVer/$zipName"
$bootstrap = Join-Path $PluginDir ".ainl-bootstrap\uv"
$zipPath = Join-Path $bootstrap $zipName
$uvExe = Join-Path $bootstrap "uv.exe"

New-Item -ItemType Directory -Force -Path $bootstrap | Out-Null

if (-not (Test-Path $uvExe)) {
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        curl.exe -fsSL -o $zipPath $url
    } else {
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    }
    Expand-Archive -Path $zipPath -DestinationPath $bootstrap -Force
}

if (-not (Test-Path $uvExe)) {
    Write-Host "ERROR: uv download failed" -ForegroundColor Red
    exit 1
}

$pyDir = Join-Path $PluginDir ".ainl-bootstrap\pythons"
$env:UV_PYTHON_INSTALL_DIR = $pyDir
& $uvExe python install 3.12
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $uvExe venv (Join-Path $PluginDir ".venv") --python 3.12 --seed
exit $LASTEXITCODE
