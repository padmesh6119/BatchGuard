$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found. Install Python 3.11 or newer and enable 'Add Python to PATH'."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not prepare pip." }

& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

& $venvPython refresh_data.py
if ($LASTEXITCODE -ne 0) { throw "Data refresh failed. Read the error above; do not use stale outputs." }

& $venvPython -m streamlit run app.py
if ($LASTEXITCODE -ne 0) { throw "BatchGuard dashboard stopped with an error." }
