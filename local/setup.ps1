$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ModelsPath = Join-Path $PSScriptRoot "models"
$ModelsList = Join-Path $PSScriptRoot "models.txt"
$Requirements = Join-Path $RepoRoot "requirements.txt"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DefaultModelsPath = Join-Path $env:USERPROFILE ".ollama\models"

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

function Get-DirectorySizeBytes([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $Bytes = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $Bytes) { return 0 }
    return [int64]$Bytes
}

function Stop-AllOllamaProcesses {
    $Processes = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "ollama*" }
    if ($Processes) {
        Write-Host "Stopping Ollama desktop/server processes..."
        $Processes | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

Write-Host "aib local setup"
Write-Host "Repository: $RepoRoot"
Write-Host "Models:     $ModelsPath"

New-Item -ItemType Directory -Force -Path $ModelsPath | Out-Null

# Ollama 0.32.x Windows desktop currently has a known issue where the app can
# override OLLAMA_MODELS. aib therefore uses the CLI server (`ollama serve`)
# and keeps the desktop app stopped while the local service is running.
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

Stop-AllOllamaProcesses

# If the Windows desktop app already downloaded models to the default C: path,
# reuse them instead of downloading ~11 GB again. The source is intentionally
# left in place until the J: copy has been verified.
$TargetBytes = Get-DirectorySizeBytes $ModelsPath
$DefaultBytes = Get-DirectorySizeBytes $DefaultModelsPath
if (($TargetBytes -eq 0) -and ($DefaultBytes -gt 0) -and ($DefaultModelsPath -ne $ModelsPath)) {
    $DefaultGB = [Math]::Round($DefaultBytes / 1GB, 2)
    Write-Host ""
    Write-Host "Found $DefaultGB GB of Ollama models in the default Windows location:"
    Write-Host "$DefaultModelsPath"
    Write-Host "Copying them to J: so they do not need to be downloaded again..."

    & robocopy $DefaultModelsPath $ModelsPath /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP
    $RoboCode = $LASTEXITCODE
    if ($RoboCode -ge 8) {
        throw "Failed to copy existing Ollama models to $ModelsPath (robocopy exit code $RoboCode)."
    }

    $TargetBytes = Get-DirectorySizeBytes $ModelsPath
    if ($TargetBytes -eq 0) {
        throw "Model migration finished but $ModelsPath is still empty."
    }
    Write-Host "Existing models copied to J:. The original C: copy is kept for now."
}

Write-Host "Starting Ollama CLI server with model storage: $ModelsPath"
$OllamaProcess = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru

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
Write-Host "Ollama CLI server PID: $($OllamaProcess.Id)"

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
Write-Host "Checking initial models in: $ModelsPath"
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

$Bytes = Get-DirectorySizeBytes $ModelsPath
$SizeGB = [Math]::Round($Bytes / 1GB, 2)

Write-Host ""
Write-Host "Setup complete."
Write-Host "Model storage used on J: $SizeGB GB"
if ($DefaultBytes -gt 0) {
    Write-Host "Old default model storage may still exist at: $DefaultModelsPath"
    Write-Host "Do not delete it until local\status.ps1 confirms the J: models are visible."
}
Write-Host ""
Write-Host "Start aib with:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\local\start.ps1"
