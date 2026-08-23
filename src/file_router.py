from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


_FILE_PATTERN = re.compile(
    r"^(nflog|logconf|confprod|prodconf)-(.+)\.txt$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InputFileInfo:
    tipo: str
    coletor_id: str
    nome_arquivo: str
    caminho: str


def identificar_arquivo(file_path: str) -> Optional[InputFileInfo]:
    """
    Reconhece:

        nflog-<id>.txt
        logconf-<id>.txt
        confprod-<id>.txt

    Maiúsculas/minúsculas não fazem diferença.
    """

    nome = os.path.basename(file_path)

    match = _FILE_PATTERN.match(nome)

    if not match:
        return None

    tipo = match.group(1).lower()
    coletor_id = match.group(2)

    if tipo == "prodconf":
        tipo = "confprod"

    if not coletor_id.strip():
        return None

    return InputFileInfo(
        tipo=tipo,
        coletor_id=coletor_id,
        nome_arquivo=nome,
        caminho=file_path,
    )


def localizar_par_sync(
    input_dir: str,
    coletor_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Procura na pasta de entrada o par:

        logconf-<id>.txt
        confprod-<id>.txt

    A comparação é case-insensitive.
    """

    logconf = None
    confprod = None

    coletor_normalizado = coletor_id.lower()

    if not os.path.isdir(input_dir):
        return None, None

    for nome in os.listdir(input_dir):

        caminho = os.path.join(input_dir, nome)

        if not os.path.isfile(caminho):
            continue

        info = identificar_arquivo(caminho)

        if info is None:
            continue

        if info.coletor_id.lower() != coletor_normalizado:
            continue

        if info.tipo == "logconf":
            logconf = caminho

        elif info.tipo == "confprod":
            confprod = caminho

    return logconf, confprod