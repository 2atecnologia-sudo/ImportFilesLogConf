import os
import subprocess
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox

import pystray
from PIL import Image

from .runtime_status import read_runtime_status, write_runtime_status
from .settings import load_settings
from .db import get_connection
from .sql_diagnostics import diagnosticar_erro_sql
from .single_instance import SingleInstance


APP_NAME = "ImportFilesLogConf"

# Em desenvolvimento: raiz do projeto.
# Compilado pelo PyInstaller: pasta onde está o EXE.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )

IMPORTER_EXE = os.path.join(
    BASE_DIR,
    "ImportFilesLogConfImporter.exe"
)

CONFIG_EXE = os.path.join(
    BASE_DIR,
    "ImportFilesLogConfConfig.exe"
)

_importer_proc = None


def make_icon(rgb):
    return Image.new("RGB", (64, 64), rgb)


def importer_running():
    global _importer_proc

    return (
        _importer_proc is not None
        and _importer_proc.poll() is None
    )


def _mostrar_mensagem(titulo: str, mensagem: str, tipo: str = "info"):
    root = tk.Tk()
    root.withdraw()

    try:
        if tipo == "error":
            messagebox.showerror(titulo, mensagem)
        elif tipo == "warning":
            messagebox.showwarning(titulo, mensagem)
        else:
            messagebox.showinfo(titulo, mensagem)
    finally:
        root.destroy()


def refresh(icon):
    """
    Mantém o Tray em três estados visuais:
      - VERDE: Importer rodando e sem erro ativo.
      - VERMELHO: Importer rodando, mas existe erro SQL ativo.
      - CINZA: Importer parado.

    A espera normal pelo segundo arquivo do par não é tratada como erro.
    """
    status = read_runtime_status(BASE_DIR)

    if not importer_running():
        icon.icon = make_icon((128, 128, 128))
        icon.title = f"{APP_NAME} - IMPORTADOR PARADO"
        return

    if status.get("estado") == "SQL_PENDENTE":
        titulo = status.get("titulo") or "SQL indisponível"
        icon.icon = make_icon((220, 38, 38))
        icon.title = f"{APP_NAME} - ERRO: {titulo}"
        return

    icon.icon = make_icon((46, 160, 67))

    if status.get("estado") == "OK":
        icon.title = f"{APP_NAME} - OPERANDO NORMALMENTE | SQL OK"
    else:
        icon.title = f"{APP_NAME} - OPERANDO NORMALMENTE"


def start_importer(icon, item=None):
    global _importer_proc

    if importer_running():
        refresh(icon)
        return

    icon.icon = make_icon((245, 158, 11))
    icon.title = f"{APP_NAME} - INICIANDO..."

    creationflags = 0

    if os.name == "nt":
        creationflags = (
            getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0
            )
            |
            getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

    if getattr(sys, "frozen", False):
        if not os.path.exists(IMPORTER_EXE):
            raise FileNotFoundError(
                f"Importador não encontrado: {IMPORTER_EXE}"
            )

        comando = [IMPORTER_EXE]
    else:
        comando = [
            sys.executable,
            "-m",
            "src.main",
        ]

    _importer_proc = subprocess.Popen(
        comando,
        cwd=BASE_DIR,
        creationflags=creationflags,
    )

    time.sleep(0.7)
    refresh(icon)


def stop_importer(icon, item=None):
    global _importer_proc

    if not importer_running():
        _importer_proc = None
        refresh(icon)
        return

    proc = _importer_proc

    try:
        if os.name == "nt":
            # PyInstaller --onefile pode criar processo pai/filho com o mesmo EXE.
            # /T encerra toda a árvore iniciada pelo Importer.
            subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(proc.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
                check=False,
            )
        else:
            proc.terminate()

            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    finally:
        _importer_proc = None
        refresh(icon)


def restart_importer(icon, item=None):
    stop_importer(icon, item)
    time.sleep(0.3)
    start_importer(icon, item)


