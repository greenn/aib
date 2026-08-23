$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ModelsPath = Join-Path $PSScriptRoot "models"
$ModelsList = Join-Path $PSScriptRoot "models.txt"
$Requirements = Join-Path $RepoRoot "requirements.txt"
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

function Resolve-PythonExecutable {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) {
        return @{ File = $Command.Source; Prefix = @() }
    }

    $PyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($PyCommand) {
        return @{ File = $PyCommand.Source; Prefix = @("-3") }
    }

    return $null
}

Write-Host "aib local setup"
Write-Host "Repository: $RepoRoot"
Write-Host "Models:     $ModelsPath"

New-Item -ItemType Directory -Force -Path $ModelsPath | Out-Null

# Keep all Ollama model data on the same drive as this repository.
$env:OLLAMA_MODELS = $ModelsPath
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsPath, "User")
Write-Host "OLLAMA_MODELS set for current user: $ModelsPath"

$OllamaExe = Resolve-OllamaExecutable
if (-not $OllamaExe) {
    Write-Host ""
    Write-Host "Ollama is not installed or ollama.exe could not be found."
    Write-Host "Install it first, then run this script again."
    Write-Host "Windows package command: winget install Ollama.Ollama"
    exit 1
}
Write-Host "Ollama:     $OllamaExe"

$Python = Resolve-PythonExecutable
if (-not $Python) {
    Write-Host "Python is not available. Install Python 3 and run this script again."
    exit 1
}

# Ollama must be restarted after OLLAMA_MODELS changes, otherwise a previously
# running process can keep using its old model-storage directory.
$ExistingOllama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if ($ExistingOllama) {
    Write-Host "Restarting Ollama so it uses: $ModelsPath"
    $ExistingOllama | Stop-Process -Force
    Start-Sleep -Seconds 2
}

Write-Host "Starting Ollama..."
Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden

$Ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null
        $Ready = $true
        break
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $Ready) {
    throw "Ollama did not become ready at http://127.0.0.1:11434"
}

Write-Host "Creating Python virtual environment..."
if (-not (Test-Path $VenvPython)) {
    $PythonArgs = @($Python.Prefix) + @("-m", "venv", (Join-Path $RepoRoot ".venv"))
    & $Python.File @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Python virtual environment."
    }
}

Write-Host "Installing API dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Requirements

Write-Host ""
Write-Host "Downloading initial models to: $ModelsPath"
$Models = Get-Content $ModelsList | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") }
foreach ($Model in $Models) {
    $Name = $Model.Trim()
    Write-Host ""
    Write-Host "=== ollama pull $Name ==="
    & $OllamaExe pull $Name
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download model: $Name"
    }
}

$Bytes = (Get-ChildItem -Path $ModelsPath -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
if ($null -eq $Bytes) { $Bytes = 0 }
$SizeGB = [Math]::Round($Bytes / 1GB, 2)

Write-Host ""
Write-Host "Setup complete."
Write-Host "Model storage used: $SizeGB GB"
Write-Host ""
Write-Host "Start aib with:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\local\start.ps1"
