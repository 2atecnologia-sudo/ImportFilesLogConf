from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, List, Tuple, Any


def _to_decimal(s: str) -> Decimal:
    s = (s or "").strip()
    if s == "":
        return Decimal("0")
    # aceita "1,5" ou "1.5"
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _to_int(s: str) -> int:
    s = (s or "").strip()
    if not s.isdigit():
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _extract_codprod_from_desc(desc: str, fallback: str) -> str:
    """
    Tenta extrair o código do produto do começo da descrição.
    Ex: '001001 - M ACAI ...' => '001001'
    Se não conseguir, usa fallback.
    """
    desc = (desc or "").strip()
    if " - " in desc:
        cand = desc.split(" - ", 1)[0].strip()
        if cand:
            return cand
    return fallback


def parse_txt_documents(
    path: str,
    delimiter: str = ",",
    encoding: str = "utf-8",
    has_header: bool = True,
    group_items: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Lê seu TXT e retorna um dicionário por NumDoc.

    Layout esperado por linha (flexível):
      NumDoc, NomeDest, CidDest, EstDest, GTIN, DescProd, Qtde, [Local...]

    - Se desc tiver delimitador (vírgula), o parser tenta reconstruir:
      considera Qtde como o ÚLTIMO campo numérico da linha.
    - Se group_items=True: agrupa por GTIN (>0) senão por CodProd (extraído da desc)
      e soma a QtdeDoc.

    Retorno:
      {
        "100": {
          "NomeCli": "DOM PALITO",
          "Cidade": "ILHEUS",
          "UF": "BA",
          "Itens": [ {CodProd, GTIN, DescProd, QtdeDoc}, ... ]
        },
        "200": {...}
      }
    """
    docs: Dict[str, Dict[str, Any]] = {}

    with open(path, "r", encoding=encoding, errors="replace") as f:
        for line_idx, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue

            if has_header and line_idx == 0:
                continue

            parts = [p.strip() for p in line.split(delimiter)]
            if len(parts) < 7:
                # linha curta demais para o layout
                continue

            num_doc = parts[0]
            nome_cli = parts[1] if len(parts) > 1 else ""
            cidade = parts[2] if len(parts) > 2 else ""
            uf = parts[3] if len(parts) > 3 else ""

            gtin_raw = parts[4] if len(parts) > 4 else ""
            gtin = _to_int(gtin_raw)

            # acha índice da quantidade: último campo que vira Decimal de forma válida
            qty_idx = None
            for i in range(len(parts) - 1, -1, -1):
                q = _to_decimal(parts[i])
                # considera "válido" se o texto não for vazio e o parse não resultar em erro
                # (mesmo que seja 0, pois pode existir qtde 0)
                if parts[i].strip() != "":
                    # se ele conseguiu converter (sempre converte), aceitamos como candidato
                    # mas para evitar pegar 'rua1' => 0, precisamos checar se parece número:
                    txt = parts[i].strip().replace(",", ".")
                    try:
                        Decimal(txt)
                        qty_idx = i
                        break
                    except InvalidOperation:
                        pass

            if qty_idx is None or qty_idx < 6:
                continue

            # DescProd pode ter delimitadores no meio: reconstrói do campo 5 até qty_idx-1
            desc_tokens = parts[5:qty_idx]
            desc_prod = delimiter.join(desc_tokens).strip()

            qtde_doc = _to_decimal(parts[qty_idx])

            # CodProd: tenta extrair do começo da descrição; fallback = GTIN (texto)
            cod_prod = _extract_codprod_from_desc(desc_prod, fallback=str(gtin) if gtin else "0")

            item = {
                "CodProd": cod_prod,
                "GTIN": gtin,
                "DescProd": desc_prod,
                "QtdeDoc": qtde_doc,
            }

            if num_doc not in docs:
                docs[num_doc] = {
                    "NomeCli": nome_cli,
                    "Cidade": cidade,
                    "UF": uf,
                    "Itens": [],
                }

            doc = docs[num_doc]

            # se em algum arquivo vier nome/cidade/uf vazio numa linha, mantém o primeiro preenchido
            if not doc.get("NomeCli") and nome_cli:
                doc["NomeCli"] = nome_cli
            if not doc.get("Cidade") and cidade:
                doc["Cidade"] = cidade
            if not doc.get("UF") and uf:
                doc["UF"] = uf

            if not group_items:
                doc["Itens"].append(item)
            else:
                # agrupa por GTIN se existir, senão por CodProd
                key = ("GTIN", gtin) if gtin > 0 else ("COD", cod_prod)
                agrup = doc.setdefault("_agrup", {})
                if key not in agrup:
                    agrup[key] = item
                else:
                    agrup[key]["QtdeDoc"] = agrup[key]["QtdeDoc"] + qtde_doc

    # se agrupou, converte _agrup em Itens
    if group_items:
        for doc in docs.values():
            agrup = doc.pop("_agrup", {})
            doc["Itens"] = list(agrup.values())

    return docs