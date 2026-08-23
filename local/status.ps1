$ErrorActionPreference = "Stop"

$ModelsPath = Join-Path $PSScriptRoot "models"
$env:OLLAMA_MODELS = $ModelsPath

Write-Host "aib local status"
Write-Host "Models path: $ModelsPath"

if (Test-Path $ModelsPath) {
    $Bytes = (Get-ChildItem -Path $ModelsPath -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $Bytes) { $Bytes = 0 }
    $SizeGB = [Math]::Round($Bytes / 1GB, 2)
    Write-Host "Storage used: $SizeGB GB"
}
else {
    Write-Host "Storage used: 0 GB (models directory does not exist yet)"
}

Write-Host ""
$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $OllamaCommand) {
    Write-Host "Ollama: not installed or not in PATH"
    exit 0
}

try {
    $Version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2
    Write-Host "Ollama: running, version $($Version.version)"
}
catch {
    Write-Host "Ollama: installed, server is not running"
}

Write-Host ""
Write-Host "Installed models:"
& ollama list
