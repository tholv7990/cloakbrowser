<#
.SYNOPSIS
  One-command Windows build for the Plasma desktop app: freeze the FastAPI backend,
  drop it into the Tauri sidecar slot, and build the NSIS installer.

.DESCRIPTION
  Runs the whole chain end to end:
    1. PyInstaller freezes manager_backend -> dist/plasma-backend.exe (onefile).
    2. Copies it to src-tauri/binaries/plasma-backend-<host-triple>.exe (what the
       Tauri externalBin setting expects).
    3. Installs frontend deps.
    4. tauri build -> src-tauri/target/release/bundle/nsis/Plasma_<ver>_x64-setup.exe.

  Default build is UNSIGNED and works out of the box. Pass -CertThumbprint to
  Authenticode-sign (cert must be installed in the Windows certificate store).

.PARAMETER CertThumbprint
  Authenticode code-signing cert thumbprint (from the Windows store). Omit for an
  unsigned build.

.PARAMETER Icon
  Path to a >=1024x1024 PNG to (re)generate the app icon set. Required only if
  src-tauri/icons does not exist yet.

.PARAMETER SkipFrontendInstall
  Skip npm install in manager/frontend (use when deps are already installed).

.EXAMPLE
  ./build.ps1 -Icon .\assets\plasma-1024.png

.EXAMPLE
  ./build.ps1 -CertThumbprint 0123ABCD
