from __future__ import annotations

import os
import threading
from datetime import datetime

_lock = threading.Lock()

def registrar_evento_usuario(
    settings,
    *,
    nivel: str,
    titulo: str,
    onde: str = "",
    porque: str = "",
    como_resolver: str = "",
    detalhe: str = "",
):
    """Grava o log operacional amigável. O técnico continua em importador.log."""
    log_dir = settings.logging.log_dir
    os.makedirs(log_dir, exist_ok=True)
    caminho = os.path.join(log_dir, "usuario.log")

    linhas = [f"{datetime.now():%d/%m/%Y %H:%M:%S} | {(nivel or 'INFO').upper()} | {titulo}"]
    if onde:
        linhas.append(f"Ação: {onde}")
    if porque:
        linhas.append(f"Por que: {porque}")
    if como_resolver:
        linhas.append(f"O que fazer: {como_resolver}")
    if detalhe:
        linhas.append(f"Detalhe: {detalhe}")
    linhas.append("")

    try:
        with _lock:
            if os.path.exists(caminho) and os.path.getsize(caminho) > 1_000_000:
                backup = caminho + ".1"
                try:
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.replace(caminho, backup)
                except OSError:
                    pass
            with open(caminho, "a", encoding="utf-8") as f:
                f.write("\n".join(linhas) + "\n")
    except Exception:
        pass
