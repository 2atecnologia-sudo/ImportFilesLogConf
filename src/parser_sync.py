from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional


# ============================================================
# RESULTADOS
# ============================================================

@dataclass
class ErroRegistro:
    arquivo: str
    linha: int
    conteudo: str
    motivo: str


@dataclass
class LogConfRegistro:
    linha: int
    num_nf: str
    user_ini: str
    user_fim: str
    hora_ini: str
    hora_fim: str
    status: str


@dataclass
class ProdConfRegistro:
    linha: int
    num_doc: str
    qtde_lido: Decimal
    saldo: Decimal
    ean: str
    cod_prod: str
    status: str


@dataclass
class ResultadoArquivo:
    arquivo: str
    separador: str = ","
    registros_lidos: int = 0
    registros_validos: int = 0
    registros_invalidos: int = 0
    erro_estrutural: Optional[str] = None
    avisos: List[str] = field(default_factory=list)
    erros: List[ErroRegistro] = field(default_factory=list)
    registros: list = field(default_factory=list)

    @property
    def arquivo_valido(self) -> bool:
        return self.erro_estrutural is None


# ============================================================
# LEITURA
# ============================================================

def _ler_linhas(path: str) -> List[str]:
    """
    Tenta UTF-8 primeiro.
    Se não funcionar, tenta Windows-1252.
    """

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read().splitlines()

    except UnicodeDecodeError:
        with open(path, "r", encoding="cp1252") as f:
            return f.read().splitlines()


# ============================================================
# SEPARADOR
# ============================================================

def _detectar_separador(linhas: List[str], campos_esperados: int) -> Optional[str]:
    """
    Detecta automaticamente separadores conhecidos.

    Vírgula continua sendo o padrão oficial.

    Também aceita:
        ;
        |
        TAB
    """

    candidatos = [
        ",",
        ";",
        "|",
        "\t",
    ]

    linhas_validacao = [
        linha.strip()
        for linha in linhas
        if linha.strip()
    ]

    if not linhas_validacao:
        return None

    # testa algumas linhas para evitar decidir
    # com base em uma única linha problemática
    amostra = linhas_validacao[:10]

    melhor_separador = None
    melhor_pontuacao = 0

    for separador in candidatos:

        pontuacao = 0

        for linha in amostra:
            partes = linha.split(separador)

            if len(partes) == campos_esperados:
                pontuacao += 1

        if pontuacao > melhor_pontuacao:
            melhor_pontuacao = pontuacao
            melhor_separador = separador

    if melhor_pontuacao == 0:
        return None

    return melhor_separador


# ============================================================
# CONVERSÕES
# ============================================================

def _validar_numero_inteiro(valor: str) -> bool:
    valor = (valor or "").strip()

    if not valor:
        return False

    return valor.isdigit()


def _decimal(valor: str) -> Decimal:
    valor = (valor or "").strip()

    if valor == "":
        raise ValueError("valor numérico vazio")

    # tolera decimal com vírgula caso algum equipamento envie assim
    valor = valor.replace(",", ".")

    try:
        return Decimal(valor)

    except InvalidOperation:
        raise ValueError(
            f"valor numérico inválido: '{valor}'"
        )


# ============================================================
# LOGCONF
# ============================================================

