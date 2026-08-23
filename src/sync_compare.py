from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from .db import get_connection


@dataclass
class DiferencaCampo:
    campo: str
    valor_sql: Any
    valor_txt: Any


@dataclass
class ResultadoComparacaoRegistro:
    tipo: str
    linha: int
    chave: str
    situacao: str  # NOVO, IGUAL, DIFERENTE, ERRO
    diferencas: list[DiferencaCampo] = field(default_factory=list)
    mensagem: str = ""


@dataclass
class ResumoComparacao:
    novos: int = 0
    iguais: int = 0
    diferentes: int = 0
    erros: int = 0
    registros: list[ResultadoComparacaoRegistro] = field(default_factory=list)


def _norm_texto(valor) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def _norm_hora(valor) -> str:
    texto = _norm_texto(valor)
    return texto.replace(":", "")


def _norm_numero(valor) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip()

    try:
        numero = Decimal(texto).normalize()
        return format(numero, "f")
    except Exception:
        return texto


def _adicionar_resultado(resumo: ResumoComparacao, resultado: ResultadoComparacaoRegistro):
    resumo.registros.append(resultado)

    if resultado.situacao == "NOVO":
        resumo.novos += 1
    elif resultado.situacao == "IGUAL":
        resumo.iguais += 1
    elif resultado.situacao == "DIFERENTE":
        resumo.diferentes += 1
    else:
        resumo.erros += 1


def comparar_logconf(settings, registros) -> ResumoComparacao:
    """
    LOGCONF

    A tabela dbo.logConf já possui uma linha por nota.
    O arquivo pode conter várias ocorrências da mesma NumNF.

    Consolidação por NumNF:
    - UserIniConf / HoraIniConf: primeira ocorrência da nota.
    - Se existir ocorrência CONFERIDO:
        UserFimConf / HoraFimConf / StatusConf vêm da última ocorrência CONFERIDO.
    - Caso contrário:
        UserFimConf e HoraFimConf ficam vazios e StatusConf fica ANDAMENTO.

    A localização no SQL Server é feita somente por NumNF.
    Somente consulta/compara.
    Não executa INSERT nem UPDATE.
    """
    resumo = ResumoComparacao()
    conn = get_connection(settings.sql)

    # Preserva a ordem da primeira ocorrência de cada nota.
    consolidados = {}

    for reg in registros:
        num_nf = reg.num_nf

        if num_nf not in consolidados:
            consolidados[num_nf] = {
                "linha": reg.linha,
                "num_nf": num_nf,
                "user_ini": _norm_texto(reg.user_ini),
                "hora_ini": _norm_hora(reg.hora_ini),
                "user_fim": "",
                "hora_fim": "",
                "status": "ANDAMENTO",
            }

        status_atual = _norm_texto(reg.status).upper()

        # Se a nota foi concluída, a última ocorrência CONFERIDO
        # representa o estado final da conferência.
        if status_atual == "CONFERIDO":
            consolidados[num_nf]["user_fim"] = _norm_texto(reg.user_fim)
            consolidados[num_nf]["hora_fim"] = _norm_hora(reg.hora_fim)
            consolidados[num_nf]["status"] = "CONFERIDO"

    try:
        cur = conn.cursor()

        for dados in consolidados.values():
            chave = f"NumNF={dados['num_nf']}"

            try:
                cur.execute(
                    """
                    SELECT
                        NumNF,
                        UserIniConf,
                        UserFimConf,
                        HoraIniConf,
                        HoraFimConf,
                        StatusConf
                    FROM dbo.logConf
                    WHERE NumNF = ?
                    """,
                    (int(dados["num_nf"]),),
                )

                rows = cur.fetchall()

                if len(rows) == 0:
                    _adicionar_resultado(
                        resumo,
                        ResultadoComparacaoRegistro(
                            tipo="LOGCONF",
                            linha=dados["linha"],
                            chave=chave,
                            situacao="NOVO",
                            mensagem="Nota não localizada no SQL Server.",
                        ),
                    )
                    continue

                if len(rows) > 1:
                    _adicionar_resultado(
                        resumo,
                        ResultadoComparacaoRegistro(
                            tipo="LOGCONF",
                            linha=dados["linha"],
                            chave=chave,
                            situacao="ERRO",
                            mensagem=(
                                f"Busca ambígua: {len(rows)} registros "
                                f"encontrados para NumNF."
                            ),
                        ),
                    )
                    continue

                row = rows[0]

                comparacoes = [
                    (
                        "UserIniConf",
                        _norm_texto(row.UserIniConf),
                        dados["user_ini"],
                    ),
                    (
                        "UserFimConf",
                        _norm_texto(row.UserFimConf),
                        dados["user_fim"],
                    ),
                    (
                        "HoraIniConf",
                        _norm_hora(row.HoraIniConf),
                        dados["hora_ini"],
                    ),
                    (
                        "HoraFimConf",
                        _norm_hora(row.HoraFimConf),
                        dados["hora_fim"],
                    ),
                    (
                        "StatusConf",
                        _norm_texto(row.StatusConf).upper(),
                        dados["status"],
                    ),
                ]

                diferencas = [
                    DiferencaCampo(campo, valor_sql, valor_txt)
                    for campo, valor_sql, valor_txt in comparacoes
                    if valor_sql != valor_txt
                ]

                _adicionar_resultado(
                    resumo,
                    ResultadoComparacaoRegistro(
                        tipo="LOGCONF",
                        linha=dados["linha"],
                        chave=chave,
                        situacao="DIFERENTE" if diferencas else "IGUAL",
                        diferencas=diferencas,
                    ),
                )

            except Exception as e:
                _adicionar_resultado(
                    resumo,
                    ResultadoComparacaoRegistro(
                        tipo="LOGCONF",
                        linha=dados["linha"],
                        chave=chave,
                        situacao="ERRO",
                        mensagem=str(e),
                    ),
                )

    finally:
        conn.close()

    return resumo

