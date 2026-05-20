# bug_hunt_matrix.ps1 — Windows regression matrix (Python + optional native).
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/bug_hunt_matrix.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/bug_hunt_matrix.ps1 -Quick
param(
    [switch]$Quick
)

$ErrorActionPreference = "Stop"
$PluginDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPy = Join-Path $PluginDir ".venv\Scripts\python.exe"
$Pass = 0
$Fail = 0

function Ok($msg) { Write-Host "  [ok] $msg"; $script:Pass++ }
function Fail($msg) { Write-Host "  [FAIL] $msg"; $script:Fail++ }

Write-Host ""
Write-Host "=== AINL Cortex — Bug hunt matrix (Windows) ==="
Write-Host "  Plugin: $PluginDir"
Write-Host ""

if (-not (Test-Path $VenvPy)) {
    Write-Host "  [FAIL] .venv missing — run: setup.cmd -PythonOnly"
    exit 1
}

Write-Host "[1] install_manifest platform"
$manifest = Join-Path $PluginDir "install_manifest.json"
if (Test-Path $manifest) {
    $m = Get-Content $manifest -Raw | ConvertFrom-Json
    if ($m.platform -eq "windows") { Ok "platform=windows" } else { Fail "platform=$($m.platform)" }
} else {
    Fail "install_manifest.json missing"
}

Write-Host "[2] hooks.json uses run_hook.cmd"
$hooksJson = Join-Path $PluginDir "hooks\hooks.json"
if (Test-Path $hooksJson) {
    $hooks = Get-Content $hooksJson -Raw
    if ($hooks -match "run_hook\.cmd") { Ok "hooks.json -> run_hook.cmd" }
    else { Fail "hooks.json missing run_hook.cmd (run setup_install.py)" }
} else {
    Fail "hooks/hooks.json missing"
}

Write-Host "[3] plugin.json MCP launcher"
$pluginJson = Join-Path $PluginDir ".claude-plugin\plugin.json"
if (Test-Path $pluginJson) {
    $pj = Get-Content $pluginJson -Raw | ConvertFrom-Json
    $entry = $pj.mcpServers."ainl-cortex"
    if ($entry.command -eq "cmd" -and ($entry.args -join " ") -match "mcp_launch\.cmd") {
        Ok "MCP -> cmd /c mcp_launch.cmd"
    } else {
        Fail "MCP launcher not Windows-shaped (command=$($entry.command))"
    }
} else {
    Fail "plugin.json missing"
}

Write-Host "[4] MCP package-mode import"
& $VenvPy -c @"
import logging, sys
logging.disable(logging.CRITICAL)
sys.path.insert(0, r'$PluginDir')
import mcp_server.server
"@ 2>$null
if ($LASTEXITCODE -eq 0) { Ok "mcp_server.server imports" } else { Fail "package-mode import" }

Write-Host "[5] compiler_v2 (ainativelang)"
& $VenvPy -c "from compiler_v2 import AICodeCompiler" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "compiler_v2 importable" } else { Fail "ainativelang/compiler_v2" }

Write-Host "[6] ainl_native wheel (optional)"
& $VenvPy -c "import ainl_native; print(ainl_native.__file__)" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "ainl_native importable" }
else { Ok "ainl_native optional skip (Python backend valid)" }

Write-Host "[7] SessionStart hook (stdin JSON)"
$hookIn = '{"session_id":"bug-hunt-win","cwd":"C:\\"}'
$hookOut = $hookIn | & $VenvPy (Join-Path $PluginDir "scripts\run_hook.py") startup 2>$null
if ($LASTEXITCODE -eq 0 -and $hookOut -match "AINL Cortex") {
    Ok "SessionStart emits banner"
} else {
    Fail "SessionStart hook (exit=$LASTEXITCODE)"
}

if (-not $Quick) {
    Write-Host "[8] pytest — Windows-focused suite"
    & $VenvPy -m pytest @(
        "tests/test_install_bootstrap.py",
        "tests/test_platform_paths.py",
        "tests/test_windows_compat.py",
        "tests/test_python_bootstrap.py",
        "tests/test_hook_launcher_heal.py",
        "tests/test_claude_integration_heal.py",
        "tests/test_plugin_self_update.py",
        "tests/test_session_banner.py",
        "tests/test_sessionstart_visibility.py",
        "tests/test_native_roundtrip.py"
    ) -q --tb=no
    if ($LASTEXITCODE -eq 0) { Ok "Windows pytest subset passed" }
    else { Fail "Windows pytest subset (exit=$LASTEXITCODE)" }

    Write-Host "[9] native_upgrade_status.py"
    & $VenvPy (Join-Path $PluginDir "scripts\native_upgrade_status.py") --json 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "native upgrade status JSON" }
    else { Fail "native_upgrade_status.py" }

    Write-Host "[10] ensure_runtime_preflight"
    & $VenvPy (Join-Path $PluginDir "scripts\ensure_runtime_preflight.py") 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "runtime preflight" }
    else { Fail "ensure_runtime_preflight" }
}

Write-Host ""
Write-Host "  Passed: $Pass  Failed: $Fail"
Write-Host ""
if ($Fail -eq 0) {
    Write-Host "  Bug hunt matrix clean."
    exit 0
}
Write-Host "  $Fail scenario(s) failed."
exit 1
