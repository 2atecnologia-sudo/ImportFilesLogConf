from __future__ import annotations

import configparser
import logging
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pyodbc


VERSION_MARKER = "ETAPA_7F_STATUS_LANCA_012"
TEST_DATABASE_ALLOWED = "est_ambTestes"
MOVEMENT_TABLE = "movEstambTeste"
MOVEMENT_TYPE = "SAIDA_CONFERENCIA"
STATUS_TABLE = "LancamentoExternoStatus"


def _allowed_test_database(config_path: str | None = None) -> str:
    """
    Banco permitido para gravação em MODO DEMO.
    Mantém a trava de segurança, mas deixa o nome do banco portátil/configurável.
    """
    try:
        cfg = _load_cfg(config_path)
        value = cfg.get(
            "test_environment",
            "database",
            fallback=TEST_DATABASE_ALLOWED,
        ).strip()
        return value or TEST_DATABASE_ALLOWED
    except Exception:
        return TEST_DATABASE_ALLOWED


@dataclass
class ExternalSyncResult:
    status: str
    num_doc: str
    message: str = ""
    items: int = 0


@dataclass
class ExternalDataSource:
    configured: bool = False
    valid: bool = False
    section: str = ""
    name: str = ""
    type: str = ""
    driver: str = ""
    server: str = ""
    port: str = ""
    database: str = ""
    trusted_connection: bool = False
    user: str = ""
    password: str = ""
    schema: str = ""
    table: str = ""
    field_codprod: str = ""
    field_gtin: str = ""
    field_saldo: str = ""
    field_local: str = ""
    field_terminal: str = ""
    field_documento: str = ""
    error: str = ""


@dataclass
class ConferenceValidationResult:
    status: str
    num_doc: str
    status_conf: str = ""
    total_items: int = 0
    zero_items: int = 0
    nonzero_items: int = 0
    message: str = ""


@dataclass
class SimulationItem:
    cod_prod: str
    gtin: str
    descricao: str
    localizacao: str
    coletor_id: str
    qtd_lida: Decimal
    saldo_atual: Decimal | None
    saldo_simulado: Decimal | None
    status: str
    message: str = ""


@dataclass
class SimulationResult:
    status: str
    num_doc: str
    items: list[SimulationItem]
    message: str = ""


@dataclass
class PostingResult:
    status: str
    num_doc: str
    items: int = 0
    message: str = ""


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in (
        "1", "true", "yes", "y", "sim", "s"
    )


def _config_path() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
    return os.path.join(base_dir, "config.ini")


def _load_cfg(
    config_path: str | None = None,
) -> configparser.ConfigParser:
    path = config_path or _config_path()
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg


def load_external_data_source(
    config_path: str | None = None,
) -> ExternalDataSource:
    path = config_path or _config_path()

    if not os.path.exists(path):
        return ExternalDataSource(
            configured=False,
            valid=False,
            error=f"Arquivo de configuração não encontrado: {path}",
        )

    cfg = _load_cfg(path)

    external_sections = [
        section
        for section in cfg.sections()
        if section.startswith("external_connection:")
    ]

    if external_sections:
        section = external_sections[0]
    elif cfg.has_section("connector"):
        section = "connector"
    else:
        return ExternalDataSource(
            configured=False,
            valid=False,
            error="Nenhuma Fonte de Dados Externa configurada.",
        )

    data = ExternalDataSource(
        configured=True,
        section=section,
        name=cfg.get(section, "name", fallback="Fonte de Dados Externa").strip(),
        type=cfg.get(section, "type", fallback="Microsoft SQL Server").strip(),
        driver=cfg.get(section, "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
        server=cfg.get(section, "server", fallback="").strip(),
        port=cfg.get(section, "port", fallback="1433").strip(),
        database=cfg.get(section, "database", fallback="").strip(),
        trusted_connection=_as_bool(
            cfg.get(section, "trusted_connection", fallback="no")
        ),
        user=cfg.get(section, "user", fallback="").strip(),
        password=cfg.get(section, "password", fallback=""),
        schema=cfg.get(section, "schema", fallback="dbo").strip() or "dbo",
        table=cfg.get(section, "table", fallback="").strip(),
        field_codprod=cfg.get(section, "field_codprod", fallback="").strip(),
        field_gtin=cfg.get(section, "field_gtin", fallback="").strip(),
        field_saldo=cfg.get(section, "field_saldo", fallback="").strip(),
        field_local=cfg.get(section, "field_local", fallback="").strip(),
        field_terminal=cfg.get(section, "field_terminal", fallback="").strip(),
        field_documento=cfg.get(section, "field_documento", fallback="").strip(),
    )

    errors = []

    if not data.server:
        errors.append("servidor não informado")
    if not data.database:
        errors.append("banco de dados não informado")
    if not data.driver:
        errors.append("driver ODBC não informado")
    if not data.trusted_connection and not data.user:
        errors.append("usuário SQL não informado")
    if not data.table:
        errors.append("tabela de estoque não configurada")
    if not data.field_saldo:
        errors.append("campo de saldo não configurado")
    if not data.field_codprod and not data.field_gtin:
        errors.append("nenhuma chave de produto configurada (CodProd ou GTIN)")
    if not data.field_local:
        errors.append("campo de localização não configurado")

    data.valid = not errors
    data.error = "; ".join(errors)
    return data


def _build_external_conn_str(source: ExternalDataSource) -> str:
    server = source.server

    if source.port and "\\" not in server and "," not in server:
        server = f"{server},{source.port}"

    parts = [
        f"DRIVER={{{source.driver}}}",
        f"SERVER={server}",
        f"DATABASE={source.database}",
        "TrustServerCertificate=yes",
    ]

    if source.trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={source.user}")
        parts.append(f"PWD={source.password}")

    return ";".join(parts) + ";"


def _build_local_conn_str(
    config_path: str | None = None,
) -> str:
    path = config_path or _config_path()

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {path}"
        )

    cfg = _load_cfg(path)

    driver = cfg.get(
        "sql",
        "driver",
        fallback="ODBC Driver 18 for SQL Server",
    ).strip()
    server = cfg.get("sql", "server", fallback="127.0.0.1").strip()
    database = cfg.get("sql", "database", fallback="").strip()
    trusted = _as_bool(
        cfg.get("sql", "trusted_connection", fallback="no")
    )

    if not database:
        raise RuntimeError("Banco Local logConf não configurado.")

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "TrustServerCertificate=yes",
    ]

    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        user = cfg.get("sql", "user", fallback="").strip()
        password = cfg.get("sql", "password", fallback="")

        if not user:
            raise RuntimeError(
                "Usuário do Banco Local logConf não configurado."
            )

        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")

    return ";".join(parts) + ";"


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")

    text = str(value).strip().replace(",", ".")

    if text == "":
        return Decimal("0")

    return Decimal(text)


