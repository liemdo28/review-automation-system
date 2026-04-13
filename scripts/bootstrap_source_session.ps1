param(
    [Parameter(Mandatory = $true)]
    [int]$SourceId,
    [string]$ShareScope = "source",
    [Parameter(Mandatory = $true)]
    [string]$Platform,
    [Parameter(Mandatory = $true)]
    [string]$SourceUrl,
    [Parameter(Mandatory = $true)]
    [string]$SourceLabel,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$Host.UI.RawUI.WindowTitle = "START Login - $SourceLabel [$Platform]"

$pythonExe = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment is missing. Run start.bat once before launching session bootstrap."
}

Write-Host ""
Write-Host "START session bootstrap"
Write-Host "Source: $SourceLabel ($Platform)"
Write-Host "Review page: $SourceUrl"
Write-Host "Session file: $OutputPath"
Write-Host ""

& $pythonExe "scripts\\bootstrap_source_session.py" `
    --source-id $SourceId `
    --share-scope $ShareScope `
    --platform $Platform `
    --source-url $SourceUrl `
    --source-label $SourceLabel `
    --output-path $OutputPath `
    --api-base-url $ApiBaseUrl

if ($LASTEXITCODE -ne 0) {
    throw "Session bootstrap failed."
}
