"""Localização automática, somente leitura, da instalação do importador."""
import os, subprocess, json
from pathlib import Path

def candidates(base):
    base=Path(base)
    paths=[]
    # A instalação em execução tem prioridade sobre as cópias de desenvolvimento.
    if os.name=='nt':
        try:
            script="Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('ImportFilesLogConfImporter.exe','ImportFilesLogConfTray.exe','ImportFilesLogConfConfig.exe') } | Select-Object -ExpandProperty ExecutablePath | ConvertTo-Json -Compress"
            result=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            values=json.loads(result.stdout or '[]')
            if isinstance(values,str):values=[values]
            for value in values:
                if value:paths.append(Path(value).parent)
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
    active=list(dict.fromkeys(paths))
    roots=[Path(r'C:\2atec\ImportFilesLogConf'),Path(r'C:\Projetos2\ImportFilesLogConf'),Path(r'C:\Projetos\ImportFilesLogConf'),Path(r'C:\projetos\importfileslogconf')]
    roots.extend(parent/'ImportFilesLogConf' for parent in [base,*list(base.parents)[:4]])
    for root in roots:
        paths.extend([root/'dist',root/'dist'/'ImportFilesLogConfImporter',root/'dist'/'ImportFilesLogConfTray',root,root/'config'])
    return active,list(dict.fromkeys(paths))

def locate(base):
    active,paths=candidates(base)
    valid=lambda p:(p/'config.ini').is_file()
    installed=[p for p in active if valid(p)]
    if len(installed)==1:return installed[0]
    if len(installed)>1:
        raise RuntimeError('Há mais de uma instalação do importador em execução. Mantenha apenas a instalação que deseja acompanhar.')
    found=[p for p in paths if valid(p)]
    licensed=[p for p in found if (p/'licenci.ini').is_file()]
    if len(licensed)==1:return licensed[0]
    if len(found)==1:return found[0]
    if not found:raise RuntimeError('Configuração do importador não localizada. Abra o ImportFilesLogConf nesta máquina e clique em Atualizar.')
    raise RuntimeError('Foram encontradas várias configurações do importador. Abra o ImportFilesLogConf que está em uso para identificar automaticamente a instalação correta.')