def _is_zero(value) -> bool:
    if value is None:
        return False
    try:
        return _to_decimal(value) == Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return False


def _quote_identifier(name: str) -> str:
    value = str(name or "").strip()

    if not value or "]" in value:
        raise ValueError(f"Identificador SQL inválido: {value!r}")

    return f"[{value}]"


def _write_user_log(
    *,
    level: str,
    title: str,
    num_doc: str,
    why: str,
    what_to_do: str = "",
    detail: str = "",
    config_path: str | None = None,
):
    """
    Grava no usuario.log sem depender do objeto Settings.
    Falha de log nunca interrompe o fluxo.
    """
    try:
        cfg = _load_cfg(config_path)
        log_dir = cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(
                os.path.dirname(config_path or _config_path()),
                "logs",
            ),
        ).strip()

        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "usuario.log")

        from datetime import datetime

        lines = [
            f"{datetime.now():%d/%m/%Y %H:%M:%S} | {level.upper()} | {title}",
            f"Ação: Documento {num_doc}",
            f"Por que: {why}",
        ]

        if what_to_do:
            lines.append(f"O que fazer: {what_to_do}")
        if detail:
            lines.append(f"Detalhe: {detail}")

        lines.append("")

        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    except Exception:
        pass



def _ensure_external_status_table(
    config_path: str | None = None,
) -> None:
    """
    Confirma a existência da tabela operacional dbo.LancamentoExternoStatus.

    Regra de segurança:
    - primeiro consulta OBJECT_ID;
    - se a tabela já existe, NÃO envia nenhum CREATE TABLE ao SQL Server;
    - somente tenta criar quando ela realmente não existe;
    - falha nesta camada nunca bloqueia o lançamento externo.
    """
    conn = pyodbc.connect(
        _build_local_conn_str(config_path),
        timeout=5,
        autocommit=False,
    )
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT OBJECT_ID(?, 'U')",
            (f"dbo.{STATUS_TABLE}",),
        )
        object_id = cur.fetchone()[0]

        if object_id is not None:
            return

        cur.execute(
            f"""
            CREATE TABLE dbo.[{STATUS_TABLE}]
            (
                NumDoc              VARCHAR(50)   NOT NULL PRIMARY KEY,
                StatusLancamento    VARCHAR(30)   NOT NULL,
                Motivo              VARCHAR(80)   NULL,
                Mensagem            VARCHAR(1000) NULL,
                ItemProblema        VARCHAR(100)  NULL,
                Localizacao         VARCHAR(100)  NULL,
                QtdeSolicitada      DECIMAL(18,3) NULL,
                SaldoDisponivel     DECIMAL(18,3) NULL,
                Itens               INT           NOT NULL
                    CONSTRAINT DF_{STATUS_TABLE}_Itens DEFAULT (0),
                Tentativas          INT           NOT NULL
                    CONSTRAINT DF_{STATUS_TABLE}_Tentativas DEFAULT (0),
                PrimeiraTentativa   DATETIME2(0)  NULL,
                UltimaTentativa     DATETIME2(0)  NULL,
                DataLancamento      DATETIME2(0)  NULL,
                ColetorID           VARCHAR(100)  NULL,
                FonteExterna        VARCHAR(200)  NULL,
                BancoExterno        VARCHAR(200)  NULL,
                AtualizadoEm        DATETIME2(0)  NOT NULL
                    CONSTRAINT DF_{STATUS_TABLE}_AtualizadoEm DEFAULT (SYSDATETIME())
            )
            """
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass



def _update_logconf_status_lanca(
    *,
    num_doc: str,
    status_lanca: str,
    motivo: str = "",
    config_path: str | None = None,
) -> None:
    """
    Atualiza somente o status resumido do lançamento no cabeçalho LOGCONF.

    Convenção usada pelo Dashboard/Kalipso:
    0 = Pendente
    1 = Lançado com sucesso
    2 = Não lançado / problema

    MotivoEstoque recebe somente um texto amigável quando StatusLanca = 2.

    Esta atualização é não-crítica:
    qualquer falha aqui é registrada no log técnico e NÃO interfere
    no lançamento externo já validado.
    """
    num_doc = str(num_doc or "").strip()
    if not num_doc:
        return

    try:
        conn = pyodbc.connect(
            _build_local_conn_str(config_path),
            timeout=5,
            autocommit=False,
        )
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE dbo.logConf
                SET
                    StatusLanca = ?,
                    MotivoEstoque = NULLIF(?, '')
                WHERE CAST(NumNF AS VARCHAR(50)) = ?
                """,
                (
                    str(status_lanca),
                    str(motivo or "").strip(),
                    num_doc,
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as e:
        logging.warning(
            f"[FONTE EXTERNA][STATUS LANCA][NAO GRAVADO] "
            f"Documento={num_doc} | Motivo={e}"
        )


def _friendly_status_reason(motivo: str) -> str:
    """Traduz o motivo técnico para o texto curto exibido no looper."""
    labels = {
        "SALDO_INSUFICIENTE": "Saldo insuficiente",
        "PRODUTO_LOCAL_NAO_ENCONTRADO": "Produto/localização não encontrado",
        "ESTOQUE_DUPLICADO": "Cadastro de estoque duplicado",
        "ERRO_VALIDACAO_ITEM": "Erro na validação do item",
        "FONTE_NAO_CONFIGURADA": "Fonte externa não configurada",
        "CONFIGURACAO_INVALIDA": "Configuração externa inválida",
        "FALHA_CONEXAO": "Falha de conexão com a fonte externa",
        "TABELA_NAO_ENCONTRADA": "Tabela de estoque não encontrada",
        "CONFERENCIA_INCONSISTENTE": "Conferência inconsistente",
        "VALIDACAO_BLOQUEADA": "Lançamento bloqueado na validação",
        "ERRO_VALIDACAO": "Erro na validação",
        "AGUARDANDO_CONFERENCIA": "Aguardando conferência",
        "ROLLBACK": "Lançamento cancelado e revertido",
        "BLOCKED": "Lançamento bloqueado",
        "BLOCKED_SIMULATION": "Lançamento bloqueado na validação",
        "BLOCKED_DATABASE": "Banco externo não liberado",
    }
    return labels.get(str(motivo or "").strip(), str(motivo or "").strip())



def _record_external_status(
    *,
    num_doc: str,
    status: str,
    motivo: str = "",
    mensagem: str = "",
    item_problema: str = "",
    localizacao: str = "",
    qtde_solicitada=None,
    saldo_disponivel=None,
    itens: int = 0,
    coletor_id: str = "",
    fonte_externa: str = "",
    banco_externo: str = "",
    data_lancamento: bool = False,
    increment_attempt: bool = False,
    config_path: str | None = None,
) -> None:
    """
    Atualiza o estado operacional do documento para uso em Dashboard/Kalipso.

    Esta função é deliberadamente não-crítica: qualquer falha gera apenas
    warning técnico e NÃO interfere no lançamento externo.
    """
    num_doc = str(num_doc or "").strip()
    if not num_doc:
        return

    try:
        _ensure_external_status_table(config_path)

        conn = pyodbc.connect(
            _build_local_conn_str(config_path),
            timeout=5,
            autocommit=False,
        )
        try:
            cur = conn.cursor()

            cur.execute(
                f"""
                UPDATE dbo.[{STATUS_TABLE}]
                SET
                    StatusLancamento = ?,
                    Motivo = NULLIF(?, ''),
                    Mensagem = NULLIF(?, ''),
                    ItemProblema = NULLIF(?, ''),
                    Localizacao = NULLIF(?, ''),
                    QtdeSolicitada = ?,
                    SaldoDisponivel = ?,
                    Itens = ?,
                    ColetorID = NULLIF(?, ''),
                    FonteExterna = NULLIF(?, ''),
                    BancoExterno = NULLIF(?, ''),
                    Tentativas = Tentativas + ?,
                    PrimeiraTentativa =
                        CASE
                            WHEN ? = 1 AND PrimeiraTentativa IS NULL
                                THEN SYSDATETIME()
                            ELSE PrimeiraTentativa
                        END,
                    UltimaTentativa =
                        CASE
                            WHEN ? = 1 THEN SYSDATETIME()
                            ELSE UltimaTentativa
                        END,
                    DataLancamento =
                        CASE
                            WHEN ? = 1 THEN SYSDATETIME()
                            ELSE DataLancamento
                        END,
                    AtualizadoEm = SYSDATETIME()
                WHERE NumDoc = ?
                """,
                (
                    status,
                    motivo,
                    mensagem,
                    item_problema,
                    localizacao,
                    qtde_solicitada,
                    saldo_disponivel,
                    int(itens or 0),
                    coletor_id,
                    fonte_externa,
                    banco_externo,
                    1 if increment_attempt else 0,
                    1 if increment_attempt else 0,
                    1 if increment_attempt else 0,
                    1 if data_lancamento else 0,
                    num_doc,
                ),
            )

            if cur.rowcount == 0:
                cur.execute(
                    f"""
                    INSERT INTO dbo.[{STATUS_TABLE}]
                    (
                        NumDoc,
                        StatusLancamento,
                        Motivo,
                        Mensagem,
                        ItemProblema,
                        Localizacao,
                        QtdeSolicitada,
                        SaldoDisponivel,
                        Itens,
                        Tentativas,
                        PrimeiraTentativa,
                        UltimaTentativa,
                        DataLancamento,
                        ColetorID,
                        FonteExterna,
                        BancoExterno,
                        AtualizadoEm
                    )
                    VALUES
                    (
                        ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''),
                        NULLIF(?, ''), ?, ?, ?, ?,
                        CASE WHEN ? = 1 THEN SYSDATETIME() ELSE NULL END,
                        CASE WHEN ? = 1 THEN SYSDATETIME() ELSE NULL END,
                        CASE WHEN ? = 1 THEN SYSDATETIME() ELSE NULL END,
                        NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''),
                        SYSDATETIME()
                    )
                    """,
                    (
                        num_doc,
                        status,
                        motivo,
                        mensagem,
                        item_problema,
                        localizacao,
                        qtde_solicitada,
                        saldo_disponivel,
                        int(itens or 0),
                        1 if increment_attempt else 0,
                        1 if increment_attempt else 0,
                        1 if increment_attempt else 0,
                        1 if data_lancamento else 0,
                        coletor_id,
                        fonte_externa,
                        banco_externo,
                    ),
                )

            conn.commit()

            # Atualiza também o resumo exibido pelo looper/Kalipso.
            # StatusLanca: 0=Pendente, 1=Lançado, 2=Não lançado/problema.
            if status == "LANCADO":
                _update_logconf_status_lanca(
                    num_doc=num_doc,
                    status_lanca="1",
                    motivo="",
                    config_path=config_path,
                )
            elif status == "NAO_LANCADO":
                _update_logconf_status_lanca(
                    num_doc=num_doc,
                    status_lanca="2",
                    motivo=_friendly_status_reason(motivo),
                    config_path=config_path,
                )
            elif status == "EM_VALIDACAO":
                _update_logconf_status_lanca(
                    num_doc=num_doc,
                    status_lanca="0",
                    motivo="",
                    config_path=config_path,
                )

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as e:
        logging.warning(
            f"[FONTE EXTERNA][STATUS DASHBOARD][NAO GRAVADO] "
            f"Documento={num_doc} | Motivo={e}"
        )


def _first_simulation_problem(
    simulation: SimulationResult,
):
    """Extrai o primeiro problema para exibir na tabela de status."""
    for item in simulation.items:
        if item.status != "OK":
            motivo_map = {
                "NOT_FOUND": "PRODUTO_LOCAL_NAO_ENCONTRADO",
                "DUPLICATE": "ESTOQUE_DUPLICADO",
                "INSUFFICIENT_STOCK": "SALDO_INSUFICIENTE",
                "ERROR": "ERRO_VALIDACAO_ITEM",
            }
            return {
                "motivo": motivo_map.get(item.status, "VALIDACAO_BLOQUEADA"),
                "item": item.cod_prod or item.gtin or "",
                "local": item.localizacao or "",
                "qtde": item.qtd_lida,
                "saldo": item.saldo_atual,
            }

    return {
        "motivo": "VALIDACAO_BLOQUEADA",
        "item": "",
        "local": "",
        "qtde": None,
        "saldo": None,
    }



def test_external_connection(
    config_path: str | None = None,
) -> ExternalSyncResult:
    source = load_external_data_source(config_path)

    if not source.configured:
        return ExternalSyncResult(
            status="NO_CONFIG",
            num_doc="",
            message=source.error,
        )

    if not source.valid:
        return ExternalSyncResult(
            status="INVALID_CONFIG",
            num_doc="",
            message=source.error,
        )

    conn = None
    try:
        conn = pyodbc.connect(
            _build_external_conn_str(source),
            timeout=5,
        )
        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = ?
              AND TABLE_NAME = ?
            """,
            (source.schema, source.table),
        )

        if int(cur.fetchone()[0]) != 1:
            return ExternalSyncResult(
                status="TABLE_NOT_FOUND",
                num_doc="",
                message=(
                    f"Tabela {source.schema}.{source.table} "
                    f"não encontrada no banco {source.database}."
                ),
            )

        cur.execute(
            f"SELECT COUNT(*) FROM [{source.schema}].[{source.table}]"
        )
        total = int(cur.fetchone()[0])

        return ExternalSyncResult(
            status="CONNECTION_OK",
            num_doc="",
            message=(
                f"Conexão OK | {source.server} | {source.database} | "
                f"{source.schema}.{source.table} | Registros={total}"
            ),
            items=total,
        )

    except Exception as e:
        return ExternalSyncResult(
            status="CONNECTION_ERROR",
            num_doc="",
            message=str(e),
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def validate_conference(
    num_doc: str,
    config_path: str | None = None,
) -> ConferenceValidationResult:
    num_doc = str(num_doc).strip()

    if not num_doc:
        return ConferenceValidationResult(
            status="ERROR",
            num_doc="",
            message="Número do documento não informado.",
        )

    conn = None
    try:
        conn = pyodbc.connect(
            _build_local_conn_str(config_path),
            timeout=5,
        )
        cur = conn.cursor()

        cur.execute(
            """
            SELECT TOP 1 StatusConf
            FROM dbo.logConf
            WHERE CAST(NumNF AS VARCHAR(50)) = ?
            """,
            (num_doc,),
        )

        row = cur.fetchone()

        if row is None:
            return ConferenceValidationResult(
                status="ERROR",
                num_doc=num_doc,
                message=f"Documento {num_doc} não encontrado em dbo.logConf.",
            )

        status_conf = str(
            row[0] if row[0] is not None else ""
        ).strip().upper()

        cur.execute(
            """
            SELECT Saldo
            FROM dbo.prodConf
            WHERE CAST(NumDoc AS VARCHAR(50)) = ?
            """,
            (num_doc,),
        )
        rows = cur.fetchall()

        if not rows:
            return ConferenceValidationResult(
                status="ERROR",
                num_doc=num_doc,
                status_conf=status_conf,
                message=f"Documento {num_doc} não possui itens em dbo.prodConf.",
            )

        total_items = len(rows)
        zero_items = sum(1 for row in rows if _is_zero(row[0]))
        nonzero_items = total_items - zero_items
        all_zero = nonzero_items == 0

        if all_zero and status_conf != "CONFERIDO":
            return ConferenceValidationResult(
                status="INCONSISTENT",
                num_doc=num_doc,
                status_conf=status_conf,
                total_items=total_items,
                zero_items=zero_items,
                nonzero_items=nonzero_items,
                message=(
                    "Todos os itens estão com Saldo=0, porém "
                    f"StatusConf={status_conf or 'VAZIO'}."
                ),
            )

        if status_conf == "CONFERIDO" and all_zero:
            return ConferenceValidationResult(
                status="READY",
                num_doc=num_doc,
                status_conf=status_conf,
                total_items=total_items,
                zero_items=zero_items,
                nonzero_items=nonzero_items,
                message=(
                    "Conferência concluída: StatusConf=CONFERIDO "
                    "e todos os itens possuem Saldo=0."
                ),
            )

        return ConferenceValidationResult(
            status="WAITING",
            num_doc=num_doc,
            status_conf=status_conf,
            total_items=total_items,
            zero_items=zero_items,
            nonzero_items=nonzero_items,
            message=(
                "Conferência ainda não liberada. "
                f"Itens com saldo diferente de zero={nonzero_items}."
            ),
        )

    except Exception as e:
        return ConferenceValidationResult(
            status="ERROR",
            num_doc=num_doc,
            message=str(e),
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _read_local_items(
    num_doc: str,
    config_path: str | None = None,
):
    conn = pyodbc.connect(
        _build_local_conn_str(config_path),
        timeout=5,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                pc.CodProd,
                pc.GTIN,
                pc.DescProd,
                pc.QtdeLido,
                pc.Localizacao,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(pc.ColetorID)), ''),
                    (
                        SELECT TOP 1 lc.ColetorID
                        FROM dbo.logConf AS lc
                        WHERE CAST(lc.NumNF AS VARCHAR(50)) =
                              CAST(pc.NumDoc AS VARCHAR(50))
                          AND NULLIF(LTRIM(RTRIM(lc.ColetorID)), '') IS NOT NULL
                    )
                ) AS ColetorID
            FROM dbo.prodConf AS pc
            WHERE CAST(pc.NumDoc AS VARCHAR(50)) = ?
            ORDER BY pc.CodProd, pc.GTIN, pc.Localizacao
            """,
            (str(num_doc),),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _build_stock_where(
    source: ExternalDataSource,
    cod_prod: str,
    gtin: str,
    localizacao: str,
):
    cod_field = (
        _quote_identifier(source.field_codprod)
        if source.field_codprod
        else None
    )
    gtin_field = (
        _quote_identifier(source.field_gtin)
        if source.field_gtin
        else None
    )
    local_field = _quote_identifier(source.field_local)

    product_predicates = []
    product_params = []

    if cod_field and cod_prod:
        product_predicates.append(
            f"LTRIM(RTRIM(ISNULL(CAST({cod_field} AS VARCHAR(100)), ''))) = ?"
        )
        product_params.append(cod_prod)

    if gtin_field and gtin:
        product_predicates.append(
            f"LTRIM(RTRIM(ISNULL(CAST({gtin_field} AS VARCHAR(100)), ''))) = ?"
        )
        product_params.append(gtin)

    if not product_predicates:
        raise RuntimeError(
            "Produto sem CodProd/GTIN utilizável para localizar no estoque externo."
        )

    if not localizacao:
        raise RuntimeError(
            "PRODCONF sem Localizacao. Não é seguro escolher uma posição de estoque."
        )

    where_sql = (
        "(" + " OR ".join(product_predicates) + ")"
        f" AND LTRIM(RTRIM(ISNULL(CAST({local_field} AS VARCHAR(100)), ''))) = ?"
    )

    return where_sql, tuple(product_params + [localizacao])


def simulate_external_posting(
    num_doc: str,
    config_path: str | None = None,
) -> SimulationResult:
    validation = validate_conference(num_doc, config_path)

    if validation.status != "READY":
        return SimulationResult(
            status="BLOCKED",
            num_doc=str(num_doc),
            items=[],
            message=(
                "Simulação bloqueada porque a conferência "
                f"não está READY. Status={validation.status}."
            ),
        )

    source = load_external_data_source(config_path)

    if not source.configured:
        return SimulationResult("NO_CONFIG", str(num_doc), [], source.error)

    if not source.valid:
        return SimulationResult("INVALID_CONFIG", str(num_doc), [], source.error)

    external_conn = None

    try:
        local_items = _read_local_items(num_doc, config_path)

        if not local_items:
            return SimulationResult(
                status="ERROR",
                num_doc=str(num_doc),
                items=[],
                message="Documento sem itens no PRODCONF.",
            )

        external_conn = pyodbc.connect(
            _build_external_conn_str(source),
            timeout=5,
        )
        cur = external_conn.cursor()

        schema = _quote_identifier(source.schema)
        table = _quote_identifier(source.table)
        saldo_field = _quote_identifier(source.field_saldo)

        results: list[SimulationItem] = []

        for row in local_items:
            cod_prod = str(row[0] or "").strip()
            gtin = str(row[1] or "").strip()
            descricao = str(row[2] or "").strip()
            qtd_lida = _to_decimal(row[3])
            localizacao = str(row[4] or "").strip()
            coletor_id = str(row[5] or "").strip()

            try:
                where_sql, params = _build_stock_where(
                    source, cod_prod, gtin, localizacao
                )
            except Exception as e:
                results.append(
                    SimulationItem(
                        cod_prod, gtin, descricao, localizacao, coletor_id,
                        qtd_lida, None, None, "ERROR", str(e)
                    )
                )
                continue

            cur.execute(
                f"""
                SELECT {saldo_field}
                FROM {schema}.{table}
                WHERE {where_sql}
                """,
                params,
            )
            rows = cur.fetchall()

            if len(rows) == 0:
                results.append(
                    SimulationItem(
                        cod_prod, gtin, descricao, localizacao, coletor_id,
                        qtd_lida, None, None, "NOT_FOUND",
                        "Produto/localização não encontrado no estoque externo."
                    )
                )
                continue

            if len(rows) > 1:
                results.append(
                    SimulationItem(
                        cod_prod, gtin, descricao, localizacao, coletor_id,
                        qtd_lida, None, None, "DUPLICATE",
                        f"{len(rows)} registros encontrados; esperado=1."
                    )
                )
                continue

            saldo_atual = _to_decimal(rows[0][0])

            if qtd_lida > saldo_atual:
                results.append(
                    SimulationItem(
                        cod_prod, gtin, descricao, localizacao, coletor_id,
                        qtd_lida, saldo_atual, None, "INSUFFICIENT_STOCK",
                        (
                            f"Saldo insuficiente: disponível={saldo_atual}, "
                            f"saída={qtd_lida}."
                        )
                    )
                )
                continue

            saldo_simulado = saldo_atual - qtd_lida

            results.append(
                SimulationItem(
                    cod_prod, gtin, descricao, localizacao, coletor_id,
                    qtd_lida, saldo_atual, saldo_simulado, "OK",
                    "Simulação de saída válida."
                )
            )

        errors = [item for item in results if item.status != "OK"]

        if errors:
            return SimulationResult(
                status="SIMULATION_ERROR",
                num_doc=str(num_doc),
                items=results,
                message=(
                    f"Simulação encontrou {len(errors)} item(ns) com problema. "
                    "Nenhum lançamento será permitido."
                ),
            )

        return SimulationResult(
            status="SIMULATION_OK",
            num_doc=str(num_doc),
            items=results,
            message=(
                f"Simulação de saída concluída para {len(results)} item(ns). "
                "Nenhum dado foi alterado."
            ),
        )

    except Exception as e:
        return SimulationResult(
            status="ERROR",
            num_doc=str(num_doc),
            items=[],
            message=str(e),
        )
    finally:
        if external_conn is not None:
            try:
                external_conn.close()
            except Exception:
                pass


def post_external_test_transaction(
    num_doc: str,
    config_path: str | None = None,
) -> PostingResult:
    """
    Mantida para testes manuais.
    NÃO é chamada pelo preflight automático da Etapa 7A.
    """
    num_doc = str(num_doc).strip()

    source = load_external_data_source(config_path)

    if not source.configured:
        return PostingResult("NO_CONFIG", num_doc, 0, source.error)

    if not source.valid:
        return PostingResult("INVALID_CONFIG", num_doc, 0, source.error)

    allowed_test_database = _allowed_test_database(config_path)

    if source.database.lower() != allowed_test_database.lower():
        return PostingResult(
            "BLOCKED_DATABASE",
            num_doc,
            0,
            (
                f"GRAVAÇÃO BLOQUEADA: o modo DEMO só permite o banco "
                f"{allowed_test_database}. Banco configurado={source.database}."
            ),
        )

    validation = validate_conference(num_doc, config_path)

    if validation.status != "READY":
        return PostingResult(
            "BLOCKED",
            num_doc,
            0,
            f"Conferência não está READY. Status={validation.status}.",
        )

    simulation = simulate_external_posting(num_doc, config_path)

    if simulation.status != "SIMULATION_OK":
        return PostingResult(
            "BLOCKED_SIMULATION",
            num_doc,
            0,
            (
                f"Gravação bloqueada porque a simulação não passou. "
                f"Status={simulation.status}."
            ),
        )

    conn = None

    try:
        conn = pyodbc.connect(
            _build_external_conn_str(source),
            timeout=5,
            autocommit=False,
        )
        cur = conn.cursor()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME = ?
            """,
            (MOVEMENT_TABLE,),
        )
        if int(cur.fetchone()[0]) != 1:
            raise RuntimeError(
                f"Tabela dbo.{MOVEMENT_TABLE} não encontrada."
            )

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM dbo.[{MOVEMENT_TABLE}] WITH (UPDLOCK, HOLDLOCK)
            WHERE CAST(NUM_DOCUMENTO AS VARCHAR(100)) = ?
              AND TIPO_OPERACAO = ?
              AND RESULTADO = 'SUCESSO'
            """,
            (num_doc, MOVEMENT_TYPE),
        )

        if int(cur.fetchone()[0]) > 0:
            conn.rollback()
            return PostingResult(
                "ALREADY_POSTED",
                num_doc,
                0,
                "Documento já possui lançamento de saída com sucesso.",
            )

        schema = _quote_identifier(source.schema)
        table = _quote_identifier(source.table)
        saldo_field = _quote_identifier(source.field_saldo)

        terminal_field = (
            _quote_identifier(source.field_terminal)
            if source.field_terminal
            else None
        )

        documento_field = (
            _quote_identifier(source.field_documento)
            if source.field_documento
            else None
        )

        processed = 0

        for item in simulation.items:
            where_sql, where_params = _build_stock_where(
                source,
                item.cod_prod,
                item.gtin,
                item.localizacao,
            )

            cur.execute(
                f"""
                SELECT {saldo_field}
                FROM {schema}.{table} WITH (UPDLOCK, HOLDLOCK)
                WHERE {where_sql}
                """,
                where_params,
            )
            stock_rows = cur.fetchall()

            if len(stock_rows) != 1:
                raise RuntimeError(
                    f"Produto {item.cod_prod or item.gtin} / "
                    f"{item.localizacao}: encontrados={len(stock_rows)}, esperado=1."
                )

            saldo_anterior = _to_decimal(stock_rows[0][0])

            if item.qtd_lida > saldo_anterior:
                raise RuntimeError(
                    f"Saldo insuficiente para {item.cod_prod or item.gtin} "
                    f"em {item.localizacao}: disponível={saldo_anterior}, "
                    f"saída={item.qtd_lida}."
                )

            saldo_posterior = saldo_anterior - item.qtd_lida

            set_parts = [f"{saldo_field} = ?"]
            update_params = [saldo_posterior]

            if terminal_field:
                set_parts.append(f"{terminal_field} = ?")
                update_params.append(item.coletor_id or None)

            if documento_field:
                set_parts.append(f"{documento_field} = ?")
                update_params.append(num_doc)

            cur.execute(
                f"""
                UPDATE {schema}.{table}
                SET {", ".join(set_parts)}
                WHERE {where_sql}
                """,
                tuple(update_params) + tuple(where_params),
            )

            if cur.rowcount != 1:
                raise RuntimeError(
                    f"UPDATE do produto {item.cod_prod or item.gtin} "
                    f"afetou {cur.rowcount} registros; esperado=1."
                )

            cur.execute(
                f"""
                INSERT INTO dbo.[{MOVEMENT_TABLE}]
                (
                    NUM_DOCUMENTO,
                    COD_ITEM,
                    COD_BARRAS,
                    QTD_MOVIMENTADA,
                    SALDO_ANTERIOR,
                    SALDO_POSTERIOR,
                    IDENT_TERMINAL,
                    TIPO_OPERACAO,
                    RESULTADO,
                    DETALHE
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    num_doc,
                    item.cod_prod or None,
                    item.gtin or None,
                    item.qtd_lida,
                    saldo_anterior,
                    saldo_posterior,
                    item.coletor_id or None,
                    MOVEMENT_TYPE,
                    "SUCESSO",
                    (
                        f"Saída por conferência finalizada | "
                        f"{item.descricao or 'Sem descrição'} | "
                        f"Local: {item.localizacao}"
                    ),
                ),
            )

            processed += 1

        conn.commit()

        return PostingResult(
            "POSTED",
            num_doc,
            processed,
            (
                f"Saída concluída com COMMIT. "
                f"{processed} item(ns) descontados do estoque e movimentados."
            ),
        )

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        return PostingResult(
            "ROLLBACK",
            num_doc,
            0,
            f"Falha: {e}. ROLLBACK executado; nenhuma alteração confirmada.",
        )

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def automatic_external_preflight(
    num_doc: str,
    config_path: str | None = None,
) -> ExternalSyncResult:
    """
    ETAPA 7A - PRE-FLIGHT AUTOMÁTICO, SEM GRAVAÇÃO.

    Esta é a função que será futuramente chamada pelo importador.

    Ela:
    1) verifica se existe Fonte de Dados Externa;
    2) valida a configuração;
    3) testa comunicação;
    4) valida a conferência;
    5) simula a saída;
    6) grava log técnico e log amigável quando necessário.

    NUNCA chama post_external_test_transaction().
    NÃO executa UPDATE/INSERT/DELETE.
    """
    num_doc = str(num_doc).strip()

    source = load_external_data_source(config_path)

    if not source.configured:
        message = source.error or "Fonte de Dados Externa não configurada."
        logging.warning(
            f"[FONTE EXTERNA][PREFLIGHT][SEM CONFIGURACAO] "
            f"Documento={num_doc} | {message}"
        )
        _write_user_log(
            level="ERRO",
            title="Lançamento externo não realizado",
            num_doc=num_doc,
            why=message,
            what_to_do=(
                "Configure e teste a Fonte de Dados Externa. "
                "O processamento local permanece normal."
            ),
            config_path=config_path,
        )
        return ExternalSyncResult("NO_CONFIG", num_doc, message)

    if not source.valid:
        message = source.error or "Configuração externa inválida."
        logging.error(
            f"[FONTE EXTERNA][PREFLIGHT][CONFIG INVALIDA] "
            f"Documento={num_doc} | {message}"
        )
        _write_user_log(
            level="ERRO",
            title="Fonte de Dados Externa incompleta",
            num_doc=num_doc,
            why=message,
            what_to_do="Revise a configuração e o mapeamento da fonte externa.",
            config_path=config_path,
        )
        return ExternalSyncResult("INVALID_CONFIG", num_doc, message)

    conn_test = test_external_connection(config_path)

    if conn_test.status != "CONNECTION_OK":
        logging.error(
            f"[FONTE EXTERNA][PREFLIGHT][CONEXAO] "
            f"Documento={num_doc} | Status={conn_test.status} | "
            f"Motivo={conn_test.message}"
        )
        _write_user_log(
            level="ERRO",
            title="Falha na comunicação com a Fonte de Dados Externa",
            num_doc=num_doc,
            why=conn_test.message,
            what_to_do=(
                "Verifique servidor, banco, usuário, senha, rede e disponibilidade SQL. "
                "Nenhum lançamento externo foi realizado."
            ),
            config_path=config_path,
        )
        return ExternalSyncResult(
            conn_test.status,
            num_doc,
            conn_test.message,
        )

    validation = validate_conference(num_doc, config_path)

    if validation.status == "WAITING":
        logging.info(
            f"[FONTE EXTERNA][PREFLIGHT][AGUARDANDO] "
            f"Documento={num_doc} | StatusConf={validation.status_conf} | "
            f"SaldoNaoZero={validation.nonzero_items}"
        )
        return ExternalSyncResult(
            "WAITING",
            num_doc,
            validation.message,
            validation.total_items,
        )

    if validation.status == "INCONSISTENT":
        logging.error(
            f"[FONTE EXTERNA][PREFLIGHT][INCONSISTENCIA] "
            f"Documento={num_doc} | {validation.message}"
        )
        _write_user_log(
            level="ERRO",
            title="Conferência inconsistente - lançamento bloqueado",
            num_doc=num_doc,
            why=validation.message,
            what_to_do=(
                "Verifique o StatusConf do LOGCONF. "
                "Todos os saldos estão zerados, portanto o documento deveria estar CONFERIDO."
            ),
            config_path=config_path,
        )
        return ExternalSyncResult(
            "INCONSISTENT",
            num_doc,
            validation.message,
            validation.total_items,
        )

    if validation.status != "READY":
        logging.error(
            f"[FONTE EXTERNA][PREFLIGHT][VALIDACAO ERRO] "
            f"Documento={num_doc} | Status={validation.status} | "
            f"Motivo={validation.message}"
        )
        _write_user_log(
            level="ERRO",
            title="Não foi possível validar a conferência",
            num_doc=num_doc,
            why=validation.message,
            what_to_do="Verifique o Banco Local logConf e os dados do documento.",
            config_path=config_path,
        )
        return ExternalSyncResult(
            validation.status,
            num_doc,
            validation.message,
        )

    simulation = simulate_external_posting(num_doc, config_path)

    if simulation.status != "SIMULATION_OK":
        logging.error(
            f"[FONTE EXTERNA][PREFLIGHT][SIMULACAO BLOQUEADA] "
            f"Documento={num_doc} | Status={simulation.status} | "
            f"Motivo={simulation.message}"
        )

        details = []
        for item in simulation.items:
            if item.status != "OK":
                details.append(
                    f"{item.cod_prod or item.gtin} / {item.localizacao}: "
                    f"{item.status} - {item.message}"
                )

        _write_user_log(
            level="ERRO",
            title="Lançamento externo bloqueado na validação",
            num_doc=num_doc,
            why=simulation.message,
            what_to_do=(
                "Verifique produto, GTIN, localização e saldo disponível "
                "na Fonte de Dados Externa."
            ),
            detail=" | ".join(details),
            config_path=config_path,
        )

        return ExternalSyncResult(
            simulation.status,
            num_doc,
            simulation.message,
            len(simulation.items),
        )

    logging.info(
        f"[FONTE EXTERNA][PREFLIGHT OK] "
        f"Documento={num_doc} | Itens={len(simulation.items)} | "
        f"Fonte={source.name} | Banco={source.database} | "
        f"NENHUMA GRAVACAO EXECUTADA"
    )

    return ExternalSyncResult(
        "READY_TO_POST",
        num_doc,
        (
            f"Preflight externo aprovado para {len(simulation.items)} item(ns). "
            "Nenhuma gravação executada nesta etapa."
        ),
        len(simulation.items),
    )



