"""Limpeza explícita dos dados de conferência, em uma transação SQL."""
import subprocess
from contextlib import closing
from .data import connection
from .importer_monitor import processes

TABLES=('LancamentoExternoStatus','scanerroconf','scanocorconf','RespostasSync','prodConf','logConf')

def preview(folder):
    with closing(connection(folder)) as conn:
        cur=conn.cursor();server,database=cur.execute('SELECT @@SERVERNAME, DB_NAME()').fetchone();counts={}
        for table in TABLES:
            if cur.execute("SELECT OBJECT_ID(?, 'U')",('dbo.'+table,)).fetchone()[0] is not None:
                counts[table]=cur.execute('SELECT COUNT_BIG(*) FROM dbo.['+table+']').fetchone()[0]
        return str(server),str(database),counts

def clear(folder):
    # Não limpa enquanto o importador/Tray puder gravar ou reiniciar a importação.
    active=processes()+processes('ImportFilesLogConfTray.exe')
    from pathlib import Path
    import os
    root=os.path.normcase(str(Path(folder).resolve()))
    for process in active:
        path=process.get('ExecutablePath')
        if not path or os.path.normcase(str(Path(path).resolve().parent))!=root:
            raise RuntimeError('Há processo do importador/Tray fora da instalação selecionada ou sem caminho acessível. Feche-o antes de zerar.')
    ids=[int(p['ProcessId']) for p in active]
    if ids:
        command='Stop-Process -Id '+','.join(map(str,ids))+' -Force -ErrorAction Stop'
        result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('Não foi possível encerrar o importador/Tray; nenhum dado foi apagado.')
    if processes() or processes('ImportFilesLogConfTray.exe'):raise RuntimeError('O importador/Tray continua rodando. Nenhum dado foi apagado.')
    with closing(connection(folder)) as conn:
        try:
            cur=conn.cursor();cur.execute('SET XACT_ABORT ON');deleted=[]
            for table in TABLES:
                if cur.execute("SELECT OBJECT_ID(?, 'U')",('dbo.'+table,)).fetchone()[0] is not None:
                    cur.execute('DELETE FROM dbo.['+table+']');deleted.append(table)
            conn.commit();return ', '.join(deleted)
        except Exception:
            conn.rollback();raise
