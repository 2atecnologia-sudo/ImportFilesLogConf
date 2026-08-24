from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .db import get_connection


class SyncWriteError(RuntimeError):
    """Erro de consistência/gravação da sincronização."""


@dataclass
class ResultadoGravacao:
    logconf_atualizados: int = 0
    prodconf_atualizados: int = 0


def _texto(valor) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def _hora_normalizada(valor) -> str:
    return _texto(valor).replace(":", "")


def _numero_normalizado(valor) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip()

    try:
        return format(Decimal(texto).normalize(), "f")
    except Exception:
        return texto


def _decimal_ou_none(valor):
    texto = _texto(valor)
    if texto == "":
        return None
    return Decimal(texto)


def _consolidar_logconf(registros):
    consolidados = {}

    for reg in registros:
        num_nf = str(reg.num_nf).strip()

        if num_nf not in consolidados:
            consolidados[num_nf] = {
                "num_nf": num_nf,
                "user_ini": _texto(reg.user_ini),
                "hora_ini": _hora_normalizada(reg.hora_ini),
                "user_fim": "",
                "hora_fim": "",
                "status": "ANDAMENTO",
            }

        if _texto(reg.status).upper() == "CONFERIDO":
            consolidados[num_nf]["user_fim"] = _texto(reg.user_fim)
            consolidados[num_nf]["hora_fim"] = _hora_normalizada(reg.hora_fim)
            consolidados[num_nf]["status"] = "CONFERIDO"

    return list(consolidados.values())