def automatic_external_posting(
    num_doc: str,
    config_path: str | None = None,
) -> ExternalSyncResult:
    """
    ETAPA 7D - lançamento automático REAL, restrito ao banco de testes.

    Fluxo:
    1) executa todo o preflight já aprovado;
    2) somente READY_TO_POST pode prosseguir;
    3) chama a transação existente de gravação;
    4) ALREADY_POSTED é tratado como proteção anti-duplicidade;
    5) qualquer falha preserva o banco via rollback.

    A própria post_external_test_transaction() bloqueia qualquer banco
    diferente do banco configurado em [test_environment].
    """
    num_doc = str(num_doc).strip()

    source = load_external_data_source(config_path)

    _record_external_status(
        num_doc=num_doc,
        status="EM_VALIDACAO",
        motivo="",
        mensagem="Validando lançamento na Fonte de Dados Externa.",
        itens=0,
        fonte_externa=source.name if source.configured else "",
        banco_externo=source.database if source.configured else "",
        increment_attempt=True,
        config_path=config_path,
    )

    preflight = automatic_external_preflight(num_doc, config_path)

    if preflight.status != "READY_TO_POST":
        motivo_map = {
            "NO_CONFIG": "FONTE_NAO_CONFIGURADA",
            "INVALID_CONFIG": "CONFIGURACAO_INVALIDA",
            "CONNECTION_ERROR": "FALHA_CONEXAO",
            "TABLE_NOT_FOUND": "TABELA_NAO_ENCONTRADA",
            "INCONSISTENT": "CONFERENCIA_INCONSISTENTE",
            "SIMULATION_ERROR": "VALIDACAO_BLOQUEADA",
            "ERROR": "ERRO_VALIDACAO",
            "WAITING": "AGUARDANDO_CONFERENCIA",
        }

        problem = {
            "motivo": motivo_map.get(preflight.status, preflight.status),
            "item": "",
            "local": "",
            "qtde": None,
            "saldo": None,
        }

        if preflight.status == "SIMULATION_ERROR":
            simulation = simulate_external_posting(num_doc, config_path)
            problem = _first_simulation_problem(simulation)

        _record_external_status(
            num_doc=num_doc,
            status="NAO_LANCADO",
            motivo=problem["motivo"],
            mensagem=preflight.message,
            item_problema=problem["item"],
            localizacao=problem["local"],
            qtde_solicitada=problem["qtde"],
            saldo_disponivel=problem["saldo"],
            itens=preflight.items,
            fonte_externa=source.name if source.configured else "",
            banco_externo=source.database if source.configured else "",
            config_path=config_path,
        )

        return preflight

    posting = post_external_test_transaction(num_doc, config_path)

    if posting.status == "POSTED":
        message = (
            f"Lançamento externo concluído com sucesso para "
            f"{posting.items} item(ns)."
        )
        logging.info(
            f"[FONTE EXTERNA][LANCAMENTO OK] "
            f"Documento={num_doc} | Itens={posting.items} | "
            f"Resultado=SUCESSO"
        )
        _record_external_status(
            num_doc=num_doc,
            status="LANCADO",
            motivo="SUCESSO",
            mensagem=message,
            itens=posting.items,
            fonte_externa=source.name,
            banco_externo=source.database,
            data_lancamento=True,
            config_path=config_path,
        )

        _write_user_log(
            level="OK",
            title="Lançamento de estoque realizado com sucesso",
            num_doc=num_doc,
            why=(
                "A conferência foi finalizada e o lançamento foi "
                "processado na Fonte de Dados Externa."
            ),
            what_to_do="Nenhuma ação necessária.",
            detail=(
                f"Itens movimentados={posting.items}. "
                "Saldo do estoque atualizado e movimentação registrada."
            ),
            config_path=config_path,
        )
        return ExternalSyncResult(
            "POSTED",
            num_doc,
            message,
            posting.items,
        )

    if posting.status == "ALREADY_POSTED":
        message = (
            "Documento já lançado anteriormente. "
            "Nenhuma nova baixa de estoque foi executada."
        )
        logging.info(
            f"[FONTE EXTERNA][DOCUMENTO JA LANCADO] "
            f"Documento={num_doc} | Nenhuma nova gravacao executada."
        )
        _record_external_status(
            num_doc=num_doc,
            status="LANCADO",
            motivo="JA_LANCADO",
            mensagem=message,
            itens=0,
            fonte_externa=source.name,
            banco_externo=source.database,
            data_lancamento=False,
            config_path=config_path,
        )

        _write_user_log(
            level="INFO",
            title="Documento já processado anteriormente",
            num_doc=num_doc,
            why=(
                "Já existe uma movimentação de saída concluída "
                "com sucesso para este documento."
            ),
            what_to_do="Nenhuma ação necessária.",
            detail="Proteção contra lançamento duplicado acionada.",
            config_path=config_path,
        )
        return ExternalSyncResult(
            "ALREADY_POSTED",
            num_doc,
            message,
            0,
        )

    message = posting.message or "Lançamento externo não concluído."
    logging.error(
        f"[FONTE EXTERNA][LANCAMENTO BLOQUEADO] "
        f"Documento={num_doc} | Status={posting.status} | "
        f"Motivo={message}"
    )
    _record_external_status(
        num_doc=num_doc,
        status="NAO_LANCADO",
        motivo=posting.status,
        mensagem=message,
        itens=posting.items,
        fonte_externa=source.name if source.configured else "",
        banco_externo=source.database if source.configured else "",
        config_path=config_path,
    )

    _write_user_log(
        level="ERRO",
        title="Lançamento de estoque não realizado",
        num_doc=num_doc,
        why=message,
        what_to_do=(
            "Verifique o Log Técnico e a Fonte de Dados Externa. "
            "Se houve falha durante a transação, o rollback preservou o estoque."
        ),
        detail=f"Status técnico={posting.status}.",
        config_path=config_path,
    )
    return ExternalSyncResult(
        posting.status,
        num_doc,
        message,
        posting.items,
    )