def _abrir_configuracao(aba_status=False):
    if getattr(sys, "frozen", False):
        if not os.path.exists(CONFIG_EXE):
            _mostrar_mensagem(
                APP_NAME,
                f"Configuração não encontrada:\n{CONFIG_EXE}",
                "error",
            )
            return

        comando = [CONFIG_EXE]

        if aba_status:
            comando.append("--status")
    else:
        comando = [
            sys.executable,
            "-m",
            "src.config_ui",
        ]

        if aba_status:
            comando.append("--status")

    subprocess.Popen(
        comando,
        cwd=BASE_DIR,
    )


def open_config(icon, item=None):
    _abrir_configuracao(aba_status=False)


def show_status(icon, item=None):
    refresh(icon)
    _abrir_configuracao(aba_status=True)


def open_logs(icon, item=None):
    log_dir = os.path.join(BASE_DIR, "logs")

    os.makedirs(
        log_dir,
        exist_ok=True
    )

    os.startfile(log_dir)


def open_input_folder(icon, item=None):
    s = load_settings()

    os.makedirs(
        s.watch.input_dir,
        exist_ok=True
    )

    os.startfile(
        s.watch.input_dir
    )


def _texto_status():
    s = load_settings()
    runtime = read_runtime_status(BASE_DIR)

    linhas = [
        f"Importador: {'RODANDO' if importer_running() else 'PARADO'}",
        f"Formato: {s.app.input_format}",
        f"Pasta entrada: {s.watch.input_dir}",
        f"Servidor SQL: {s.sql.server}",
        f"Banco: {s.sql.database}",
    ]

    if runtime:
        linhas.append("")

        estado = runtime.get("estado", "")

        if estado == "SQL_PENDENTE":
            linhas.append("SQL Server: INDISPONÍVEL")
        elif estado == "OK":
            linhas.append("SQL Server: OK")
        else:
            linhas.append(f"Estado: {estado or 'não informado'}")

        titulo = runtime.get("titulo", "")
        tipo = runtime.get("tipo", "")
        codigo = runtime.get("codigo", "")
        coletor = runtime.get("coletor", "")
        mensagem = runtime.get("mensagem", "")
        orientacao = runtime.get("orientacao", "")
        atualizado = runtime.get("updated_at", "")

        if titulo:
            linhas.append(f"Situação: {titulo}")

        if tipo:
            linhas.append(f"Tipo: {tipo}")

        if codigo:
            linhas.append(f"Código: {codigo}")

        if coletor:
            linhas.append(f"Coletor: {coletor}")

        if atualizado:
            linhas.append(f"Última atualização: {atualizado}")

        if mensagem:
            linhas.append("")
            linhas.append("Detalhe:")
            linhas.append(mensagem)

        if orientacao:
            linhas.append("")
            linhas.append("O que verificar:")
            linhas.append(orientacao)

    return "\n".join(linhas)


def _testar_conexao_worker(icon, mostrar_sucesso=True):
    s = load_settings()

    try:
        conn = get_connection(s.sql)
        conn.close()

        write_runtime_status(
            BASE_DIR,
            {
                "estado": "OK",
                "titulo": "SQL Server acessível",
                "mensagem": "Conexão com SQL Server realizada com sucesso.",
                "orientacao": "",
            },
        )

        refresh(icon)

        if mostrar_sucesso:
            _mostrar_mensagem(
                APP_NAME,
                "Conexão com SQL Server realizada com sucesso.",
                "info",
            )

        return True

    except Exception as e:
        diagnostico = diagnosticar_erro_sql(e)

        write_runtime_status(
            BASE_DIR,
            {
                "estado": "SQL_PENDENTE",
                "titulo": diagnostico["titulo"],
                "tipo": diagnostico["tipo"],
                "codigo": diagnostico["codigo"],
                "mensagem": diagnostico["mensagem"],
                "orientacao": diagnostico["orientacao"],
            },
        )

        refresh(icon)

        msg = (
            f"{diagnostico['titulo']}\n\n"
            f"Código: {diagnostico['codigo'] or '-'}\n\n"
            f"O que verificar:\n"
            f"{diagnostico['orientacao']}"
        )

        _mostrar_mensagem(
            APP_NAME,
            msg,
            "error",
        )

        return False


