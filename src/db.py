from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
import pyodbc

from .settings import SqlSettings


class DuplicateDocumentError(Exception):
    """Documento já importado ou bloqueado por UNIQUE/CONSTRAINT."""
    pass


def build_conn_str(sql_cfg: SqlSettings) -> str:
    driver = sql_cfg.driver
    server = sql_cfg.server
    database = sql_cfg.database

    if sql_cfg.trusted_connection:
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={sql_cfg.user};"
        f"PWD={sql_cfg.password};"
        "TrustServerCertificate=yes;"
    )


def get_connection(sql_cfg: SqlSettings):
    return pyodbc.connect(build_conn_str(sql_cfg), autocommit=False)


def _to_int_or_raise(value) -> int:
    s = str(value).strip()
    if s == "":
        raise ValueError("NumNF vazio.")
    return int(s)


def numdoc_exists(conn, num_doc: str) -> bool:
    """Considera importado se já existe qualquer item no prodConf OU cabeçalho no logConf."""
    cur = conn.cursor()

    # 1) logConf
    try:
        num_nf_db = _to_int_or_raise(num_doc)
        cur.execute("SELECT TOP 1 1 FROM dbo.logConf WHERE NumNF = ?", (num_nf_db,))
        if cur.fetchone() is not None:
            return True
    except Exception:
        pass

    # 2) prodConf
    cur.execute("SELECT TOP 1 1 FROM dbo.prodConf WHERE NumDoc = ?", (str(num_doc),))
    return cur.fetchone() is not None


def prodconf_has_column(conn, column_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM sys.columns
        WHERE object_id = OBJECT_ID('dbo.prodConf')
          AND name = ?
        """,
        (column_name,),
    )
    return cur.fetchone() is not None


def ensure_logconf_header(conn, num_nf: str, nome_cli: str, status_conf: str = "AGUARDANDO"):
    """
    Garante 1 linha no logConf (não duplica).
    NÃO dá commit aqui.
    """
    cur = conn.cursor()
    num_nf_db = _to_int_or_raise(num_nf)

    cur.execute("SELECT TOP 1 1 FROM dbo.logConf WHERE NumNF = ?", (num_nf_db,))
    if cur.fetchone() is not None:
        return

    cur.execute(
        "INSERT INTO dbo.logConf (NumNF, NomeCli, StatusConf) VALUES (?, ?, ?)",
        (num_nf_db, str(nome_cli)[:80], status_conf),
    )


def insert_prodconf_items(conn, num_doc: str, nome_cli: str, itens: list[dict], status_inicial: str):
    """
    Insere em prodConf e garante cabeçalho no logConf.
    """
    has_nitem = prodconf_has_column(conn, "NItem")
    has_localizacao = prodconf_has_column(conn, "Localizacao")

    data_imp = date.today()
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if numdoc_exists(conn, num_doc):
        conn.rollback()
        raise DuplicateDocumentError(f"NumDoc {num_doc} já importado.")

    ensure_logconf_header(conn, num_doc, nome_cli, status_conf="AGUARDANDO")

    if has_nitem and has_localizacao:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, NItem, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora, Localizacao)
        VALUES
          (?,      ?,       ?,     ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?,        ?)
        """
    elif has_nitem and not has_localizacao:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, NItem, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora)
        VALUES
          (?,      ?,       ?,     ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?)
        """
    elif (not has_nitem) and has_localizacao:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora, Localizacao)
        VALUES
          (?,      ?,       ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?,        ?)
        """
    else:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora)
        VALUES
          (?,      ?,       ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?)
        """

    cur = conn.cursor()
    try:
        for it in itens:
            codprod = str(it.get("CodProd", ""))[:50]
            gtin = int(it.get("GTIN", 0) or 0)
            desc = str(it.get("DescProd", ""))[:50]
            qtde = Decimal(str(it.get("QtdeDoc", "0")))
            qtde_lido = Decimal("0")

            localizacao = (it.get("Localizacao", "") or "")[:50]  # pode ser vazio

            if has_nitem:
                nitem = it.get("NItem", None)
                if has_localizacao:
                    cur.execute(sql, (
                        str(num_doc)[:50],
                        str(nome_cli)[:50],
                        data_imp,
                        nitem,
                        codprod,
                        gtin,
                        desc,
                        qtde,
                        qtde_lido,
                        str(status_inicial)[:4],
                        str(data_hora)[:50],
                        localizacao,
                    ))
                else:
                    cur.execute(sql, (
                        str(num_doc)[:50],
                        str(nome_cli)[:50],
                        data_imp,
                        nitem,
                        codprod,
                        gtin,
                        desc,
                        qtde,
                        qtde_lido,
                        str(status_inicial)[:4],
                        str(data_hora)[:50],
                    ))
            else:
                if has_localizacao:
                    cur.execute(sql, (
                        str(num_doc)[:50],
                        str(nome_cli)[:50],
                        data_imp,
                        codprod,
                        gtin,
                        desc,
                        qtde,
                        qtde_lido,
                        str(status_inicial)[:4],
                        str(data_hora)[:50],
                        localizacao,
                    ))
                else:
                    cur.execute(sql, (
                        str(num_doc)[:50],
                        str(nome_cli)[:50],
                        data_imp,
                        codprod,
                        gtin,
                        desc,
                        qtde,
                        qtde_lido,
                        str(status_inicial)[:4],
                        str(data_hora)[:50],
                    ))

        conn.commit()

    except pyodbc.IntegrityError:
        conn.rollback()
        raise DuplicateDocumentError(
            f"Falha de integridade ao inserir NumDoc {num_doc} (verifique UNIQUE/CONSTRAINT)."
        )