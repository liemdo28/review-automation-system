param(
    [switch]$OpenBrowser = $true,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Stopping existing START process if running..."
& "$repoRoot\\stop.bat" 2>$null

Write-Host "Pulling latest code..."
git pull --ff-only origin master

$venvDir = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\\python.exe"
$alembicExe = Join-Path $venvDir "Scripts\\alembic.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Virtual environment missing, running start script to create it..."
    & "$repoRoot\\start.bat"
    exit 0
}

Write-Host "Applying database migrations..."
& $alembicExe upgrade head
if ($LASTEXITCODE -ne 0) {
    throw "Alembic upgrade failed."
}

Write-Host "Starting START..."
& "$repoRoot\\start.bat"
