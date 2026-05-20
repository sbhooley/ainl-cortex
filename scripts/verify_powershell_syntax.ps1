# Parse-check all PowerShell scripts (CI + local). Exit 1 on parse errors.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

Get-ChildItem -Path $root -Recurse -Include *.ps1 -File |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    ForEach-Object {
        $tokens = $null
        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $_.FullName, [ref]$tokens, [ref]$errors
        )
        if ($errors -and $errors.Count -gt 0) {
            $failed += $_.FullName
            foreach ($e in $errors) {
                Write-Host "PARSE ERROR: $($_.FullName):$($e.Extent.StartLineNumber): $($e.Message)" -ForegroundColor Red
            }
        }
    }

if ($failed.Count -gt 0) {
    Write-Host "PowerShell syntax check failed ($($failed.Count) file(s))." -ForegroundColor Red
    exit 1
}

Write-Host "PowerShell syntax OK ($root)"
exit 0
