from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import logging
import os

from .db import get_connection


class SyncWriteError(RuntimeError):
    """Erro de consistência/gravação da sincronização."""


@dataclass
class ResultadoGravacao:
    logconf_atualizados: int = 0
    prodconf_atualizados: int = 0
    scanocor_inseridos: int = 0
    scanocor_duplicados: int = 0


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


def _update_prodconf(cur, reg, coletor_id: str = ""):
    ean = _texto(reg.ean)
    cod = _texto(reg.cod_prod)

    valores = (
        _decimal_ou_none(reg.qtde_lido),
        _decimal_ou_none(reg.saldo),
        _texto(reg.localizacao) or None,
        _texto(reg.status).upper(),
        _texto(coletor_id) or None,
    )

    if ean and cod:
        sql = """
            UPDATE dbo.prodConf
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?, ColetorID = ?
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
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?, ColetorID = ?
             WHERE CAST(NumDoc AS VARCHAR(50)) = ?
               AND LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
        """
        params = valores + (str(reg.num_doc), cod)

    else:
        sql = """
            UPDATE dbo.prodConf
               SET QtdeLido = ?, Saldo = ?, Localizacao = ?, Status = ?, ColetorID = ?
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



def _saldo_exatamente_zero(valor) -> bool:
    if valor is None:
        return False
    try:
        return Decimal(str(valor)) == Decimal("0")
    except Exception:
        return False


def _nome_arquivo_individual(num_doc: str, modo: str) -> str:
    agora = datetime.now()
    num_doc = _texto(num_doc)

    if modo == "numdoc":
        return f"{num_doc}.txt"
    if modo == "numdoc_data":
        return f"{num_doc}_{agora.strftime('%d%m%Y')}.txt"

    return f"{num_doc}_{agora.strftime('%d%m%Y_%H%M%S')}.txt"


def _gerar_arquivo_individual_se_concluido(conn, settings, num_doc: str):
    if not getattr(settings, "output", None):
        return None

    if not settings.output.individual_file:
        return None

    cur = conn.cursor()

    cur.execute(
        """
        SELECT TOP 1 StatusConf
        FROM dbo.logConf
        WHERE CAST(NumNF AS VARCHAR(50)) = ?
        """,
        (str(num_doc),),
    )
    row_status = cur.fetchone()

    if row_status is None:
        logging.info(
            f"[SAIDA INDIVIDUAL NAO GERADA] NumDoc={num_doc} | "
            f"Motivo=LOGCONF não encontrado."
        )
        return None

    status_conf = _texto(row_status.StatusConf).upper()
    if status_conf != "CONFERIDO":
        logging.info(
            f"[SAIDA INDIVIDUAL NAO GERADA] NumDoc={num_doc} | "
            f"Motivo=StatusConf={status_conf or 'VAZIO'}."
        )
        return None

    cur.execute(
        """
        SELECT CodProd, GTIN, QtdeLido, Saldo
        FROM dbo.prodConf
        WHERE CAST(NumDoc AS VARCHAR(50)) = ?
        """,
        (str(num_doc),),
    )
    itens = cur.fetchall()

    if not itens:
        logging.info(
            f"[SAIDA INDIVIDUAL NAO GERADA] NumDoc={num_doc} | "
            f"Motivo=nenhum item em PRODCONF."
        )
        return None

    if any(not _saldo_exatamente_zero(item.Saldo) for item in itens):
        logging.info(
            f"[SAIDA INDIVIDUAL NAO GERADA] NumDoc={num_doc} | "
            f"Motivo=existe Saldo NULL/vazio ou diferente de zero."
        )
        return None

    output_dir = _texto(settings.output.output_dir) or r"C:\MIS\saida"
    os.makedirs(output_dir, exist_ok=True)

    delimitador = settings.output.delimiter or ";"
    modo_id = _texto(settings.output.product_id).lower()
    if modo_id not in ("codigo", "gtin", "ambos"):
        modo_id = "ambos"

    incluir_numdoc = bool(settings.output.include_numdoc)
    linhas = []

    for item in itens:
        cod = _texto(item.CodProd)
        gtin = _texto(item.GTIN)
        qtde = _numero_normalizado(item.QtdeLido)

        if cod and gtin and cod == gtin:
            gtin = ""

        campos = []
        if incluir_numdoc:
            campos.append(str(num_doc))

        if modo_id == "codigo":
            campos.append(cod)
        elif modo_id == "gtin":
            campos.append(gtin or cod)
        else:
            campos.extend([cod, gtin])

        campos.append(qtde)
        linhas.append(delimitador.join(campos))

    nome = _nome_arquivo_individual(
        str(num_doc),
        _texto(settings.output.file_name_mode).lower(),
    )
    destino = os.path.join(output_dir, nome)
    temporario = destino + ".tmp"

    with open(temporario, "w", encoding="utf-8", newline="") as f:
        for linha in linhas:
            f.write(linha + "\n")

    os.replace(temporario, destino)

    logging.info(
        f"[SAIDA INDIVIDUAL GERADA] NumDoc={num_doc} | "
        f"Itens={len(linhas)} | Arquivo={destino}"
    )
    return destino


def aplicar_sincronizacao(settings, registros_logconf, registros_prodconf, coletor_id: str = "") -> ResultadoGravacao:
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
                       StatusConf = ?,
                       ColetorID = ?
                 WHERE NumNF = ?
                """,
                (
                    item["user_ini"] or None,
                    item["user_fim"] or None,
                    _valor_hora_para_sql(item["hora_ini"], tipo_hora_ini),
                    _valor_hora_para_sql(item["hora_fim"], tipo_hora_fim),
                    item["status"],
                    _texto(coletor_id) or None,
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
            _update_prodconf(cur, reg, coletor_id)
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

        for item in logconf:
            _gerar_arquivo_individual_se_concluido(
                conn,
                settings,
                item["num_nf"],
            )

        return resultado

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    finally:
        conn.close()

def aplicar_scanocor(settings, registros_scanocor, coletor_id: str) -> ResultadoGravacao:
    """
    Insere ocorrências de leitura em dbo.scanocorconf.
    Não faz UPDATE. Duplicidades são ignoradas pela chave lógica:
    NumNota + CodigoLido + DataErro + HoraErro + UserConf + ColetorID.
    """
    conn = get_connection(settings.sql)
    resultado = ResultadoGravacao()
    coletor_id = _texto(coletor_id)

    if not coletor_id:
        raise SyncWriteError("SCANOCOR: ColetorID vazio.")

    try:
        cur = conn.cursor()

        for reg in registros_scanocor:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM dbo.scanocorconf WITH (UPDLOCK, HOLDLOCK)
                WHERE CAST(NumNota AS VARCHAR(50)) = ?
                  AND LTRIM(RTRIM(ISNULL(CAST(CodigoLido AS VARCHAR(100)), ''))) = ?
                  AND DataErro = ?
                  AND HoraErro = ?
                  AND LTRIM(RTRIM(ISNULL(CAST(UserConf AS VARCHAR(100)), ''))) = ?
                  AND LTRIM(RTRIM(ISNULL(CAST(ColetorID AS VARCHAR(100)), ''))) = ?
                """,
                (
                    str(reg.num_nota),
                    _texto(reg.codigo_lido),
                    reg.data_erro,
                    reg.hora_erro,
                    _texto(reg.user_conf),
                    coletor_id,
                ),
            )

            if int(cur.fetchone()[0]) > 0:
                resultado.scanocor_duplicados += 1
                continue

            cur.execute(
                """
                INSERT INTO dbo.scanocorconf
                    (NumNota, NomeCli, CodigoLido, MotivoErro,
                     DataErro, HoraErro, UserConf, ColetorID)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(reg.num_nota),
                    _texto(reg.nome_cli) or None,
                    _texto(reg.codigo_lido) or None,
                    _texto(reg.motivo_erro) or None,
                    reg.data_erro,
                    reg.hora_erro,
                    _texto(reg.user_conf) or None,
                    coletor_id,
                ),
            )
            resultado.scanocor_inseridos += 1

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