def sync_completed_document(
    settings,
    num_doc: str,
) -> ExternalSyncResult:
    """
    Compatibilidade temporária.
    Na Etapa 7A redireciona para o preflight automático, SEM GRAVAÇÃO.
    """
    return automatic_external_preflight(num_doc)


if __name__ == "__main__":
    print("VERSAO     =", VERSION_MARKER)
    print("MODO       = PREFLIGHT AUTOMATICO - SEM GRAVACAO")
    print("OPERACAO   = SAIDA (SALDO ATUAL - QTDE LIDA)")
    print()

    source = load_external_data_source()

    print("CONFIGURED =", source.configured)
    print("VALID      =", source.valid)
    print("NAME       =", source.name)
    print("SERVER     =", source.server)
    print("DATABASE   =", source.database)
    print("TABLE      =", source.table)
    print("LOCAL      =", source.field_local)
    print("ERROR      =", source.error)

    num_doc = input(
        "\nInforme o NumDoc/NF para executar o PREFLIGHT "
        "(ou ENTER para sair): "
    ).strip()

    if num_doc:
        result = automatic_external_preflight(num_doc)

        print()
        print("=== RESULTADO PREFLIGHT AUTOMATICO ===")
        print("DOCUMENTO =", result.num_doc)
        print("STATUS    =", result.status)
        print("ITENS     =", result.items)
        print("MESSAGE   =", result.message)
        print()
        print("CONFIRMACAO: nenhum estoque foi alterado.")

    input("\nPressione ENTER para fechar...")
