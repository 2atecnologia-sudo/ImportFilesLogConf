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
from .file_router import identificar_arquivo, localizar_par_sync
from .parser_sync import parse_logconf, parse_prodconf
from .sync_compare import comparar_logconf, comparar_prodconf


def ensure_dirs(*dirs: str):
    for d in dirs:
        if d:
            os.makedirs(d, exist_ok=True)


def setup_logging(log_dir: str, level: str = "INFO"):
    ensure_dirs(log_dir)
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    log_path = os.path.join(log_dir, "importador.log")
    fh = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
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

    for _ in range(180):
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
    doc = parse_nfe_xml(
        file_path,
        group_items=settings.app.group_items,
    )

    numdoc = doc["NumDoc"]
    nomecli = doc["NomeCli"]
    itens = doc["Itens"]

    conn = get_connection(settings.sql)

    try:
        if numdoc_exists(conn, numdoc):
            logging.warning(
                f"[XML] NumDoc {numdoc} já existe. Movendo para DUPLICADOS."
            )
            conn.close()
            safe_move(
                file_path,
                settings.watch.duplicate_dir,
            )
            return

        insert_prodconf_items(
            conn,
            numdoc,
            nomecli,
            itens,
            settings.app.status_inicial,
        )

        conn.close()

        safe_move(
            file_path,
            settings.watch.processed_dir,
        )

        logging.info(
            f"[XML] Importado OK: NumDoc={numdoc} Itens={len(itens)}"
        )

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
                logging.warning(
                    f"[TXT] NumDoc {numdoc} já existe. Pulando."
                )
                continue

            insert_prodconf_items(
                conn,
                numdoc,
                nomecli,
                itens,
                settings.app.status_inicial,
            )

            imported += 1

            logging.info(
                f"[TXT] Importado OK: NumDoc={numdoc} Itens={len(itens)}"
            )

        conn.close()

        if imported > 0:
            safe_move(
                file_path,
                settings.watch.processed_dir,
            )
        else:
            if skipped_dup > 0:
                safe_move(
                    file_path,
                    settings.watch.duplicate_dir,
                )
            else:
                safe_move(
                    file_path,
                    settings.watch.error_dir,
                )

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        conn.close()
        raise


