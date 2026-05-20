# Upgrade to native Rust backend on Windows.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1 -Yes
#   powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1 -Yes -AutoInstallRust
param(
    [Alias("Yes")]
    [switch]$Assumeyes,
    [switch]$AutoInstallRust,
    [switch]$SkipMigrate,
    [switch]$PreferSource
)

$ErrorActionPreference = "Stop"
$PluginDir = $PSScriptRoot | Split-Path -Parent

function Find-Python {
    foreach ($name in @("python", "py", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "ERROR: Python not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

$argsList = @("$PluginDir\scripts\upgrade_to_native.py")
if ($Yes) { $argsList += "--yes" }
if ($AutoInstallRust) { $argsList += "--auto-install-rust" }
if ($SkipMigrate) { $argsList += "--skip-migrate" }
if ($PreferSource) { $argsList += "--prefer-source" }

& $py @argsList
exit $LASTEXITCODE
