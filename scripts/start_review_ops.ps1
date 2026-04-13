param(
    [switch]$OpenBrowser = $true,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($ArgumentList -join ' ')"
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runDir = Join-Path $repoRoot ".run"
if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir | Out-Null
}

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repoRoot ".env.example") $envFile
    Write-Host "Created .env from .env.example. You can edit it later if needed."
}

$venvDir = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$pipExe = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating virtual environment..."
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $created = $false
        foreach ($version in @("-3.13", "-3.14", "-3")) {
            try {
                & py $version -m venv $venvDir
                if (Test-Path $pythonExe) {
                    $created = $true
                    break
                }
            } catch {
            }
        }
        if (-not $created) {
            throw "Unable to create virtual environment with the installed Python launcher versions."
        }
    } else {
        python -m venv $venvDir
    }
}

Write-Host "Installing dependencies..."
Invoke-Checked -FilePath $pythonExe -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -FilePath $pipExe -ArgumentList @("install", "-e", ".")

$playwrightMarker = Join-Path $runDir "playwright.ready"
if (-not (Test-Path $playwrightMarker)) {
    Write-Host "Installing Playwright browser..."
    Invoke-Checked -FilePath $pythonExe -ArgumentList @("-m", "playwright", "install", "chromium")
    Set-Content -Path $playwrightMarker -Value (Get-Date).ToString("s")
}

$dockerAvailable = $false
try {
    docker version | Out-Null
    $dockerAvailable = $true
} catch {
    Write-Warning "Docker Desktop is not available. PostgreSQL and Redis must already be running."
}

if ($dockerAvailable) {
    Write-Host "Starting PostgreSQL and Redis..."
    docker compose up -d postgres redis | Out-Host
}

Write-Host "Running database migrations..."
$alembicExe = Join-Path $venvDir "Scripts\alembic.exe"
Invoke-Checked -FilePath $alembicExe -ArgumentList @("upgrade", "head")

Write-Host "Seeding locations..."
Invoke-Checked -FilePath $pythonExe -ArgumentList @("-m", "scripts.seed_locations")

$webPidPath = Join-Path $runDir "web.pid"
$webLogPath = Join-Path $runDir "web.log"
$webErrPath = Join-Path $runDir "web.err.log"

if (Test-Path $webPidPath) {
    $existingPid = Get-Content $webPidPath -ErrorAction SilentlyContinue
    if ($existingPid) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Host "Review Ops is already running at http://127.0.0.1:$Port"
            if ($OpenBrowser) {
                Start-Process "http://127.0.0.1:$Port"
            }
            exit 0
        }
    }
}

Write-Host "Starting Review Ops web app..."
$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $repoRoot `
    -PassThru `
    -WindowStyle Normal `
    -RedirectStandardOutput $webLogPath `
    -RedirectStandardError $webErrPath

Set-Content -Path $webPidPath -Value $process.Id

Start-Sleep -Seconds 4

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$Port"
}

Write-Host ""
Write-Host "Review Ops started."
Write-Host "URL: http://127.0.0.1:$Port"
Write-Host "PID: $($process.Id)"
Write-Host "Logs: $webLogPath"
