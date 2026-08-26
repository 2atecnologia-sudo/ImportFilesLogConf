from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


_FILE_PATTERN = re.compile(
    r"^(nflog|logconf|confprod|prodconf)-(.+?)\.txt(\.ok)?$",
    re.IGNORECASE,
)

_SCANOCOR_PATTERN = re.compile(
    r"^ScanOcor-(.+?)\.txt$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InputFileInfo:
    tipo: str
    coletor_id: str
    nome_arquivo: str
    caminho: str
    confirmado: bool = False


def identificar_arquivo(file_path: str) -> Optional[InputFileInfo]:
    nome = os.path.basename(file_path)

    scan_match = _SCANOCOR_PATTERN.match(nome)

    if scan_match:
        coletor_id = scan_match.group(1).strip()

        if not coletor_id:
            return None

        return InputFileInfo(
            tipo="scanocor",
            coletor_id=coletor_id,
            nome_arquivo=nome,
            caminho=file_path,
            confirmado=False,
        )

    match = _FILE_PATTERN.match(nome)

    if not match:
        return None

    tipo = match.group(1).lower()
    coletor_id = match.group(2)
    confirmado = bool(match.group(3))

    if tipo == "prodconf":
        tipo = "confprod"

    if confirmado and tipo != "nflog":
        return None

    if not coletor_id.strip():
        return None

    return InputFileInfo(
        tipo=tipo,
        coletor_id=coletor_id,
        nome_arquivo=nome,
        caminho=file_path,
        confirmado=confirmado,
    )


def localizar_par_sync(
    input_dir: str,
    coletor_id: str,
) -> tuple[Optional[str], Optional[str]]:
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

        if info.tipo == "logconf" and not info.confirmado:
            logconf = caminho

        elif info.tipo == "confprod" and not info.confirmado:
            confprod = caminho

    return logconf, confprod