[CmdletBinding()]
param(
    [ValidateSet("Deterministic", "ExistingOwner")]
    [string]$Mode = "Deterministic",
    [switch]$LiveDiagnostics
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$flagNames = @(
    "CLOAK_RUN_MANAGER_E2E",
    "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E",
    "CLOAK_LIVE_DIAGNOSTICS"
)
$originalFlags = @{}
foreach ($flagName in $flagNames) {
    $originalFlags[$flagName] = @{
        Present = Test-Path -LiteralPath "Env:$flagName"
        Value = [Environment]::GetEnvironmentVariable($flagName, "Process")
    }
}

Push-Location $repositoryRoot
try {
    foreach ($flagName in $flagNames) {
        Remove-Item -LiteralPath "Env:$flagName" -ErrorAction SilentlyContinue
    }
    if ($Mode -eq "Deterministic") {
        if (-not $env:CLOAKBROWSER_LICENSE_KEY) {
            throw "CLOAKBROWSER_LICENSE_KEY is missing from the process environment."
        }
        $env:CLOAK_RUN_MANAGER_E2E = "1"
        if ($LiveDiagnostics) {
            $env:CLOAK_LIVE_DIAGNOSTICS = "1"
        }
        & python -m pytest tests/manager/e2e/test_manager_smoke.py::test_authenticated_windows_foundation_smoke -q -rs
    }
    else {
        $env:CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E = "1"
        & python -m pytest tests/manager/e2e/test_manager_smoke.py::test_existing_owner_mode_uses_environment_credentials_only -q -rs
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Manager E2E failed with exit code $LASTEXITCODE."
    }
}
finally {
    try {
        foreach ($flagName in $flagNames) {
            $original = $originalFlags[$flagName]
            if ($original.Present) {
                Set-Item -LiteralPath "Env:$flagName" -Value $original.Value
            }
            else {
                Remove-Item -LiteralPath "Env:$flagName" -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        Pop-Location
    }
}