def comparar_prodconf(settings, registros) -> ResumoComparacao:
    """
    PRODCONF

    NumDoc corresponde à nota.

    Localização:
    - apenas CodProd: NumDoc + CodProd
    - apenas EAN/GTIN: NumDoc + GTIN
    - ambos: NumDoc + (CodProd OU GTIN)

    Mais de um resultado = busca ambígua.
    Somente consulta/compara.
    """

    resumo = ResumoComparacao()
    conn = get_connection(settings.sql)

    try:
        cur = conn.cursor()

        for reg in registros:
            ean = _norm_texto(reg.ean)
            cod = _norm_texto(reg.cod_prod)

            chave = (
                f"NumDoc={reg.num_doc} "
                f"EAN={ean or '-'} "
                f"CodProd={cod or '-'}"
            )

            try:
                if ean and cod:
                    cur.execute(
                        """
                        SELECT
                            NumDoc,
                            CodProd,
                            GTIN,
                            QtdeLido,
                            Saldo,
                            Status
                        FROM dbo.prodConf
                        WHERE CAST(NumDoc AS VARCHAR(50)) = ?
                          AND (
                                LTRIM(RTRIM(ISNULL(CAST(CodProd AS VARCHAR(100)), ''))) = ?
                                OR
                                LTRIM(RTRIM(ISNULL(CAST(GTIN AS VARCHAR(100)), ''))) = ?
                              )
                        """,
                        (
                            str(reg.num_doc),
                            cod,
                            ean,
                        ),
                    )

                elif cod:
                    cur.execute(
                        """
                        SELECT
                            NumDoc,
                            CodProd,
                            GTIN,
                            QtdeLido,
                            Saldo,
                            Status
                        FROM dbo.prodConf
                        WHERE CAST(NumDoc AS VARCHAR(50)) = ?
                          AND LTRIM(
                                RTRIM(
                                    ISNULL(
                                        CAST(CodProd AS VARCHAR(100)),
                                        ''
                                    )
                                )
                              ) = ?
                        """,
                        (
                            str(reg.num_doc),
                            cod,
                        ),
                    )

                else:
                    cur.execute(
                        """
                        SELECT
                            NumDoc,
                            CodProd,
                            GTIN,
                            QtdeLido,
                            Saldo,
                            Status
                        FROM dbo.prodConf
                        WHERE CAST(NumDoc AS VARCHAR(50)) = ?
                          AND LTRIM(
                                RTRIM(
                                    ISNULL(
                                        CAST(GTIN AS VARCHAR(100)),
                                        ''
                                    )
                                )
                              ) = ?
                        """,
                        (
                            str(reg.num_doc),
                            ean,
                        ),
                    )

                rows = cur.fetchall()

                if len(rows) == 0:
                    _adicionar_resultado(
                        resumo,
                        ResultadoComparacaoRegistro(
                            tipo="PRODCONF",
                            linha=reg.linha,
                            chave=chave,
                            situacao="NOVO",
                            mensagem="Registro não localizado no SQL Server.",
                        ),
                    )
                    continue

                if len(rows) > 1:
                    _adicionar_resultado(
                        resumo,
                        ResultadoComparacaoRegistro(
                            tipo="PRODCONF",
                            linha=reg.linha,
                            chave=chave,
                            situacao="ERRO",
                            mensagem=f"Busca ambígua: {len(rows)} registros encontrados.",
                        ),
                    )
                    continue

                row = rows[0]

                comparacoes = [
                    (
                        "QtdeLido",
                        _norm_numero(row.QtdeLido),
                        _norm_numero(reg.qtde_lido),
                    ),
                    (
                        "Saldo",
                        _norm_numero(row.Saldo),
                        _norm_numero(reg.saldo),
                    ),
                    (
                        "Status",
                        _norm_texto(row.Status).upper(),
                        _norm_texto(reg.status).upper(),
                    ),
                ]

                diferencas = [
                    DiferencaCampo(
                        campo,
                        valor_sql,
                        valor_txt,
                    )
                    for campo, valor_sql, valor_txt in comparacoes
                    if valor_sql != valor_txt
                ]

                _adicionar_resultado(
                    resumo,
                    ResultadoComparacaoRegistro(
                        tipo="PRODCONF",
                        linha=reg.linha,
                        chave=chave,
                        situacao=(
                            "DIFERENTE"
                            if diferencas
                            else "IGUAL"
                        ),
                        diferencas=diferencas,
                    ),
                )

            except Exception as e:
                _adicionar_resultado(
                    resumo,
                    ResultadoComparacaoRegistro(
                        tipo="PRODCONF",
                        linha=reg.linha,
                        chave=chave,
                        situacao="ERRO",
                        mensagem=str(e),
                    ),
                )

    finally:
        conn.close()

    return resumo