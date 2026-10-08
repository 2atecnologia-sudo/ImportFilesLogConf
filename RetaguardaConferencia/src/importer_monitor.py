"""Verifica e inicia o executável do importador, sem alterar seus arquivos."""
import json
import os
import subprocess
from pathlib import Path
from .importer_config import locate
from .license import License


def processes(executable_name="ImportFilesLogConfImporter.exe"):
    if executable_name not in ("ImportFilesLogConfImporter.exe","ImportFilesLogConfTray.exe"):raise ValueError("Executável inválido.")
    script=f"@(Get-CimInstance Win32_Process -Filter \"Name = '{executable_name}'\" -ErrorAction Stop | Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('Não foi possível verificar o processo do monitor.')
    values=json.loads(result.stdout.strip() or '[]')
    return [values] if isinstance(values,dict) else values


def ensure_running(base,folder=None):
    if os.name!='nt':return 'stopped','Inicialização automática disponível no Windows.'
    current=processes()
    installation=Path(folder) if folder else locate(base)
    options=[installation/'ImportFilesLogConfImporter.exe',installation/'ImportFilesLogConfImporter'/'ImportFilesLogConfImporter.exe']
    executable=next((p for p in options if p.is_file()),None)
    if executable is None:return 'stopped','Executável do monitor não encontrado na instalação configurada.'
    matches=lambda entries:any(p.get('ExecutablePath') and os.path.normcase(os.path.abspath(p['ExecutablePath']))==os.path.normcase(str(executable.resolve())) for p in entries)
    if matches(current):return 'running','Monitor em execução.'
    if current:return 'stopped','Existe um monitor em outra instalação ou sem caminho acessível. Não foi aberta outra cópia.'
    License().check(installation)
    # Reconsulta imediatamente antes da partida para evitar duplicação com o Tray.
    current=processes()
    if matches(current):return 'running','Monitor em execução.'
    if current:return 'stopped','Outro processo do monitor foi detectado. Não foi aberta outra cópia.'
    subprocess.Popen([str(executable)],cwd=str(executable.parent),creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'CREATE_NO_WINDOW',0),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return 'starting','Monitor iniciado automaticamente; aguardando confirmação na próxima verificação.'


def open_tray(base,folder=None):
    if os.name!='nt':raise RuntimeError('O Tray está disponível no Windows.')
    if processes('ImportFilesLogConfTray.exe'):
        return 'O Tray já está aberto. Procure o ícone nos ícones ocultos da bandeja do Windows.'
    installation=Path(folder) if folder else locate(base)
    options=[installation/'ImportFilesLogConfTray.exe',installation/'ImportFilesLogConfTray'/'ImportFilesLogConfTray.exe',installation.parent/'ImportFilesLogConfTray.exe',installation.parent/'ImportFilesLogConfTray'/'ImportFilesLogConfTray.exe']
    executable=next((p for p in options if p.is_file()),None)
    if executable is None:raise RuntimeError('ImportFilesLogConfTray.exe não encontrado junto à instalação do importador.')
    subprocess.Popen([str(executable)],cwd=str(executable.parent),creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'CREATE_NO_WINDOW',0))
    return 'Tray iniciado. O ícone aparecerá na bandeja do Windows ou nos ícones ocultos.'
