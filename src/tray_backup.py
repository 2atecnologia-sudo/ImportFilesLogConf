import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox

import pystray
from PIL import Image


APP_NAME = "ImportFilesLogConf"
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
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


def refresh(icon):
    if importer_running():
        icon.icon = make_icon((46, 160, 67))
        icon.title = f"{APP_NAME} - RODANDO"
    else:
        icon.icon = make_icon((220, 38, 38))
        icon.title = f"{APP_NAME} - PARADO"


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

    _importer_proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
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
    subprocess.Popen(
        [sys.executable, "-m", "src.config_ui"],
        cwd=BASE_DIR
    )


def open_logs(icon, item=None):
    log_dir = os.path.join(BASE_DIR, "logs")

    os.makedirs(
        log_dir,
        exist_ok=True
    )

    os.startfile(log_dir)


def open_input_folder(icon, item=None):
    from .settings import load_settings

    s = load_settings()

    os.makedirs(
        s.watch.input_dir,
        exist_ok=True
    )

    os.startfile(
        s.watch.input_dir
    )


def show_status(icon, item=None):
    from .settings import load_settings

    s = load_settings()

    root = tk.Tk()
    root.withdraw()

    msg = (
        f"Status: "
        f"{'RODANDO' if importer_running() else 'PARADO'}"
        f"\n\n"
        f"Formato: {s.app.input_format}\n"
        f"Pasta entrada: {s.watch.input_dir}\n"
        f"Servidor SQL: {s.sql.server}\n"
        f"Banco: {s.sql.database}\n"
    )

    messagebox.showinfo(
        APP_NAME,
        msg
    )

    root.destroy()


def quit_all(icon, item=None):
    try:
        stop_importer(icon, item)
    finally:
        icon.stop()


def run_tray():

    menu = pystray.Menu(

        pystray.MenuItem(
            "Status",
            show_status,
            default=True
        ),

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
        make_icon((30, 64, 175)),
        f"{APP_NAME} - TRAY",
        menu
    )

    try:
        start_importer(icon)

    except Exception:
        refresh(icon)

    icon.run()

if __name__ == "__main__":
    run_tray()