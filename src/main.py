from __future__ import annotations

import os
import time
import shutil
import logging
import threading
from logging.handlers import RotatingFileHandler


from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .settings import load_settings
from .db import get_connection, numdoc_exists, insert_prodconf_items
from .parser_xml import parse_nfe_xml
from .parser_txt import parse_txt_documents
from .file_router import identificar_arquivo, localizar_par_sync
from .parser_sync import parse_logconf, parse_prodconf, parse_scanocor
from .sync_compare import comparar_logconf, comparar_prodconf
from .sync_apply import aplicar_sincronizacao, aplicar_scanocor, SyncWriteError
from .sql_diagnostics import diagnosticar_erro_sql
from .runtime_status import write_runtime_status
from .single_instance import SingleInstance


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ============================================================
# CONTROLE DE PROCESSAMENTO DUPLICADO DO PAR LOGCONF/PRODCONF
# ============================================================

_pair_lock = threading.Lock()
_pares_processados = {}
_pares_em_processamento = set()

# ============================================================
# REPROCESSAMENTO AUTOMÁTICO DE PENDÊNCIAS
# ============================================================

_RETRY_SQL_INTERVAL_SEC = 30
_retry_sql_lock = threading.Lock()
_retry_sql_em_execucao = False


def _tentar_reservar_coletor(coletor_id: str) -> bool:
    """Reserva atomicamente um coletor para impedir processamento concorrente."""
    with _pair_lock:
        if coletor_id in _pares_em_processamento:
            return False

        _pares_em_processamento.add(coletor_id)
        return True


def _liberar_coletor(coletor_id: str):
    with _pair_lock:
        _pares_em_processamento.discard(coletor_id)


def _assinatura_par(logconf_path: str, prodconf_path: str):
    """
    Cria uma assinatura da versão atual dos dois arquivos.

    Mesmo nome + mesmos arquivos = mesma assinatura.
    Se uma nova sincronização substituir os arquivos,
    tamanho ou data de modificação mudará.
    """

    def assinatura_arquivo(path: str):
        stat = os.stat(path)

        return (
            os.path.normcase(os.path.abspath(path)),
            stat.st_size,
            stat.st_mtime_ns,
        )

    return (
        assinatura_arquivo(logconf_path),
        assinatura_arquivo(prodconf_path),
    )


def _par_ja_processado(coletor_id: str, assinatura) -> bool:
    with _pair_lock:
        return _pares_processados.get(coletor_id) == assinatura


def _marcar_par_processado(coletor_id: str, assinatura):
    with _pair_lock:
        _pares_processados[coletor_id] = assinatura

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


def process_txt(file_path: str, settings, coletor_id: str | None = None):
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
                coletor_id=coletor_id,
            )

            imported += 1

            logging.info(
                f"[TXT] Importado OK: NumDoc={numdoc} Itens={len(itens)}"
            )

        conn.close()

        if imported > 0:
            logging.info(
                f"[NFLOG SQL OK] "
                f"Arquivo={os.path.basename(file_path)} | "
                f"DocumentosImportados={imported} | "
                f"Arquivo preservado em entrada aguardando .ok do coletor."
            )
        elif skipped_dup > 0:
            logging.info(
                f"[NFLOG SQL JA IMPORTADO] "
                f"Arquivo={os.path.basename(file_path)} | "
                f"Duplicados={skipped_dup} | "
                f"Arquivo preservado em entrada aguardando .ok do coletor."
            )
        else:
            raise ValueError("NFLOG sem documentos novos ou duplicados válidos.")

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        conn.close()
        raise


