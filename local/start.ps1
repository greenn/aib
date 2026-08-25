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

function Test-LocalPort([int]$Port) {
    $Listener = $null
    try {
        $Address = [System.Net.IPAddress]::Parse("127.0.0.1")
        $Listener = [System.Net.Sockets.TcpListener]::new($Address, $Port)
        $Listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $Listener) {
            try { $Listener.Stop() } catch {}
        }
    }
}

function Resolve-AibPort {
    if ($env:AIB_PORT) {
        $RequestedPort = [int]$env:AIB_PORT
        if (-not (Test-LocalPort $RequestedPort)) {
            throw "AIB_PORT=$RequestedPort cannot be bound on 127.0.0.1. Choose another port."
        }
        return $RequestedPort
    }

    # 8282 is preferred for compatibility. Other candidates are deliberately
    # spread out because Windows/Hyper-V can reserve whole port ranges.
    $Candidates = @(8282, 8181, 8383, 8484, 8585, 8686, 8787, 8888, 8989, 9080, 9180)
    foreach ($Candidate in $Candidates) {
        if (Test-LocalPort $Candidate) {
            return $Candidate
        }
    }

    throw "Could not find a bindable local port for aib."
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

$Port = Resolve-AibPort
$BaseUrl = "http://127.0.0.1:$Port"

Set-Location $RepoRoot
Write-Host "Ollama PID: $($OllamaProcess.Id)"
Write-Host "aib API: $BaseUrl"
Write-Host "API docs: $BaseUrl/docs"
if ($Port -ne 8282) {
    Write-Host "Note: port 8282 is unavailable/reserved; using $Port instead."
}
Write-Host "Press Ctrl+C to stop the API."

& $VenvPython -m uvicorn api.main:app --host 127.0.0.1 --port $Port
