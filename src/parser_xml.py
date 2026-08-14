from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET


NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def _to_decimal(s: str) -> Decimal:
    s = (s or "").strip()
    if s == "":
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _gtin_to_int(s: str) -> int:
    s = (s or "").strip()
    if not s.isdigit():
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def parse_nfe_xml(path: str, group_items: bool = False) -> dict:
    """
    Lê NF-e XML 4.00 e retorna:
      {
        "NumDoc": nNF,
        "NomeCli": dest/xNome,
        "Itens": [ {CodProd, GTIN, DescProd, QtdeDoc, (opcional) NItem}, ... ]
      }

    - NumDoc = nNF (conforme regra definida)
    - Se group_items=True: agrupa por GTIN (>0) senão por CodProd, somando QtdeDoc.
    - Se group_items=False: 1 item por <det>, incluindo NItem.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    nNF = root.findtext(".//nfe:ide/nfe:nNF", namespaces=NS)
    nome_cli = root.findtext(".//nfe:dest/nfe:xNome", namespaces=NS)

    if not nNF:
        raise ValueError("XML sem ide/nNF (NumDoc).")
    if not nome_cli:
        raise ValueError("XML sem dest/xNome (NomeCli).")

    if not group_items:
        itens = []
        for det in root.findall(".//nfe:det", namespaces=NS):
            n_item = det.get("nItem")
            cprod = det.findtext("./nfe:prod/nfe:cProd", namespaces=NS) or ""
            cean = det.findtext("./nfe:prod/nfe:cEAN", namespaces=NS) or ""
            xprod = det.findtext("./nfe:prod/nfe:xProd", namespaces=NS) or ""
            qcom = det.findtext("./nfe:prod/nfe:qCom", namespaces=NS) or "0"

            itens.append({
                "NItem": int(n_item) if (n_item and n_item.isdigit()) else None,
                "CodProd": cprod.strip(),
                "GTIN": _gtin_to_int(cean),
                "DescProd": xprod.strip(),
                "QtdeDoc": _to_decimal(qcom),
            })

        return {"NumDoc": nNF.strip(), "NomeCli": nome_cli.strip(), "Itens": itens}

    # group_items=True
    agrup = {}
    for det in root.findall(".//nfe:det", namespaces=NS):
        cprod = det.findtext("./nfe:prod/nfe:cProd", namespaces=NS) or ""
        cean = det.findtext("./nfe:prod/nfe:cEAN", namespaces=NS) or ""
        xprod = det.findtext("./nfe:prod/nfe:xProd", namespaces=NS) or ""
        qcom = det.findtext("./nfe:prod/nfe:qCom", namespaces=NS) or "0"

        gtin = _gtin_to_int(cean)
        qtd = _to_decimal(qcom)
        key = ("GTIN", gtin) if gtin > 0 else ("COD", cprod.strip())

        if key not in agrup:
            agrup[key] = {
                "NItem": None,
                "CodProd": cprod.strip(),
                "GTIN": gtin,
                "DescProd": xprod.strip(),
                "QtdeDoc": qtd,
            }
        else:
            agrup[key]["QtdeDoc"] = agrup[key]["QtdeDoc"] + qtd

    return {"NumDoc": nNF.strip(), "NomeCli": nome_cli.strip(), "Itens": list(agrup.values())}