param(
    [switch]$OpenBrowser = $true,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runDir = Join-Path $repoRoot ".run"
if (-not (Test-Path $runDir)) {
    New-Item -ItemType Directory -Path $runDir | Out-Null
}
$errorLog = Join-Path $runDir "fix.err.log"

function Wait-ForTcpPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Host,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$TimeoutSeconds = 45,
        [string]$Label = "service"
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $task = $client.ConnectAsync($Host, $Port)
            if ($task.Wait(1000) -and $client.Connected) {
                $client.Close()
                return
            }
            $client.Close()
        } catch {
        }
        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for $Label on $Host`:$Port"
}

try {
    if (Test-Path $errorLog) {
        Remove-Item $errorLog -Force
    }

    Write-Host "Stopping existing START process if running..."
    & "$repoRoot\\stop.bat" 2>$null

    Write-Host "Pulling latest code..."
    git pull --ff-only origin master

    Write-Host "Ensuring PostgreSQL + Redis are running..."
    $dockerAvailable = $false
    $dockerError = $null
    try {
        docker version | Out-Null
        $dockerAvailable = $true
    } catch {
        $dockerError = $_ | Out-String
        $dockerAvailable = $false
    }

    if (-not $dockerAvailable) {
        throw "Docker Desktop is not running. Start Docker Desktop and re-run fix-and-start.`n$dockerError"
    }

    docker compose up -d postgres redis | Out-Null
    Wait-ForTcpPort -Host "127.0.0.1" -Port 5432 -Label "PostgreSQL"
    Wait-ForTcpPort -Host "127.0.0.1" -Port 6379 -Label "Redis"

    $venvDir = Join-Path $repoRoot ".venv"
    $pythonExe = Join-Path $venvDir "Scripts\\python.exe"
    $alembicExe = Join-Path $venvDir "Scripts\\alembic.exe"
    $pipExe = Join-Path $venvDir "Scripts\\pip.exe"

    if (-not (Test-Path $pythonExe)) {
        Write-Host "Virtual environment missing, running start script to create it..."
        & "$repoRoot\\start.bat"
        exit 0
    }

    if (-not (Test-Path $alembicExe)) {
        Write-Host "Alembic missing in virtual environment, reinstalling dependencies..."
        & $pythonExe -m pip install --upgrade pip
        & $pipExe install -e .
    }

    Write-Host "Applying database migrations..."
    & $alembicExe upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic upgrade failed."
    }

    Write-Host "Starting START..."
    & "$repoRoot\\start.bat"
} catch {
    $message = $_.Exception.Message
    $details = $_ | Out-String
    "ERROR: $message" | Set-Content -Path $errorLog
    $details | Add-Content -Path $errorLog
    Write-Host "Fix-and-start failed. See $errorLog"
    exit 1
}
