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


def numdoc_exists(conn, num_doc: str) -> bool:
    cur = conn.cursor()
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


def insert_prodconf_items(conn, num_doc: str, nome_cli: str, itens: list[dict], status_inicial: str):
    """
    Insere itens na dbo.prodConf.
    Cada item deve ter:
      CodProd, GTIN, DescProd, QtdeDoc
    E opcionalmente:
      NItem (int)  -> só será gravado se a coluna existir no banco
    """
    has_nitem = prodconf_has_column(conn, "NItem")

    data_imp = date.today()
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if has_nitem:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, NItem, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora)
        VALUES
          (?,      ?,       ?,     ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?)
        """
    else:
        sql = """
        INSERT INTO dbo.prodConf
          (NumDoc, NomeCli, DataImp, CodProd, GTIN, DescProd, QtdeDoc, QtdeLido, Status, DataeHora)
        VALUES
          (?,      ?,       ?,     ?,       ?,    ?,        ?,       ?,        ?,      ?)
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
            ))

    conn.commit()