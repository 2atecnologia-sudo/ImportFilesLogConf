from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
import pyodbc

from .settings import SqlSettings


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
    """
    NumNF no SQL é numeric. Aqui garantimos que vai como int.
    Se não for possível converter, levantamos erro para não gravar lixo.
    """
    s = str(value).strip()
    if s == "":
        raise ValueError("NumNF vazio.")
    return int(s)


def numdoc_exists(conn, num_doc: str) -> bool:
    cur = conn.cursor()

    # checa cabeçalho (logConf) primeiro
    try:
        num_nf_db = _to_int_or_raise(num_doc)
        cur.execute("SELECT TOP 1 1 FROM dbo.logConf WHERE NumNF = ?", (num_nf_db,))
        if cur.fetchone() is not None:
            return True
    except Exception:
        pass

    # fallback: checa detalhe (prodConf)
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


def insert_logconf_header(conn, num_nf: str, nome_cli: str, status_conf: str = "AGUARDANDO", coletor_id: str | None = None):
    """
    Insere 1 linha em dbo.logConf com (NumNF, NomeCli, StatusConf).
    Se já existir, não faz nada.
    Não faz COMMIT aqui (commit é feito no final junto com prodConf).
    """
    cur = conn.cursor()

    num_nf_db = _to_int_or_raise(num_nf)

    # ignora duplicidade
    cur.execute("SELECT TOP 1 1 FROM dbo.logConf WHERE NumNF = ?", (num_nf_db,))
    if cur.fetchone() is not None:
        return

    sql = """
    INSERT INTO dbo.logConf (NumNF, NomeCli, StatusConf, ColetorID)
    VALUES (?, ?, ?, ?)
    """
    cur.execute(sql, (num_nf_db, str(nome_cli)[:80], status_conf, str(coletor_id or "")[:100]))


def insert_prodconf_items(conn, num_doc: str, nome_cli: str, itens: list[dict], status_inicial: str, coletor_id: str | None = None):
    """
    Insere cabeçalho em dbo.logConf (NumNF, NomeCli, StatusConf="AGUARDANDO")
    e itens em dbo.prodConf.

    Cada item deve ter:
      CodProd, GTIN, DescProd, QtdeDoc
    E opcionalmente:
      NItem (int)  -> só será gravado se a coluna existir no banco
    """
    has_nitem = prodconf_has_column(conn, "NItem")

    data_imp = date.today()
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # >>> Cabeçalho (logConf)
    insert_logconf_header(conn, num_doc, nome_cli, status_conf="AGUARDANDO", coletor_id=coletor_id)

    # >>> Detalhe (prodConf)
    if has_nitem:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, NItem, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora, ColetorID)
        VALUES
          (?,      ?,       ?,     ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?,         ?)
        """
    else:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora, ColetorID)
        VALUES
          (?,      ?,       ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?,         ?)
        """

    cur = conn.cursor()
    for it in itens:
        codprod = str(it.get("CodProd", ""))[:50]
        gtin = int(it.get("GTIN", 0) or 0)
        desc = str(it.get("DescProd", ""))[:50]
        qtde = Decimal(str(it.get("QtdeDoc", "0")))
        qtde_lido = Decimal("0")

        if has_nitem:
            nitem = it.get("NItem", None)
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
                str(status_inicial)[:3],
                str(data_hora)[:50],
                str(coletor_id or "")[:100],
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
                str(status_inicial)[:3],
                str(data_hora)[:50],
                str(coletor_id or "")[:100],
            ))

    conn.commit()

def get_conference_table_counts(conn) -> tuple[int, int]:
    """Retorna (qtd_logconf, qtd_prodconf)."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dbo.logConf")
    qtd_logconf = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM dbo.prodConf")
    qtd_prodconf = int(cur.fetchone()[0] or 0)
    return qtd_logconf, qtd_prodconf


def normalize_empty_conference_tables(conn) -> tuple[int, int, bool]:
    """Normaliza logConf/prodConf quando uma ou ambas estiverem vazias."""
    qtd_logconf, qtd_prodconf = get_conference_table_counts(conn)

    if qtd_logconf == 0 and qtd_prodconf == 0:
        return qtd_logconf, qtd_prodconf, True

    if qtd_logconf == 0 and qtd_prodconf > 0:
        conn.cursor().execute("DELETE FROM dbo.prodConf")
        conn.commit()
        return qtd_logconf, qtd_prodconf, True

    if qtd_logconf > 0 and qtd_prodconf == 0:
        conn.cursor().execute("DELETE FROM dbo.logConf")
        conn.commit()
        return qtd_logconf, qtd_prodconf, True

    return qtd_logconf, qtd_prodconf, False
