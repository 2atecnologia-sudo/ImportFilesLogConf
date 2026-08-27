$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$versao = "1.0.3"
$dataBuild = Get-Date -Format "dd/MM/yyyy HH:mm"

@"
APP_VERSION = "$versao"
BUILD_DATE = "$dataBuild"
"@ | Set-Content -Path ".\src\build_info.py" -Encoding UTF8

Write-Host "Gerando versao $versao | Build $dataBuild"

python -m PyInstaller --clean ImportFilesLogConfTray.spec
python -m PyInstaller --clean ImportFilesLogConfConfig.spec
python -m PyInstaller --clean ImportFilesLogConfImporter.spec

Write-Host ""
Write-Host "Build concluido: $versao | $dataBuild"
Write-Host "Gerados:"
Write-Host " - ImportFilesLogConfTray.exe"
Write-Host " - ImportFilesLogConfConfig.exe"
Write-Host " - ImportFilesLogConfImporter.exe"