def test_sql_connection(icon, item=None):
    threading.Thread(
        target=_testar_conexao_worker,
        args=(icon, True),
        daemon=True,
    ).start()


def _reprocessar_worker(icon):
    # Primeiro testa conexão. Se ainda não houver acesso ao SQL,
    # não reinicia o importador desnecessariamente.
    if not _testar_conexao_worker(
        icon,
        mostrar_sucesso=False,
    ):
        return

    _mostrar_mensagem(
        APP_NAME,
        (
            "Conexão com SQL Server restabelecida.\n\n"
            "Os arquivos pendentes serão reprocessados agora."
        ),
        "info",
    )

    restart_importer(icon)

    # O main executa process_existing() ao iniciar,
    # portanto os arquivos que permaneceram na pasta de entrada
    # serão reavaliados automaticamente.
    time.sleep(2)
    refresh(icon)


def reprocess_pending(icon, item=None):
    threading.Thread(
        target=_reprocessar_worker,
        args=(icon,),
        daemon=True,
    ).start()


def quit_all(icon, item=None):
    """
    Encerra o Importer e toda a sua árvore de processos antes de fechar o Tray.
    Assim, ao clicar em "Sair", não ficam processos órfãos em segundo plano.
    """
    try:
        stop_importer(icon, item)

        # Pequena espera para o Windows concluir a finalização da árvore.
        time.sleep(0.5)

    finally:
        icon.stop()


def run_tray():
    # Impede que dois ícones da bandeja sejam abertos.
    single_instance = SingleInstance("Global\\ImportFilesLogConf_Tray")

    if not single_instance.acquire():
        _mostrar_mensagem(
            APP_NAME,
            "O ImportFilesLogConf já está em execução.",
            "warning",
        )
        return

    menu = pystray.Menu(
        pystray.MenuItem(
            "Status",
            show_status,
            default=True
        ),

        pystray.MenuItem(
            "Reprocessar pendentes",
            reprocess_pending
        ),

        pystray.MenuItem(
            "Testar conexão SQL",
            test_sql_connection
        ),

        pystray.Menu.SEPARATOR,

        pystray.MenuItem(
            "Configuração",
            open_config
        ),

        pystray.MenuItem(
            "Abrir pasta de entrada",
            open_input_folder
        ),

        pystray.MenuItem(
            "Abrir logs",
            open_logs
        ),

        pystray.Menu.SEPARATOR,

        pystray.MenuItem(
            "Iniciar importador",
            start_importer,
            enabled=lambda item: not importer_running()
        ),

        pystray.MenuItem(
            "Parar importador",
            stop_importer,
            enabled=lambda item: importer_running()
        ),

        pystray.MenuItem(
            "Reiniciar importador",
            restart_importer
        ),

        pystray.Menu.SEPARATOR,

        pystray.MenuItem(
            "Sair",
            quit_all
        ),
    )

    icon = pystray.Icon(
        APP_NAME,
        make_icon((128, 128, 128)),
        f"{APP_NAME} - INICIANDO",
        menu
    )

    try:
        start_importer(icon)

        # Ao iniciar o Tray, valida o SQL em segundo plano.
        # Isso evita reutilizar um runtime_status antigo e garante:
        # SQL OK -> verde | SQL com erro -> vermelho.
        threading.Thread(
            target=_testar_conexao_worker,
            args=(icon, False),
            daemon=True,
        ).start()

    except Exception:
        refresh(icon)

    icon.run()


if __name__ == "__main__":
    run_tray()