def _process_file_impl(file_path: str, settings):
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
    # TXT / NFLOG CONFIRMADO (.txt.ok)
    # =====================================================

    info = identificar_arquivo(file_path)

    if info is None:
        if ext in (".txt", ".ok"):
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
    # .txt    = recebido e aguarda o coletor.
    # .txt.ok = coletor confirmou a importação.
    # =====================================================

    if info.tipo == "nflog":
        if not wait_file_stable(file_path):
            raise RuntimeError(
                "NFLOG não estabilizou (cópia/rename incompleto?)."
            )

        if not info.confirmado:
            logging.info(
                f"[NFLOG RECEBIDO] "
                f"Coletor={info.coletor_id} | "
                f"Arquivo={info.nome_arquivo} | "
                f"Iniciando importação no SQL antes da confirmação do coletor."
            )

            process_txt(
                file_path,
                settings,
                coletor_id=info.coletor_id,
            )

            logging.info(
                f"[NFLOG AGUARDANDO OK] "
                f"Coletor={info.coletor_id} | "
                f"Arquivo={info.nome_arquivo} | "
                f"SQL processado. Arquivo mantido em entrada para o coletor."
            )
            return

        logging.info(
            f"[NFLOG CONFIRMADO] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={info.nome_arquivo} | "
            f"Confirmacao=.ok | Arquivando sem nova importação SQL."
        )

        nflog_processados_dir = os.path.join(
            settings.watch.processed_dir,
            "nflog",
        )
        ensure_dirs(nflog_processados_dir)

        nome_original = os.path.basename(file_path)
        sufixo = ".txt.ok"
        timestamp = time.strftime("%d%m%Y_%H%M%S")

        if nome_original.lower().endswith(sufixo):
            base_sem_sufixo = nome_original[:-len(sufixo)]
            nome_destino = (
                f"{base_sem_sufixo}_{timestamp}.txt"
            )
        else:
            nome_destino = f"{nome_original}_{timestamp}.txt"

        destino_final = os.path.join(
            nflog_processados_dir,
            nome_destino,
        )

        contador = 1
        while os.path.exists(destino_final):
            if nome_original.lower().endswith(sufixo):
                nome_destino = (
                    f"{base_sem_sufixo}_{timestamp}_{contador}.txt"
                )
            else:
                nome_destino = (
                    f"{nome_original}_{timestamp}_{contador}.txt"
                )
            destino_final = os.path.join(
                nflog_processados_dir,
                nome_destino,
            )
            contador += 1

        shutil.move(file_path, destino_final)

        logging.info(
            f"[NFLOG ARQUIVADO] "
            f"Coletor={info.coletor_id} | "
            f"Destino={destino_final}"
        )
        return

    # =====================================================
    # SCANOCOR
    # Histórico de ocorrências de leitura: somente INSERT.
    # O ColetorID é extraído do nome do arquivo.
    # =====================================================

    if info.tipo == "scanocor":
        if not wait_file_stable(file_path):
            raise RuntimeError(
                "SCANOCOR não estabilizou (cópia incompleta?)."
            )

        resultado_scanocor = parse_scanocor(file_path)

        if not resultado_scanocor.arquivo_valido:
            logging.error(
                f"[SCANOCOR][ERRO ESTRUTURAL] "
                f"Coletor={info.coletor_id} | "
                f"Arquivo={info.nome_arquivo} | "
                f"Motivo={resultado_scanocor.erro_estrutural} | "
                f"Arquivo preservado."
            )
            return

        logging.info(
            f"[SCANOCOR] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={info.nome_arquivo} | "
            f"Lidos={resultado_scanocor.registros_lidos} | "
            f"Validos={resultado_scanocor.registros_validos} | "
            f"Erros={resultado_scanocor.registros_invalidos}"
        )

        for aviso in resultado_scanocor.avisos:
            logging.warning(f"[SCANOCOR][AVISO] {aviso}")

        for erro in resultado_scanocor.erros:
            logging.error(
                f"[SCANOCOR][REGISTRO INVALIDO] "
                f"Linha={erro.linha} | "
                f"Motivo={erro.motivo} | "
                f"Conteudo={erro.conteudo}"
            )

        # Para o arquivo de ocorrências, linhas inválidas não impedem
        # as linhas válidas de serem espelhadas no SQL.
        if not resultado_scanocor.registros:
            logging.warning(
                f"[SCANOCOR][SEM REGISTROS VALIDOS] "
                f"Coletor={info.coletor_id} | "
                f"Arquivo={info.nome_arquivo} | "
                f"Arquivo preservado."
            )
            return

        try:
            gravacao_scan = aplicar_scanocor(
                settings,
                resultado_scanocor.registros,
                info.coletor_id,
            )

            scanocor_processados_dir = os.path.join(
                settings.watch.processed_dir,
                "scanocor",
            )
            destino_scan = safe_move(
                file_path,
                scanocor_processados_dir,
            )

            logging.info(
                f"[SCANOCOR GRAVACAO OK] "
                f"Coletor={info.coletor_id} | "
                f"Inseridos={gravacao_scan.scanocor_inseridos} | "
                f"DuplicadosIgnorados={gravacao_scan.scanocor_duplicados} | "
                f"Destino={destino_scan} | "
                f"COMMIT=OK"
            )

            write_runtime_status(
                BASE_DIR,
                {
                    "estado": "OK",
                    "titulo": "Ocorrências importadas",
                    "coletor": info.coletor_id,
                    "arquivo": info.nome_arquivo,
                    "mensagem": (
                        f"SCANOCOR importado. "
                        f"Inseridos={gravacao_scan.scanocor_inseridos}; "
                        f"Duplicados ignorados={gravacao_scan.scanocor_duplicados}; "
                        f"Linhas inválidas={resultado_scanocor.registros_invalidos}."
                    ),
                    "orientacao": "",
                },
            )
            return

        except Exception as e:
            diagnostico = diagnosticar_erro_sql(e)

            logging.error(
                f"[SCANOCOR][SQL PENDENTE] "
                f"Coletor={info.coletor_id} | "
                f"Tipo={diagnostico['tipo']} | "
                f"Titulo={diagnostico['titulo']} | "
                f"Codigo={diagnostico['codigo']} | "
                f"Orientacao={diagnostico['orientacao']} | "
                f"Arquivo preservado para reprocessamento."
            )
            logging.error(
                f"[SCANOCOR][SQL DETALHE] {diagnostico['mensagem']}"
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

    assinatura_par = _assinatura_par(
        logconf_path,
        confprod_path,
    )

    if _par_ja_processado(
        info.coletor_id,
        assinatura_par,
    ):
        logging.info(
            f"[SYNC DUPLICADA IGNORADA] "
            f"Coletor={info.coletor_id} | "
            f"LOGCONF={os.path.basename(logconf_path)} | "
            f"CONFPROD={os.path.basename(confprod_path)}"
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
    # REGRA DE FIDELIDADE
    # Qualquer registro inválido bloqueia o par inteiro.
    # =====================================================

    if (
        not resultado_logconf.arquivo_valido
        or not resultado_prodconf.arquivo_valido
        or resultado_logconf.registros_invalidos > 0
        or resultado_prodconf.registros_invalidos > 0
    ):
        logging.error(
            f"[SYNC ABORTADA][VALIDACAO] "
            f"Coletor={info.coletor_id} | "
            f"LOGCONF_Erros={resultado_logconf.registros_invalidos} | "
            f"PRODCONF_Erros={resultado_prodconf.registros_invalidos} | "
            f"Nenhuma alteração realizada. Arquivos preservados."
        )
        return

    try:
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
                        f"Linha={item.linha} | {item.chave} | "
                        f"Campo={dif.campo} | "
                        f"SQL='{dif.valor_sql}' -> TXT='{dif.valor_txt}'"
                    )
            elif item.situacao == "NOVO":
                logging.error(
                    f"[SIMULACAO][LOGCONF][NOVO] "
                    f"Linha={item.linha} | {item.chave}"
                )
            elif item.situacao == "ERRO":
                logging.error(
                    f"[SIMULACAO][LOGCONF][ERRO] "
                    f"Linha={item.linha} | {item.chave} | "
                    f"Motivo={item.mensagem}"
                )

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
                        f"Linha={item.linha} | {item.chave} | "
                        f"Campo={dif.campo} | "
                        f"SQL='{dif.valor_sql}' -> TXT='{dif.valor_txt}'"
                    )
            elif item.situacao == "NOVO":
                logging.error(
                    f"[SIMULACAO][PRODCONF][NOVO] "
                    f"Linha={item.linha} | {item.chave}"
                )
            elif item.situacao == "ERRO":
                logging.error(
                    f"[SIMULACAO][PRODCONF][ERRO] "
                    f"Linha={item.linha} | {item.chave} | "
                    f"Motivo={item.mensagem}"
                )

        if (
            comp_logconf.novos > 0
            or comp_logconf.erros > 0
            or comp_prodconf.novos > 0
            or comp_prodconf.erros > 0
        ):
            logging.error(
                f"[SYNC ABORTADA][CONSISTENCIA] "
                f"Coletor={info.coletor_id} | "
                f"LOGCONF_Novos={comp_logconf.novos} | "
                f"LOGCONF_Erros={comp_logconf.erros} | "
                f"PRODCONF_Novos={comp_prodconf.novos} | "
                f"PRODCONF_Erros={comp_prodconf.erros} | "
                f"Nenhuma alteração realizada. Arquivos preservados."
            )
            return

        logging.info(
            f"[PREFLIGHT OK] "
            f"Coletor={info.coletor_id} | "
            f"LOGCONF_Notas={len(comp_logconf.registros)} | "
            f"PRODCONF_Registros={len(comp_prodconf.registros)}"
        )

        gravacao = aplicar_sincronizacao(
            settings,
            resultado_logconf.registros,
            resultado_prodconf.registros,
            info.coletor_id,
        )

        logging.info(
            f"[SYNC GRAVACAO OK] "
            f"Coletor={info.coletor_id} | "
            f"LOGCONF_Atualizados={gravacao.logconf_atualizados} | "
            f"PRODCONF_Atualizados={gravacao.prodconf_atualizados} | "
            f"COMMIT=OK"
        )

        _marcar_par_processado(
            info.coletor_id,
            assinatura_par,
        )

        logconf_destino = safe_move(
            logconf_path,
            settings.watch.processed_dir,
        )
        prodconf_destino = safe_move(
            confprod_path,
            settings.watch.processed_dir,
        )

        logging.info(
            f"[SYNC ARQUIVOS PROCESSADOS] "
            f"Coletor={info.coletor_id} | "
            f"LOGCONF={logconf_destino} | "
            f"CONFPROD={prodconf_destino}"
        )

        write_runtime_status(
            BASE_DIR,
            {
                "estado": "OK",
                "titulo": "Sincronização concluída",
                "coletor": info.coletor_id,
                "arquivo_logconf": os.path.basename(logconf_path),
                "arquivo_prodconf": os.path.basename(confprod_path),
                "mensagem": (
                    f"SQL Server atualizado com sucesso. "
                    f"LOGCONF={gravacao.logconf_atualizados}; "
                    f"PRODCONF={gravacao.prodconf_atualizados}."
                ),
                "orientacao": "",
            },
        )

    except SyncWriteError as e:
        logging.error(
            f"[SYNC ABORTADA][ROLLBACK] "
            f"Coletor={info.coletor_id} | "
            f"Motivo={e} | "
            f"ROLLBACK executado. Arquivos preservados."
        )
        return

    except Exception as e:
        diagnostico = diagnosticar_erro_sql(e)

        logging.error(
            f"[SYNC][SQL PENDENTE] "
            f"Coletor={info.coletor_id} | "
            f"Tipo={diagnostico['tipo']} | "
            f"Titulo={diagnostico['titulo']} | "
            f"Codigo={diagnostico['codigo']} | "
            f"Orientacao={diagnostico['orientacao']} | "
            f"Arquivos preservados para reprocessamento."
        )

        logging.error(
            f"[SYNC][SQL DETALHE] {diagnostico['mensagem']}"
        )
        return


