$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ModelsPath = Join-Path $PSScriptRoot "models"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

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

$env:OLLAMA_MODELS = $ModelsPath

if (-not (Test-Path $VenvPython)) {
    Write-Host "Python environment is not ready. Run .\local\setup.ps1 first."
    exit 1
}

$OllamaReady = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
    $OllamaReady = $true
}
catch {
    $OllamaReady = $false
}

if (-not $OllamaReady) {
    $OllamaExe = Resolve-OllamaExecutable
    if (-not $OllamaExe) {
        Write-Host "Ollama is not available. Run .\local\setup.ps1 first."
        exit 1
    }

    Write-Host "Starting Ollama with model storage: $ModelsPath"
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden

    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
            $OllamaReady = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
}

if (-not $OllamaReady) {
    throw "Ollama did not become ready."
}

Set-Location $RepoRoot
Write-Host "aib API: http://127.0.0.1:8181"
Write-Host "API docs: http://127.0.0.1:8181/docs"
Write-Host "Press Ctrl+C to stop the API."

& $VenvPython -m uvicorn api.main:app --host 127.0.0.1 --port 8181
