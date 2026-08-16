from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, Any


def _to_decimal(s: str) -> Decimal:
    s = (s or "").strip()
    if s == "":
        return Decimal("0")
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


def _is_decimal_text(s: str) -> bool:
    s = (s or "").strip()
    if s == "":
        return False
    s = s.replace(",", ".")
    try:
        Decimal(s)
        return True
    except InvalidOperation:
        return False


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
    Layout esperado por linha (Localizacao é o último campo):
      NumDoc, NomeDest, CidDest, EstDest, GTIN, DescProd, Qtde, Localizacao

    - Localizacao: alfanumérico, pode vir vazio.
    - DescProd pode conter delimitador.
    - Se group_items=True: soma SOMENTE se for mesmo produto (GTIN/CodProd)
      E mesma Localizacao DENTRO DA MESMA NF (NumDoc).
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
                continue

            num_doc = (parts[0] or "").strip()
            if not num_doc:
                continue

            nome_cli = parts[1] if len(parts) > 1 else ""
            cidade = parts[2] if len(parts) > 2 else ""
            uf = parts[3] if len(parts) > 3 else ""

            gtin_raw = parts[4] if len(parts) > 4 else ""
            gtin = _to_int(gtin_raw)

            # Regra preferida: se tiver pelo menos 8 colunas e penúltima for numérica,
            # Qtde = penúltimo, Localizacao = último
            qty_idx = None
            localizacao = ""

            if len(parts) >= 8 and _is_decimal_text(parts[-2]):
                qty_idx = len(parts) - 2
                localizacao = (parts[-1] if len(parts) >= 1 else "").strip()
            else:
                # fallback: Qtde = último campo numérico válido
                for i in range(len(parts) - 1, -1, -1):
                    if _is_decimal_text(parts[i]):
                        qty_idx = i
                        break

                if qty_idx is None or qty_idx < 6:
                    continue

                if (qty_idx + 1) < len(parts):
                    localizacao = delimiter.join(parts[qty_idx + 1 :]).strip()

            desc_tokens = parts[5:qty_idx]
            desc_prod = delimiter.join(desc_tokens).strip()

            qtde_doc = _to_decimal(parts[qty_idx])

            cod_prod = _extract_codprod_from_desc(desc_prod, fallback=str(gtin) if gtin else "0")

            item = {
                "CodProd": cod_prod,
                "GTIN": gtin,
                "DescProd": desc_prod,
                "QtdeDoc": qtde_doc,
                "Localizacao": localizacao,
            }

            if num_doc not in docs:
                docs[num_doc] = {
                    "NomeCli": nome_cli,
                    "Cidade": cidade,
                    "UF": uf,
                    "Itens": [],
                }

            doc = docs[num_doc]

            if not doc.get("NomeCli") and nome_cli:
                doc["NomeCli"] = nome_cli
            if not doc.get("Cidade") and cidade:
                doc["Cidade"] = cidade
            if not doc.get("UF") and uf:
                doc["UF"] = uf

            if not group_items:
                doc["Itens"].append(item)
            else:
                # Agrupa por produto + Localizacao (NumDoc já separa as NFs)
                loc_key = (localizacao or "").strip()
                prod_key = ("GTIN", gtin) if gtin > 0 else ("COD", cod_prod)
                key = (prod_key, loc_key)

                agrup = doc.setdefault("_agrup", {})
                if key not in agrup:
                    agrup[key] = item
                else:
                    agrup[key]["QtdeDoc"] = agrup[key]["QtdeDoc"] + qtde_doc

    if group_items:
        for doc in docs.values():
            agrup = doc.pop("_agrup", {})
            doc["Itens"] = list(agrup.values())

    return docs