def process_file(file_path: str, settings):
    fmt = settings.app.input_format
    ext = os.path.splitext(file_path)[1].lower()

    if fmt == "xml":
        if ext != ".xml":
            return

        logging.info(
            f"Detectado arquivo XML: {file_path}"
        )

        if not wait_file_stable(file_path):
            raise RuntimeError(
                "Arquivo não estabilizou (cópia incompleta?)."
            )

        process_xml(
            file_path,
            settings,
        )
        return

    # =====================================================
    # TXT
    # =====================================================

    if ext != ".txt":
        return

    info = identificar_arquivo(file_path)

    if info is None:
        logging.warning(
            f"[ARQUIVO IGNORADO] Nome fora do padrão: "
            f"{os.path.basename(file_path)}"
        )
        return

    logging.info(
        f"[ARQUIVO] Tipo={info.tipo.upper()} | "
        f"Coletor={info.coletor_id} | "
        f"Arquivo={info.nome_arquivo}"
    )

    # =====================================================
    # NFLOG
    # Mantém a rotina atual
    # =====================================================

    if info.tipo == "nflog":
        if not wait_file_stable(file_path):
            raise RuntimeError(
                "NFLOG não estabilizou (cópia incompleta?)."
            )

        logging.info(
            f"[NFLOG] Iniciando processamento | "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={info.nome_arquivo}"
        )

        process_txt(
            file_path,
            settings,
        )
        return

    # =====================================================
    # LOGCONF / CONFPROD
    # =====================================================

    logconf_path, confprod_path = localizar_par_sync(
        settings.watch.input_dir,
        info.coletor_id,
    )

    if not logconf_path or not confprod_path:
        faltando = (
            "LOGCONF"
            if not logconf_path
            else "CONFPROD"
        )

        logging.warning(
            f"[SYNC PENDENTE] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo recebido={info.nome_arquivo} | "
            f"Faltando={faltando} | "
            f"Nenhuma alteração realizada."
        )
        return

    if not wait_file_stable(logconf_path):
        logging.warning(
            f"[SYNC] LOGCONF ainda não estabilizou | "
            f"Coletor={info.coletor_id}"
        )
        return

    if not wait_file_stable(confprod_path):
        logging.warning(
            f"[SYNC] CONFPROD ainda não estabilizou | "
            f"Coletor={info.coletor_id}"
        )
        return

    logging.info(
        f"[SYNC PAR DETECTADO] "
        f"Coletor={info.coletor_id} | "
        f"LOGCONF={os.path.basename(logconf_path)} | "
        f"CONFPROD={os.path.basename(confprod_path)}"
    )

    # =====================================================
    # ETAPA 2 - PARSER / VALIDAÇÃO
    # Ainda não altera SQL Server
    # =====================================================

    resultado_logconf = parse_logconf(
        logconf_path
    )

    resultado_prodconf = parse_prodconf(
        confprod_path
    )

    # ---------- LOGCONF ----------

    if not resultado_logconf.arquivo_valido:
        logging.error(
            f"[SYNC][LOGCONF][ERRO ESTRUTURAL] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={os.path.basename(logconf_path)} | "
            f"Motivo={resultado_logconf.erro_estrutural}"
        )
    else:
        logging.info(
            f"[SYNC][LOGCONF] "
            f"Lidos={resultado_logconf.registros_lidos} | "
            f"Validos={resultado_logconf.registros_validos} | "
            f"Erros={resultado_logconf.registros_invalidos}"
        )

        for aviso in resultado_logconf.avisos:
            logging.warning(
                f"[SYNC][LOGCONF][AVISO] "
                f"{aviso}"
            )

        for erro in resultado_logconf.erros:
            logging.error(
                f"[SYNC][LOGCONF][REGISTRO INVALIDO] "
                f"Linha={erro.linha} | "
                f"Motivo={erro.motivo} | "
                f"Conteudo={erro.conteudo}"
            )

    # ---------- PRODCONF ----------

    if not resultado_prodconf.arquivo_valido:
        logging.error(
            f"[SYNC][PRODCONF][ERRO ESTRUTURAL] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={os.path.basename(confprod_path)} | "
            f"Motivo={resultado_prodconf.erro_estrutural}"
        )
    else:
        logging.info(
            f"[SYNC][PRODCONF] "
            f"Lidos={resultado_prodconf.registros_lidos} | "
            f"Validos={resultado_prodconf.registros_validos} | "
            f"Erros={resultado_prodconf.registros_invalidos}"
        )

        for aviso in resultado_prodconf.avisos:
            logging.warning(
                f"[SYNC][PRODCONF][AVISO] "
                f"{aviso}"
            )

        for erro in resultado_prodconf.erros:
            logging.error(
                f"[SYNC][PRODCONF][REGISTRO INVALIDO] "
                f"Linha={erro.linha} | "
                f"Motivo={erro.motivo} | "
                f"Conteudo={erro.conteudo}"
            )

    logging.info(
        f"[SYNC VALIDACAO CONCLUIDA] "
        f"Coletor={info.coletor_id}"
    )

    # =====================================================
    # ETAPA 3A - COMPARAÇÃO COM SQL SERVER
    # SOMENTE SIMULAÇÃO - NÃO GRAVA NADA
    # =====================================================

    if resultado_logconf.arquivo_valido:
        comp_logconf = comparar_logconf(
            settings,
            resultado_logconf.registros,
        )

        logging.info(
            f"[SIMULACAO][LOGCONF] "
            f"Novos={comp_logconf.novos} | "
            f"Diferentes={comp_logconf.diferentes} | "
            f"Iguais={comp_logconf.iguais} | "
            f"Erros={comp_logconf.erros}"
        )

        for item in comp_logconf.registros:
            if item.situacao == "DIFERENTE":
                for dif in item.diferencas:
                    logging.info(
                        f"[SIMULACAO][LOGCONF][ALTERARIA] "
                        f"Linha={item.linha} | "
                        f"{item.chave} | "
                        f"Campo={dif.campo} | "
                        f"SQL='{dif.valor_sql}' -> TXT='{dif.valor_txt}'"
                    )

            elif item.situacao == "NOVO":
                logging.info(
                    f"[SIMULACAO][LOGCONF][NOVO] "
                    f"Linha={item.linha} | "
                    f"{item.chave}"
                )

            elif item.situacao == "ERRO":
                logging.error(
                    f"[SIMULACAO][LOGCONF][ERRO] "
                    f"Linha={item.linha} | "
                    f"{item.chave} | "
                    f"Motivo={item.mensagem}"
                )

    if resultado_prodconf.arquivo_valido:
        comp_prodconf = comparar_prodconf(
            settings,
            resultado_prodconf.registros,
        )

        logging.info(
            f"[SIMULACAO][PRODCONF] "
            f"Novos={comp_prodconf.novos} | "
            f"Diferentes={comp_prodconf.diferentes} | "
            f"Iguais={comp_prodconf.iguais} | "
            f"Erros={comp_prodconf.erros}"
        )

        for item in comp_prodconf.registros:
            if item.situacao == "DIFERENTE":
                for dif in item.diferencas:
                    logging.info(
                        f"[SIMULACAO][PRODCONF][ALTERARIA] "
                        f"Linha={item.linha} | "
                        f"{item.chave} | "
                        f"Campo={dif.campo} | "
                        f"SQL='{dif.valor_sql}' -> TXT='{dif.valor_txt}'"
                    )

            elif item.situacao == "NOVO":
                logging.info(
                    f"[SIMULACAO][PRODCONF][NOVO] "
                    f"Linha={item.linha} | "
                    f"{item.chave}"
                )

            elif item.situacao == "ERRO":
                logging.error(
                    f"[SIMULACAO][PRODCONF][ERRO] "
                    f"Linha={item.linha} | "
                    f"{item.chave} | "
                    f"Motivo={item.mensagem}"
                )

    logging.info(
        f"[SIMULACAO CONCLUIDA] "
        f"Coletor={info.coletor_id} | "
        f"Nenhuma alteração realizada no SQL Server."
    )