#>
[CmdletBinding()]
param(
  [string]$CertThumbprint,
  [string]$Icon,
  [switch]$SkipFrontendInstall,
  [string]$SigningKeyPath = "$env:USERPROFILE\.plasma-signing\plasma-updater.key"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Updater signing key. tauri build reads TAURI_SIGNING_PRIVATE_KEY to produce the
# .sig files the auto-updater verifies; without it the build fails because
# createUpdaterArtifacts is on. The key lives outside the repo (never committed).
# Publish the printed .sig content + installer URL from the admin Releases screen.
if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
  if (Test-Path $SigningKeyPath) {
    $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $SigningKeyPath -Raw
    # The key was generated with --ci (no password). Tauri's signer still reads
    # TAURI_SIGNING_PRIVATE_KEY_PASSWORD; it MUST exist as an empty value or the
    # signer falls back to an interactive stdin prompt that hangs a headless build.
    # $env:VAR = "" removes the var in PowerShell, so set it via the provider API.
    [Environment]::SetEnvironmentVariable("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "", "Process")
  } else {
    throw "Updater signing key not found at $SigningKeyPath. Generate one with:  npx @tauri-apps/cli@2 signer generate --ci -w `"$SigningKeyPath`"  (or pass -SigningKeyPath / set TAURI_SIGNING_PRIVATE_KEY)."
  }
}

function Need($name, $hint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Missing $name. $hint" }
}

# Run an external tool. PowerShell 5.1 turns ANY native stderr line into a
# terminating error under -ErrorActionPreference Stop (cargo/npm/tauri all print
# normal progress to stderr), so drop to Continue for the call and judge success by
# the real exit code instead.
function Invoke-Native($what, [scriptblock]$cmd) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $cmd } finally { $ErrorActionPreference = $prev }
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

Write-Host "==> Checking prerequisites" -ForegroundColor Cyan
Need python "Install Python 3.13, then pip install the app + pyinstaller."
Need npm    "Install Node.js LTS (bundles npm)."
Need cargo  "Install the Rust toolchain from https://rustup.rs (MSVC)."
Need rustc  "Install the Rust toolchain from https://rustup.rs (MSVC)."
Need npx    "npx ships with Node.js; reinstall Node if it is missing."
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller is not installed in this Python. Run pip install pyinstaller." }

# --- icons (Tauri build requires them) ---------------------------------------
# The generated icons/ set is gitignored; on a fresh checkout regenerate it from the
# committed source PNG so `./build.ps1` works with no arguments.
$iconsDir = Join-Path $root "src-tauri/icons"
$defaultIconSource = Join-Path $root "src-tauri/icon-source.png"
if (-not $Icon -and -not (Test-Path $iconsDir) -and (Test-Path $defaultIconSource)) {
  $Icon = $defaultIconSource
}
if ($Icon) {
  if (-not (Test-Path $Icon)) { throw "Icon source not found: $Icon" }
  Write-Host "==> Generating icon set from $Icon" -ForegroundColor Cyan
  Invoke-Native "tauri icon" { npx --yes "@tauri-apps/cli@2" icon $Icon }
} elseif (-not (Test-Path $iconsDir)) {
  throw "No src-tauri/icons found. Provide one once with:  ./build.ps1 -Icon path\to\plasma-1024.png"
}

# --- 1. freeze the backend ----------------------------------------------------
Write-Host "==> [1/4] Freezing the FastAPI backend (PyInstaller onefile)" -ForegroundColor Cyan
Invoke-Native "PyInstaller" { python -m PyInstaller src-tauri/plasma-backend.spec --noconfirm --clean }
$frozen = Join-Path $root "dist/plasma-backend.exe"
if (-not (Test-Path $frozen)) { throw "PyInstaller did not produce $frozen." }

# --- 2. place the sidecar at the host target triple ---------------------------
Write-Host "==> [2/4] Placing the sidecar for Tauri" -ForegroundColor Cyan
$prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$hostLine = & rustc -vV 2>&1 | Select-String -Pattern "host:\s*(\S+)"
$ErrorActionPreference = $prev
if (-not $hostLine) { throw "Could not read the host target triple from rustc -vV output." }
$triple = $hostLine.Matches[0].Groups[1].Value.Trim()
$binaries = Join-Path $root "src-tauri/binaries"
New-Item -ItemType Directory -Force -Path $binaries | Out-Null
$dest = Join-Path $binaries "plasma-backend-$triple.exe"
Copy-Item $frozen $dest -Force
Write-Host "    -> $dest"

# --- 3. frontend deps + build -------------------------------------------------
if ($SkipFrontendInstall) {
  Write-Host "==> [3/4] Skipping frontend deps (-SkipFrontendInstall)" -ForegroundColor Cyan
} else {
  Write-Host "==> [3/4] Installing frontend deps" -ForegroundColor Cyan
  Invoke-Native "npm install" { npm --prefix manager/frontend install }
}
# Built here, not via beforeBuildCommand: the Tauri CLI runs hooks from the
# nearest package.json directory it can find, and with no root package.json
# that scan landed on cloud/admin-ui, so a cwd-relative --prefix broke.
Write-Host "==> [3/4] Building the frontend" -ForegroundColor Cyan
Invoke-Native "frontend build" { npm --prefix manager/frontend run build }

# --- 4. build the app + installer --------------------------------------------
Write-Host "==> [4/4] Building the app + NSIS installer" -ForegroundColor Cyan
$buildArgs = @("--yes", "@tauri-apps/cli@2", "build")
if ($CertThumbprint) {
  $signCfg = Join-Path $env:TEMP "plasma-sign.json"
  @{ bundle = @{ windows = @{ certificateThumbprint = $CertThumbprint } } } |
    ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $signCfg
  $buildArgs += @("--config", $signCfg)
  Write-Host "    signing with cert thumbprint $CertThumbprint"
} else {
  Write-Warning "No -CertThumbprint given: building UNSIGNED (Windows SmartScreen will warn users)."
}
Invoke-Native "tauri build" { npx @buildArgs }

# --- report -------------------------------------------------------------------
$installer = Get-ChildItem "src-tauri/target/release/bundle/nsis/*-setup.exe" -ErrorAction SilentlyContinue |
  Select-Object -First 1
if (-not $installer) {
  throw "Build finished but no installer under src-tauri/target/release/bundle/nsis/."
}
Write-Host ""
Write-Host "BUILD OK" -ForegroundColor Green
Write-Host ("  installer: " + $installer.FullName)
if (-not $CertThumbprint) {
  Write-Host "  unsigned build - pass -CertThumbprint to sign a release" -ForegroundColor Yellow
}

# --- update-release fields ----------------------------------------------------
# The auto-updater's .sig file sits next to the installer. Print the values the
# admin Releases screen needs so publishing is copy-paste, not guesswork.
$sig = Get-ChildItem "src-tauri/target/release/bundle/nsis/*-setup.exe.sig" -ErrorAction SilentlyContinue |
  Select-Object -First 1
$version = (Get-Content "src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json).version
$sha256 = (Get-FileHash $installer.FullName -Algorithm SHA256).Hash.ToLower()
Write-Host ""
Write-Host "PUBLISH THIS RELEASE (admin -> Releases):" -ForegroundColor Cyan
Write-Host ("  version:      " + $version)
Write-Host ("  artifact URL: host " + $installer.Name + " somewhere HTTPS, use that URL")
Write-Host ("  sha256:       " + $sha256)
if ($sig) {
  Write-Host "  signature:    (contents of the .sig file below)"
  Write-Host ("  " + (Get-Content $sig.FullName -Raw).Trim()) -ForegroundColor DarkGray
} else {
  Write-Warning "No .sig file produced - is createUpdaterArtifacts on and the signing key set?"
}
