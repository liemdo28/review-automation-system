$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot ".run"
$webPidPath = Join-Path $runDir "web.pid"

if (Test-Path $webPidPath) {
    $appPid = Get-Content $webPidPath -ErrorAction SilentlyContinue
    if ($appPid) {
        $process = Get-Process -Id $appPid -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $appPid -Force
            Write-Host "Stopped Review Ops process $appPid"
        }
    }
    Remove-Item $webPidPath -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "No running Review Ops PID file found."
}