class Handler(FileSystemEventHandler):
    def __init__(self, settings):
        self.settings = settings

        # Guarda a última assinatura processada de cada arquivo.
        # Evita que o watchdog processe duas vezes o mesmo evento.
        self._ultimos_arquivos = {}

    def _assinatura_arquivo(self, path: str):
        try:
            stat = os.stat(path)

            return (
                stat.st_size,
                stat.st_mtime_ns,
            )

        except (FileNotFoundError, OSError):
            return None

    def _processar_evento(self, file_path: str):
        assinatura = self._assinatura_arquivo(file_path)

        if assinatura is None:
            return

        chave = os.path.normcase(
            os.path.abspath(file_path)
        )

        assinatura_anterior = self._ultimos_arquivos.get(chave)

        if assinatura_anterior == assinatura:
            logging.debug(
                f"[EVENTO DUPLICADO IGNORADO] "
                f"{os.path.basename(file_path)}"
            )
            return

        try:
            process_file(
                file_path,
                self.settings,
            )

            assinatura_final = self._assinatura_arquivo(
                file_path
            )

            if assinatura_final is not None:
                self._ultimos_arquivos[chave] = assinatura_final

        except Exception as e:
            logging.exception(
                f"Erro processando {file_path}: {e}"
            )

            try:
                safe_move(
                    file_path,
                    self.settings.watch.error_dir,
                )
            except Exception:
                pass

    def on_created(self, event):
        if event.is_directory:
            return

        self._processar_evento(
            event.src_path
        )

    def on_moved(self, event):
        if event.is_directory:
            return

        self._processar_evento(
            event.dest_path
        )


def process_existing(settings):
    inp = settings.watch.input_dir

    for name in sorted(os.listdir(inp)):
        path = os.path.join(inp, name)

        if os.path.isfile(path):
            try:
                process_file(
                    path,
                    settings,
                )

            except Exception as e:
                logging.exception(
                    f"Erro processando existente {path}: {e}"
                )

                try:
                    safe_move(
                        path,
                        settings.watch.error_dir,
                    )
                except Exception:
                    pass


def main():
    settings = load_settings()

    setup_logging(
        settings.logging.log_dir,
        settings.logging.level,
    )

    ensure_dirs(
        settings.watch.input_dir,
        settings.watch.processed_dir,
        settings.watch.error_dir,
        settings.watch.duplicate_dir,
        settings.logging.log_dir,
    )

    logging.info(
        f"Iniciando importador | "
        f"formato={settings.app.input_format} | "
        f"pasta={settings.watch.input_dir}"
    )

    process_existing(settings)

    handler = Handler(settings)

    observer = Observer()

    observer.schedule(
        handler,
        settings.watch.input_dir,
        recursive=False,
    )

    observer.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()