def process_file(file_path: str, settings):
    """
    Entrada serializada por coletor para LOGCONF/CONFPROD.

    O watchdog pode gerar mais de um evento para o mesmo arquivo.
    A reserva abaixo é atômica: somente uma execução por coletor
    pode entrar no processamento do par por vez.

    IMPORTANTE:
    Recarrega a configuração a cada processamento para que alterações
    feitas no Tray (servidor, banco, usuário, senha etc.) passem a valer
    imediatamente, sem necessidade de reiniciar o Importer.
    """
    settings = load_settings()

    ext = os.path.splitext(file_path)[1].lower()
    info = identificar_arquivo(file_path)

    if info is None:
        return _process_file_impl(file_path, settings)

    if info.tipo == "nflog":
        return _process_file_impl(file_path, settings)

    if ext != ".txt":
        return _process_file_impl(file_path, settings)

    if not _tentar_reservar_coletor(info.coletor_id):
        logging.info(
            f"[SYNC CONCORRENTE IGNORADA] "
            f"Coletor={info.coletor_id} | "
            f"Arquivo={info.nome_arquivo} | "
            f"Outro processamento do mesmo coletor já está em andamento."
        )
        return

    try:
        return _process_file_impl(file_path, settings)
    finally:
        _liberar_coletor(info.coletor_id)


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



