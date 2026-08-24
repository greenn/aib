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

function Stop-AllOllamaProcesses {
    $Processes = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "ollama*" }
    if ($Processes) {
        Write-Host "Stopping other Ollama desktop/server processes..."
        $Processes | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

$env:OLLAMA_MODELS = $ModelsPath

if (-not (Test-Path $VenvPython)) {
    Write-Host "Python environment is not ready. Run .\local\setup.ps1 first."
    exit 1
}

$OllamaExe = Resolve-OllamaExecutable
if (-not $OllamaExe) {
    Write-Host "Ollama is not available. Run .\local\setup.ps1 first."
    exit 1
}

# Do not trust an already-running Windows desktop server: Ollama 0.32.x can
# ignore OLLAMA_MODELS there. Start our own CLI server so J: is guaranteed.
Stop-AllOllamaProcesses
Write-Host "Starting Ollama CLI server with model storage: $ModelsPath"
$OllamaProcess = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru

$OllamaReady = $false
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

if (-not $OllamaReady) {
    throw "Ollama did not become ready."
}

Set-Location $RepoRoot
Write-Host "Ollama PID: $($OllamaProcess.Id)"
Write-Host "aib API: http://127.0.0.1:8181"
Write-Host "API docs: http://127.0.0.1:8181/docs"
Write-Host "Press Ctrl+C to stop the API."

& $VenvPython -m uvicorn api.main:app --host 127.0.0.1 --port 8181
