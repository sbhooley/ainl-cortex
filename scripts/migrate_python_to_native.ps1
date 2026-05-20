# Thin wrapper — runs migrate_python_to_native.py with a discovered Python.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Passthrough
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

if (Test-Path $VenvPy) {
    & $VenvPy (Join-Path $Root "scripts\migrate_python_to_native.py") @Passthrough
    exit $LASTEXITCODE
}

foreach ($name in @("python", "py", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        if ($name -eq "py") {
            & py -3 (Join-Path $Root "scripts\migrate_python_to_native.py") @Passthrough
        } else {
            & $cmd.Source (Join-Path $Root "scripts\migrate_python_to_native.py") @Passthrough
        }
        exit $LASTEXITCODE
    }
}

Write-Host "ERROR: Python not found. Run setup.ps1 first." -ForegroundColor Red
exit 1