def _tem_arquivos_pendentes(settings) -> bool:
    # NFLOG .txt depende do SQL; somente .txt.ok não precisa de retry SQL.
    inp = settings.watch.input_dir

    try:
        for name in os.listdir(inp):
            path = os.path.join(inp, name)

            if not os.path.isfile(path):
                continue

            info = identificar_arquivo(path)

            if info is not None and info.tipo == "nflog":
                # NFLOG .txt precisa de SQL; NFLOG .txt.ok só precisa ser arquivado.
                if info.confirmado:
                    continue
                return True

            return True

        return False

    except (FileNotFoundError, OSError):
        return False


def _testar_conexao_sql(settings):
    """Abre e fecha uma conexão apenas para confirmar que o SQL voltou."""
    conn = get_connection(settings.sql)
    try:
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _reprocessar_pendentes_automaticamente(settings):
    """Reprocessa a entrada quando houver pendências e o SQL voltar."""
    global _retry_sql_em_execucao

    with _retry_sql_lock:
        if _retry_sql_em_execucao:
            return
        _retry_sql_em_execucao = True

    try:
        if not _tem_arquivos_pendentes(settings):
            return

        # Recarrega a configuração antes do teste para pegar correções feitas no Tray.
        settings_atualizados = load_settings()

        try:
            _testar_conexao_sql(settings_atualizados)
        except Exception as e:
            diagnostico = diagnosticar_erro_sql(e)
            logging.warning(
                f"[REPROCESSAMENTO AUTOMATICO][SQL INDISPONIVEL] "
                f"Tipo={diagnostico['tipo']} | "
                f"Codigo={diagnostico['codigo']} | "
                f"Nova tentativa em {_RETRY_SQL_INTERVAL_SEC}s."
            )
            return

        logging.info(
            "[REPROCESSAMENTO AUTOMATICO] SQL disponível. "
            "Reprocessando arquivos pendentes."
        )
        process_existing(settings_atualizados)

    except Exception as e:
        logging.exception(f"[REPROCESSAMENTO AUTOMATICO][ERRO] {e}")
    finally:
        with _retry_sql_lock:
            _retry_sql_em_execucao = False

def main():
    # Impede que dois ImportFilesLogConfImporter.exe processem a mesma pasta.
    single_instance = SingleInstance("Global\\ImportFilesLogConf_Importer")

    if not single_instance.acquire():
        logging.basicConfig(level=logging.INFO)
        logging.warning(
            "[INSTANCIA DUPLICADA] Já existe um importador em execução. "
            "Esta segunda instância será encerrada."
        )
        return

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
        proxima_tentativa_sql = time.monotonic() + _RETRY_SQL_INTERVAL_SEC

        while True:
            time.sleep(1)

            agora = time.monotonic()

            if agora >= proxima_tentativa_sql:
                proxima_tentativa_sql = agora + _RETRY_SQL_INTERVAL_SEC
                _reprocessar_pendentes_automaticamente(settings)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()