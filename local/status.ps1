$ErrorActionPreference = "Stop"

$ModelsPath = Join-Path $PSScriptRoot "models"
$env:OLLAMA_MODELS = $ModelsPath

function Resolve-OllamaExecutable {
    $Command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:LOCALAPPDATA "Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )

    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path $Candidate)) {
            return $Candidate
        }
    }

    return $null
}

Write-Host "aib local status"
Write-Host "Models path: $ModelsPath"

if (Test-Path $ModelsPath) {
    $Bytes = (Get-ChildItem -Path $ModelsPath -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $Bytes) { $Bytes = 0 }
    $SizeGB = [Math]::Round($Bytes / 1GB, 2)
    Write-Host "Storage used on J: $SizeGB GB"
}
else {
    Write-Host "Storage used on J: 0 GB (models directory does not exist yet)"
}

$OllamaExe = Resolve-OllamaExecutable
if (-not $OllamaExe) {
    Write-Host "Ollama: not installed"
    exit 0
}
Write-Host "Ollama executable: $OllamaExe"

try {
    $Version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2
    Write-Host "Ollama server: running, version $($Version.version)"

    $Tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    Write-Host ""
    Write-Host "Models visible to the running server:"
    if ($Tags.models) {
        $Tags.models | ForEach-Object {
            $GB = [Math]::Round($_.size / 1GB, 2)
            Write-Host "  $($_.name) - $GB GB"
        }
    }
    else {
        Write-Host "  (none)"
    }
}
catch {
    Write-Host "Ollama server: not running"
    Write-Host "Run .\local\start.ps1 or .\local\setup.ps1."
}
