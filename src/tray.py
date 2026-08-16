import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox

import pystray
from PIL import Image

APP_NAME = "ImportFilesLogConf"
APP_VERSION = "1.0.0"
APP_COMPANY = "2A Tecnologia"
APP_CONTACT = "faleconosco@2atecnologia.com.br"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_base_dir() -> str:
    # Empacotado: pasta do exe
    if is_frozen():
        return os.path.dirname(sys.executable)
    # Dev: raiz do projeto
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


BASE_DIR = get_base_dir()
_importer_proc = None  # subprocess.Popen | None


def _msg_info(title: str, text: str):
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(title, text)
    root.destroy()


def _msg_error(title: str, text: str):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, text)
    root.destroy()


def make_icon(rgb):
    return Image.new("RGB", (64, 64), rgb)


def importer_running():
    global _importer_proc
    return _importer_proc is not None and _importer_proc.poll() is None


def refresh(icon):
    if importer_running():
        icon.icon = make_icon((46, 160, 67))   # verde
        icon.title = f"{APP_NAME} - RODANDO"
    else:
        icon.icon = make_icon((220, 38, 38))   # vermelho
        icon.title = f"{APP_NAME} - PARADO"


def start_importer(icon, item=None):
    global _importer_proc
    if importer_running():
        refresh(icon)
        return

    icon.icon = make_icon((245, 158, 11))  # amarelo
    icon.title = f"{APP_NAME} - INICIANDO..."

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)

    importer_exe = os.path.join(BASE_DIR, "ImportFilesLogConfImporter.exe")

    if is_frozen():
        # Modo empacotado: NUNCA chamar python -m (evita loop de ícones)
        if not os.path.exists(importer_exe):
            _msg_error(APP_NAME, f"Importer não encontrado:\n{importer_exe}")
            refresh(icon)
            return

        _importer_proc = subprocess.Popen(
            [importer_exe],
            cwd=BASE_DIR,
            creationflags=creationflags,
        )
    else:
        # Modo desenvolvimento
        _importer_proc = subprocess.Popen(
            [sys.executable, "-m", "src.importer_entry"],
            cwd=BASE_DIR,
            creationflags=creationflags,
        )

    time.sleep(0.7)
    refresh(icon)


def stop_importer(icon, item=None):
    global _importer_proc
    if not importer_running():
        refresh(icon)
        return

    _importer_proc.terminate()
    try:
        _importer_proc.wait(timeout=5)
    except Exception:
        _importer_proc.kill()

    _importer_proc = None
    refresh(icon)


def restart_importer(icon, item=None):
    stop_importer(icon, item)
    time.sleep(0.3)
    start_importer(icon, item)


def open_config(icon, item=None):
    if is_frozen():
        cfg_exe = os.path.join(BASE_DIR, "ImportFilesLogConfConfig.exe")
        if not os.path.exists(cfg_exe):
            _msg_error(APP_NAME, f"Config UI não encontrada:\n{cfg_exe}")
            return
        subprocess.Popen([cfg_exe], cwd=BASE_DIR)
        return

    subprocess.Popen([sys.executable, "-m", "src.config_ui"], cwd=BASE_DIR)


def open_logs(icon, item=None):
    if is_frozen():
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        os.startfile(log_dir)
        return

    from .settings import load_settings
    s = load_settings()
    os.makedirs(s.logging.log_dir, exist_ok=True)
    os.startfile(s.logging.log_dir)


def open_input_folder(icon, item=None):
    if is_frozen():
        _msg_info(APP_NAME, "Abra a pasta configurada no config.ini (watch.input_dir).")
        return

    from .settings import load_settings
    s = load_settings()
    os.makedirs(s.watch.input_dir, exist_ok=True)
    os.startfile(s.watch.input_dir)


def show_status(icon, item=None):
    if is_frozen():
        msg = (
            f"{APP_NAME}\n\n"
            f"Importador: {'RODANDO' if importer_running() else 'PARADO'}\n\n"
            f"Base: {BASE_DIR}\n"
            f"Obs: em modo empacotado, leia config.ini na pasta do programa.\n"
        )
        _msg_info(APP_NAME, msg)
        return

    from .settings import load_settings
    s = load_settings()

    msg = (
        f"Importador: {'RODANDO' if importer_running() else 'PARADO'}\n\n"
        f"Formato: {s.app.input_format}\n"
        f"Pasta entrada: {s.watch.input_dir}\n"
        f"Servidor SQL: {s.sql.server}\n"
        f"Banco: {s.sql.database}\n"
    )
    _msg_info(APP_NAME, msg)


def show_about(icon, item=None):
    about = (
        f"{APP_NAME}\n\n"
        f"Desenvolvido por: {APP_COMPANY}\n"
        f"Versão: {APP_VERSION}\n"
        f"Contato: {APP_CONTACT}\n"
    )
    _msg_info("Sobre", about)

def open_sefaz_manual(icon, item=None):
    """
    Abre a interface do SEFAZ Downloader em modo manual.
    - Empacotado: abre SefazDownloader.exe (na mesma pasta do Tray)
    - Dev: abre external/sefaz_downloader/main.py
    """
    if is_frozen():
        sefaz_exe = os.path.join(BASE_DIR, "SefazDownloader.exe")
        if not os.path.exists(sefaz_exe):
            _msg_error(APP_NAME, f"SefazDownloader.exe não encontrado:\n{sefaz_exe}")
            return
        subprocess.Popen([sefaz_exe], cwd=BASE_DIR)
        return

    sefaz_dir = os.path.join(BASE_DIR, "external", "sefaz_downloader")
    main_py = os.path.join(sefaz_dir, "main.py")

    if not os.path.exists(main_py):
        _msg_error(APP_NAME, f"SEFAZ Downloader não encontrado:\n{main_py}")
        return

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    subprocess.Popen(
        [sys.executable, main_py],
        cwd=sefaz_dir,
        creationflags=creationflags,
    )


def quit_all(icon, item=None):
    try:
        stop_importer(icon, item)
    finally:
        icon.stop()


def run_tray():
    menu = pystray.Menu(
        pystray.MenuItem("Status", show_status, default=True),
        pystray.MenuItem("Sobre", show_about),
        pystray.MenuItem("Configuração", open_config),
        pystray.MenuItem("Abrir SEFAZ Downloader (Manual)", open_sefaz_manual),
        pystray.MenuItem("Abrir pasta de entrada", open_input_folder),
        pystray.MenuItem("Abrir logs", open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Iniciar importador", start_importer, enabled=lambda item: not importer_running()),
        pystray.MenuItem("Parar importador", stop_importer, enabled=lambda item: importer_running()),
        pystray.MenuItem("Reiniciar importador", restart_importer),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", quit_all),
    )

    icon = pystray.Icon(APP_NAME, make_icon((30, 64, 175)), f"{APP_NAME} - TRAY", menu)

    # auto-start
    try:
        start_importer(icon)
    except Exception:
        refresh(icon)

    icon.run()


if __name__ == "__main__":
    run_tray()