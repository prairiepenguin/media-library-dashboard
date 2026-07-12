$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
Set-Location $Project

if (-not (Test-Path ".venv\Scripts\media-library-sync.exe")) {
    py -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -e .
}

.venv\Scripts\media-library-sync.exe --project $Project --music-root "M:\" --push *>> "$Project\nightly-sync.log"