def parse_logconf(path: str) -> ResultadoArquivo:

    resultado = ResultadoArquivo(
        arquivo=path
    )

    linhas = _ler_linhas(path)

    linhas_com_conteudo = [
        linha
        for linha in linhas
        if linha.strip()
    ]

    if not linhas_com_conteudo:
        resultado.erro_estrutural = (
            "Arquivo LOGCONF vazio."
        )
        return resultado

    separador = _detectar_separador(
        linhas_com_conteudo,
        campos_esperados=6
    )

    if separador is None:
        resultado.erro_estrutural = (
            "Não foi possível identificar o separador "
            "ou o arquivo não possui o layout de 6 campos."
        )
        return resultado

    resultado.separador = separador

    if separador != ",":
        exibicao = "TAB" if separador == "\t" else separador

        resultado.avisos.append(
            f"Separador '{exibicao}' detectado. "
            "Arquivo normalizado internamente."
        )

    for numero_linha, linha in enumerate(linhas, start=1):

        linha_original = linha

        if not linha.strip():
            continue

        resultado.registros_lidos += 1

        partes = [
            p.strip()
            for p in linha.split(separador)
        ]

        if len(partes) != 6:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo=(
                        f"Quantidade de campos inválida. "
                        f"Esperado=6, recebido={len(partes)}."
                    )
                )
            )

            resultado.registros_invalidos += 1
            continue

        (
            num_nf,
            user_ini,
            user_fim,
            hora_ini,
            hora_fim,
            status,
        ) = partes

        if not _validar_numero_inteiro(num_nf):

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo="NumNF inválido ou vazio."
                )
            )

            resultado.registros_invalidos += 1
            continue

        if not status:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo="StatusConf vazio."
                )
            )

            resultado.registros_invalidos += 1
            continue

        registro = LogConfRegistro(
            linha=numero_linha,
            num_nf=num_nf,
            user_ini=user_ini,
            user_fim=user_fim,
            hora_ini=hora_ini,
            hora_fim=hora_fim,
            status=status,
        )

        resultado.registros.append(registro)
        resultado.registros_validos += 1

    return resultado


# ============================================================
# PRODCONF
# ============================================================

def parse_prodconf(path: str) -> ResultadoArquivo:

    resultado = ResultadoArquivo(
        arquivo=path
    )

    linhas = _ler_linhas(path)

    linhas_com_conteudo = [
        linha
        for linha in linhas
        if linha.strip()
    ]

    if not linhas_com_conteudo:
        resultado.erro_estrutural = (
            "Arquivo PRODCONF vazio."
        )
        return resultado

    separador = _detectar_separador(
        linhas_com_conteudo,
        campos_esperados=6
    )

    if separador is None:

        resultado.erro_estrutural = (
            "Não foi possível identificar o separador "
            "ou o arquivo não possui o layout de 6 campos."
        )

        return resultado

    resultado.separador = separador

    if separador != ",":
        exibicao = "TAB" if separador == "\t" else separador

        resultado.avisos.append(
            f"Separador '{exibicao}' detectado. "
            "Arquivo normalizado internamente."
        )

    for numero_linha, linha in enumerate(linhas, start=1):

        linha_original = linha

        if not linha.strip():
            continue

        resultado.registros_lidos += 1

        partes = [
            p.strip()
            for p in linha.split(separador)
        ]

        if len(partes) != 6:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo=(
                        f"Quantidade de campos inválida. "
                        f"Esperado=6, recebido={len(partes)}."
                    )
                )
            )

            resultado.registros_invalidos += 1
            continue

        (
            num_doc,
            qtde_lido_raw,
            saldo_raw,
            ean,
            cod_prod,
            status,
        ) = partes

        if not _validar_numero_inteiro(num_doc):

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo="NumDoc inválido ou vazio."
                )
            )

            resultado.registros_invalidos += 1
            continue

        # Pelo combinado:
        # pode existir EAN,
        # pode existir CODPROD,
        # podem existir os dois,
        # mas nunca os dois vazios.

        if not ean and not cod_prod:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo=(
                        "EAN/GTIN e CodProd estão "
                        "ambos vazios."
                    )
                )
            )

            resultado.registros_invalidos += 1
            continue

        try:
            qtde_lido = _decimal(qtde_lido_raw)
            saldo = _decimal(saldo_raw)

        except ValueError as e:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo=str(e)
                )
            )

            resultado.registros_invalidos += 1
            continue

        if not status:

            resultado.erros.append(
                ErroRegistro(
                    arquivo=path,
                    linha=numero_linha,
                    conteudo=linha_original,
                    motivo="Status vazio."
                )
            )

            resultado.registros_invalidos += 1
            continue

        registro = ProdConfRegistro(
            linha=numero_linha,
            num_doc=num_doc,
            qtde_lido=qtde_lido,
            saldo=saldo,
            ean=ean,
            cod_prod=cod_prod,
            status=status,
        )

        resultado.registros.append(registro)
        resultado.registros_validos += 1

    return resultado