$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (!(Test-Path '.venv\Scripts\python.exe')) { py -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente' } }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --windowed --onedir --name RetaguardaConferencia --collect-all cryptography run.py
if ($LASTEXITCODE -ne 0) { throw 'Falha no build' }
Write-Host 'Pronto: dist\RetaguardaConferencia\RetaguardaConferencia.exe'