def _tipo_coluna(conn, tabela: str, coluna: str) -> str:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT TYPE_NAME(c.user_type_id)
        FROM sys.columns c
        WHERE c.object_id = OBJECT_ID(?)
          AND c.name = ?
        """,
        (tabela, coluna),
    )
    row = cur.fetchone()

    if row is None:
        raise SyncWriteError(
            f"Coluna {coluna} não encontrada em {tabela}."
        )

    return str(row[0]).lower()


def _valor_hora_para_sql(hora: str, tipo_sql: str):
    hora = _hora_normalizada(hora)

    if hora == "":
        return None

    if tipo_sql == "time":
        if len(hora) != 6 or not hora.isdigit():
            raise SyncWriteError(
                f"Hora inválida para coluna TIME: {hora!r}"
            )
        return f"{hora[0:2]}:{hora[2:4]}:{hora[4:6]}"

    return hora


def _buscar_prodconf(cur, reg, lock: bool = False):
    ean = _texto(reg.ean)
    cod = _texto(reg.cod_prod)
    hint = " WITH (UPDLOCK, HOLDLOCK)" if lock else ""

    if ean and cod:
        sql = f"""
            SELECT NumDoc, CodProd, GTIN, QtdeLido, Saldo, Localizacao, Status
            FROM dbo.prodConf{hint}
            WHERE CAST(NumDoc AS VARCHAR(50)) = ?
              AND (
                    LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
                    OR
                    LTRIM(RTRIM(ISNULL(CAST(GTIN AS VARCHAR(100)), ''))) = ?
                  )
        """
        params = (str(reg.num_doc), cod, ean)

    elif cod:
        sql = f"""
            SELECT NumDoc, CodProd, GTIN, QtdeLido, Saldo, Localizacao, Status
            FROM dbo.prodConf{hint}
            WHERE CAST(NumDoc AS VARCHAR(50)) = ?
              AND LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
        """
        params = (str(reg.num_doc), cod)

    else:
        if not ean:
            raise SyncWriteError(
                f"PRODCONF linha {reg.linha}: EAN/GTIN e CodProd vazios."
            )

        sql = f"""
            SELECT NumDoc, CodProd, GTIN, QtdeLido, Saldo, Localizacao, Status
            FROM dbo.prodConf{hint}
            WHERE CAST(NumDoc AS VARCHAR(50)) = ?
              AND LTRIM(RTRIM(ISNULL(CAST(GTIN AS VARCHAR(100)), ''))) = ?
        """
        params = (str(reg.num_doc), ean)

    cur.execute(sql, params)
    return cur.fetchall()


def _update_prodconf(cur, reg):
    ean = _texto(reg.ean)
    cod = _texto(reg.cod_prod)

    valores = (
        _decimal_ou_none(reg.qtde_lido),
        _decimal_ou_none(reg.saldo),
        _texto(reg.localizacao) or None,
        _texto(reg.status).upper(),
    )

    if ean and cod:
        sql = """
            UPDATE dbo.prodConf
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?
             WHERE CAST(NumDoc AS VARCHAR(50)) = ?
               AND (
                    LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
                    OR
                    LTRIM(RTRIM(ISNULL(CAST(GTIN AS VARCHAR(100)), ''))) = ?
                   )
        """
        params = valores + (str(reg.num_doc), cod, ean)

    elif cod:
        sql = """
            UPDATE dbo.prodConf
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?
             WHERE CAST(NumDoc AS VARCHAR(50)) = ?
               AND LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
        """
        params = valores + (str(reg.num_doc), cod)

    else:
        sql = """
            UPDATE dbo.prodConf
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?
             WHERE CAST(NumDoc AS VARCHAR(50)) = ?
               AND LTRIM(RTRIM(ISNULL(CAST(GTIN AS VARCHAR(100)), ''))) = ?
        """
        params = valores + (str(reg.num_doc), ean)

    cur.execute(sql, params)

    if cur.rowcount != 1:
        raise SyncWriteError(
            f"PRODCONF linha {reg.linha}: UPDATE afetou "
            f"{cur.rowcount} registros; esperado=1."
        )


def aplicar_sincronizacao(settings, registros_logconf, registros_prodconf) -> ResultadoGravacao:
    conn = get_connection(settings.sql)
    resultado = ResultadoGravacao()

    try:
        cur = conn.cursor()
        logconf = _consolidar_logconf(registros_logconf)

        tipo_hora_ini = _tipo_coluna(conn, "dbo.logConf", "HoraIniConf")
        tipo_hora_fim = _tipo_coluna(conn, "dbo.logConf", "HoraFimConf")

        for item in logconf:
            cur.execute(
                """
                SELECT NumNF, UserIniConf, UserFimConf, HoraIniConf, HoraFimConf, StatusConf
                FROM dbo.logConf WITH (UPDLOCK, HOLDLOCK)
                WHERE NumNF = ?
                """,
                (int(item["num_nf"]),),
            )
            rows = cur.fetchall()

            if len(rows) != 1:
                raise SyncWriteError(
                    f"LOGCONF NumNF={item['num_nf']}: encontrados={len(rows)}; esperado=1."
                )

        for reg in registros_prodconf:
            rows = _buscar_prodconf(cur, reg, lock=True)

            if len(rows) != 1:
                raise SyncWriteError(
                    f"PRODCONF linha={reg.linha} NumDoc={reg.num_doc}: "
                    f"encontrados={len(rows)}; esperado=1."
                )

        for item in logconf:
            cur.execute(
                """
                UPDATE dbo.logConf
                   SET UserIniConf = ?,
                       UserFimConf = ?,
                       HoraIniConf = ?,
                       HoraFimConf = ?,
                       StatusConf = ?
                 WHERE NumNF = ?
                """,
                (
                    item["user_ini"] or None,
                    item["user_fim"] or None,
                    _valor_hora_para_sql(item["hora_ini"], tipo_hora_ini),
                    _valor_hora_para_sql(item["hora_fim"], tipo_hora_fim),
                    item["status"],
                    int(item["num_nf"]),
                ),
            )

            if cur.rowcount != 1:
                raise SyncWriteError(
                    f"LOGCONF NumNF={item['num_nf']}: UPDATE afetou "
                    f"{cur.rowcount} registros; esperado=1."
                )

            resultado.logconf_atualizados += 1

        for reg in registros_prodconf:
            _update_prodconf(cur, reg)
            resultado.prodconf_atualizados += 1

        for item in logconf:
            cur.execute(
                """
                SELECT UserIniConf, UserFimConf, HoraIniConf, HoraFimConf, StatusConf
                FROM dbo.logConf
                WHERE NumNF = ?
                """,
                (int(item["num_nf"]),),
            )
            row = cur.fetchone()

            esperado = (
                item["user_ini"],
                item["user_fim"],
                item["hora_ini"],
                item["hora_fim"],
                item["status"],
            )
            obtido = (
                _texto(row.UserIniConf),
                _texto(row.UserFimConf),
                _hora_normalizada(row.HoraIniConf),
                _hora_normalizada(row.HoraFimConf),
                _texto(row.StatusConf).upper(),
            )

            if obtido != esperado:
                raise SyncWriteError(
                    f"LOGCONF NumNF={item['num_nf']}: verificação falhou. "
                    f"Esperado={esperado!r} Obtido={obtido!r}"
                )

        for reg in registros_prodconf:
            rows = _buscar_prodconf(cur, reg, lock=False)

            if len(rows) != 1:
                raise SyncWriteError(
                    f"PRODCONF linha={reg.linha}: verificação encontrou "
                    f"{len(rows)} registros."
                )

            row = rows[0]
            esperado = (
                _numero_normalizado(reg.qtde_lido),
                _numero_normalizado(reg.saldo),
                _texto(reg.localizacao),
                _texto(reg.status).upper(),
            )
            obtido = (
                _numero_normalizado(row.QtdeLido),
                _numero_normalizado(row.Saldo),
                _texto(row.Localizacao),
                _texto(row.Status).upper(),
            )

            if obtido != esperado:
                raise SyncWriteError(
                    f"PRODCONF linha={reg.linha} NumDoc={reg.num_doc}: "
                    f"verificação falhou. "
                    f"Esperado={esperado!r} Obtido={obtido!r}"
                )

        conn.commit()
        return resultado

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    finally:
        conn.close()