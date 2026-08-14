from __future__ import annotations

import os
import time
import shutil
import logging
from logging.handlers import RotatingFileHandler

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .settings import load_settings
from .db import get_connection, numdoc_exists, insert_prodconf_items
from .parser_xml import parse_nfe_xml
from .parser_txt import parse_txt_documents


def ensure_dirs(*dirs: str):
    for d in dirs:
        if d:
            os.makedirs(d, exist_ok=True)


def setup_logging(log_dir: str, level: str = "INFO"):
    ensure_dirs(log_dir)
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    log_path = os.path.join(log_dir, "importador.log")
    fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)


def wait_file_stable(path: str, checks: int = 3, interval_sec: float = 1.0) -> bool:
    """Espera o arquivo parar de variar de tamanho (cópia finalizada)."""
    last = -1
    stable = 0
    for _ in range(180):  # ~60s máx
        if not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        if size == last and size > 0:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
            last = size
        time.sleep(interval_sec)
    return False


def safe_move(src: str, dst_dir: str) -> str:
    ensure_dirs(dst_dir)
    base = os.path.basename(src)
    dst = os.path.join(dst_dir, base)

    if os.path.exists(dst):
        name, ext = os.path.splitext(base)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(dst_dir, f"{name}_{ts}{ext}")

    shutil.move(src, dst)
    return dst


def process_xml(file_path: str, settings):
    doc = parse_nfe_xml(file_path, group_items=settings.app.group_items)
    numdoc = doc["NumDoc"]
    nomecli = doc["NomeCli"]
    itens = doc["Itens"]

    conn = get_connection(settings.sql)
    try:
        if numdoc_exists(conn, numdoc):
            logging.warning(f"[XML] NumDoc {numdoc} já existe. Movendo para DUPLICADOS.")
            conn.close()
            safe_move(file_path, settings.watch.duplicate_dir)
            return

        insert_prodconf_items(conn, numdoc, nomecli, itens, settings.app.status_inicial)
        conn.close()
        safe_move(file_path, settings.watch.processed_dir)
        logging.info(f"[XML] Importado OK: NumDoc={numdoc} Itens={len(itens)}")

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        raise


def process_txt(file_path: str, settings):
    docs = parse_txt_documents(
        file_path,
        delimiter=settings.txt.delimiter,
        encoding=settings.txt.encoding,
        has_header=settings.txt.has_header,
        group_items=settings.app.group_items,
    )

    if not docs:
        raise ValueError("TXT sem registros válidos.")

    conn = get_connection(settings.sql)

    imported = 0
    skipped_dup = 0

    try:
        for numdoc, info in docs.items():
            nomecli = info.get("NomeCli", "") or ""
            itens = info.get("Itens", []) or []

            if not itens:
                continue

            if numdoc_exists(conn, numdoc):
                skipped_dup += 1
                logging.warning(f"[TXT] NumDoc {numdoc} já existe. Pulando.")
                continue

            insert_prodconf_items(conn, numdoc, nomecli, itens, settings.app.status_inicial)
            imported += 1
            logging.info(f"[TXT] Importado OK: NumDoc={numdoc} Itens={len(itens)}")

        conn.close()

        if imported > 0:
            safe_move(file_path, settings.watch.processed_dir)
        else:
            # se não importou nada e só pulou por duplicidade, manda pra duplicados
            if skipped_dup > 0:
                safe_move(file_path, settings.watch.duplicate_dir)
            else:
                safe_move(file_path, settings.watch.error_dir)

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        raise


def process_file(file_path: str, settings):
    fmt = settings.app.input_format  # "xml" ou "txt"
    ext = os.path.splitext(file_path)[1].lower()

    if fmt == "xml" and ext != ".xml":
        return
    if fmt == "txt" and ext != ".txt":
        return

    logging.info(f"Detectado arquivo: {file_path}")

    if not wait_file_stable(file_path):
        raise RuntimeError("Arquivo não estabilizou (cópia incompleta?).")

    if fmt == "xml":
        process_xml(file_path, settings)
    else:
        process_txt(file_path, settings)


class Handler(FileSystemEventHandler):
    def __init__(self, settings):
        self.settings = settings

    def on_created(self, event):
        if event.is_directory:
            return
        try:
            process_file(event.src_path, self.settings)
        except Exception as e:
            logging.exception(f"Erro processando {event.src_path}: {e}")
            try:
                safe_move(event.src_path, self.settings.watch.error_dir)
            except Exception:
                pass

    def on_moved(self, event):
        # alguns programas criam e depois "movem" para a pasta final
        if event.is_directory:
            return
        try:
            process_file(event.dest_path, self.settings)
        except Exception as e:
            logging.exception(f"Erro processando {event.dest_path}: {e}")
            try:
                safe_move(event.dest_path, self.settings.watch.error_dir)
            except Exception:
                pass


def process_existing(settings):
    inp = settings.watch.input_dir
    for name in sorted(os.listdir(inp)):
        path = os.path.join(inp, name)
        if os.path.isfile(path):
            try:
                process_file(path, settings)
            except Exception as e:
                logging.exception(f"Erro processando existente {path}: {e}")
                try:
                    safe_move(path, settings.watch.error_dir)
                except Exception:
                    pass


def main():
    settings = load_settings()

    setup_logging(settings.logging.log_dir, settings.logging.level)

    ensure_dirs(
        settings.watch.input_dir,
        settings.watch.processed_dir,
        settings.watch.error_dir,
        settings.watch.duplicate_dir,
        settings.logging.log_dir,
    )

    logging.info(f"Iniciando importador | formato={settings.app.input_format} | pasta={settings.watch.input_dir}")

    # processa o que já estiver na pasta
    process_existing(settings)

    handler = Handler(settings)
    observer = Observer()
    observer.schedule(handler, settings.watch.input_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()