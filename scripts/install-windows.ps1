<#
.SYNOPSIS
    Installs Rosie on Windows: Python environment, config, environment variables,
    rosie-vault, a health check and (optionally) the orb app.

.DESCRIPTION
    Run it from the folder you cloned Rosie into, in PowerShell:

        powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1

    Safe to run again: it never overwrites your config\rosie.yaml or .env, and only
    adds what is missing. Nothing is written outside the repo folder and -DataDir
    (D:\Rosie by default), except two user environment variables (no admin rights):

        ROSIE_CONFIG  -> <repo>\config\rosie.yaml   so Rosie finds her config at login
        ROSIE_CORE    -> <repo>\.venv\Scripts\rosie.exe   so the orb can start the core

.PARAMETER DataDir
    Where Rosie keeps her data (vault, logs, backups). Default: D:\Rosie.

.PARAMETER Voice
    Also install the voice extras (microphone, speech-to-text, voices).

.PARAMETER Orb
    Also build the orb app (needs Rust and Node.js) and print where the installer is.

.PARAMETER SkipDoctor
    Don't run `rosie doctor` at the end (CI uses this; Ollama isn't there).
#>
param(
    [string]$DataDir = "D:\Rosie",
    [switch]$Voice,
    [switch]$Orb,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "   ok   $text" -ForegroundColor Green }
function Note($text) { Write-Host "   note $text" -ForegroundColor Yellow }

function Find-Python {
    # The py launcher knows every installed Python; fall back to python on PATH.
    foreach ($candidate in @(@("py", "-3.12"), @("py", "-3.11"), @("python"))) {
        $exe = $candidate[0]
        $pyArgs = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $version = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -and [version]$version -ge [version]"3.11") {
            return @{ Exe = $exe; Args = $pyArgs; Version = $version }
        }
    }
    throw "Python 3.11 or newer not found. Install it: winget install -e --id Python.Python.3.12"
}

Step "Python"
$python = Find-Python
Ok "Python $($python.Version)"

Step "Rosie's environment ($Repo\.venv)"
$venvPython = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $python.Exe @($python.Args) -m venv (Join-Path $Repo ".venv")
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
}
$extras = if ($Voice) { ".[dev,voice]" } else { ".[dev]" }
Push-Location $Repo
try {
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -e $extras
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
} finally { Pop-Location }
$rosie = Join-Path $Repo ".venv\Scripts\rosie.exe"
Ok (& $rosie --version)

Step "Config"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$config = Join-Path $Repo "config\rosie.yaml"
if (Test-Path $config) {
    Ok "kept your config\rosie.yaml"
} else {
    $example = Get-Content (Join-Path $Repo "config\rosie.example.yaml") -Raw
    $dataDirYaml = $DataDir -replace "\\", "/"
    $example = $example -replace 'data_dir: "D:/Rosie"', "data_dir: `"$dataDirYaml`""
    Set-Content -Path $config -Value $example -Encoding UTF8
    Ok "created config\rosie.yaml (data in $DataDir); open it to set user_vault_dir"
}
$envFile = Join-Path $Repo ".env"
if (Test-Path $envFile) {
    Ok "kept your .env"
} else {
    Copy-Item (Join-Path $Repo ".env.example") $envFile
    Ok "created .env (empty: keys are only needed for Telegram and the cloud fallback)"
}

Step "Environment variables (this user only)"
[Environment]::SetEnvironmentVariable("ROSIE_CONFIG", $config, "User")
[Environment]::SetEnvironmentVariable("ROSIE_CORE", $rosie, "User")
$env:ROSIE_CONFIG = $config
$env:ROSIE_CORE = $rosie
Ok "ROSIE_CONFIG = $config"
Ok "ROSIE_CORE   = $rosie"

Step "rosie-vault"
& $rosie vault
if ($LASTEXITCODE -ne 0) { Note "vault set up locally; git sync will retry later" } else { Ok "ready" }

if (-not $SkipDoctor) {
    Step "Health check"
    & $rosie doctor
    if ($LASTEXITCODE -ne 0) { Note "fix the [fail] lines above (often: start Ollama), then run: $rosie doctor" }
}

Step "The orb"
if ($Orb) {
    foreach ($tool in @("npm", "cargo")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "$tool not found: the orb needs Node.js and Rust (see docs\UI.md)"
        }
    }
    Push-Location (Join-Path $Repo "ui")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        npm run tauri build
        if ($LASTEXITCODE -ne 0) { throw "orb build failed" }
    } finally { Pop-Location }
    $setup = Get-ChildItem (Join-Path $Repo "ui\src-tauri\target\release\bundle\nsis") -Filter *.exe |
        Select-Object -First 1
    Ok "installer: $($setup.FullName) (run it once; Rosie then opens at login)"
} else {
    Note "skipped. To build it: install Rust and Node.js, then run this script with -Orb"
}

Write-Host "`nDone. Talk to Rosie: $rosie chat" -ForegroundColor Green
