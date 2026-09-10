from __future__ import annotations

import logging
import os
import shutil
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from .db import get_connection, insert_logconf_header, insert_prodconf_items, numdoc_exists
from .parser_xml import parse_nfe_xml


def entrada_xml_rec_dir(settings) -> str:
    """Pasta de XMLs de recebimento; cabeçalho usa o emitente."""
    return os.path.join(os.path.dirname(os.path.normpath(settings.watch.input_dir)), "entrada_xmlRec")


def entrada_xml_exp_dir(settings) -> str:
    """Pasta de XMLs de expedição; cabeçalho usa o destinatário."""
    return os.path.join(os.path.dirname(os.path.normpath(settings.watch.input_dir)), "entrada_xmlExp")


def _wait_file_stable(path: str, checks: int = 3, interval_sec: float = 1.0) -> bool:
    """Espera a cópia do XML terminar sem depender do fluxo TXT."""
    last = -1
    stable = 0

    for _ in range(180):
        if not os.path.exists(path):
            return False

        size = os.path.getsize(path)
        if size == last and size > 0:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
            last = size

        time.sleep(interval_sec)

    return False


def _safe_move(src: str, dst_dir: str) -> str:
    os.makedirs(dst_dir, exist_ok=True)

    base = os.path.basename(src)
    dst = os.path.join(dst_dir, base)

    if os.path.exists(dst):
        name, ext = os.path.splitext(base)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(dst_dir, f"{name}_{ts}{ext}")

    shutil.move(src, dst)
    return dst




def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _filho_por_nome(parent, nome: str):
    for child in list(parent):
        if _local_name(child.tag) == nome:
            return child
    return None


def _nome_cabecalho_xml(file_path: str, tipo_operacao: str) -> str:
    """REC usa emit/xNome; EXP usa dest/xNome."""
    root = ET.parse(file_path).getroot()
    inf_nfe = next((e for e in root.iter() if _local_name(e.tag) == "infNFe"), None)
    if inf_nfe is None:
        raise ValueError("XML sem elemento infNFe.")

    grupo = "emit" if tipo_operacao == "REC" else "dest" if tipo_operacao == "EXP" else None
    if grupo is None:
        raise ValueError(f"Tipo de operação XML inválido: {tipo_operacao}")

    participante = _filho_por_nome(inf_nfe, grupo)
    xnome = _filho_por_nome(participante, "xNome") if participante is not None else None
    nome = (xnome.text or "").strip() if xnome is not None else ""
    if not nome:
        raise ValueError(f"XML sem {grupo}/xNome.")
    return nome


def _consolidar_xml_para_coletor(origem: str, destino: str) -> tuple[int, int]:
    """
    Gera uma COPIA operacional do XML para o coletor.

    O XML fiscal original nunca e alterado. Na copia, itens <det> com o mesmo cProd
    sao consolidados em uma unica linha e qCom e somado. Os demais dados da primeira
    ocorrencia do produto sao preservados, pois o Kalipso usa essa copia apenas para
    carregar os produtos da conferencia.

    Retorna (quantidade_de_grupos_consolidados, quantidade_de_linhas_removidas).
    """
    tree = ET.parse(origem)
    root = tree.getroot()

    inf_nfe = None
    for elem in root.iter():
        if _local_name(elem.tag) == "infNFe":
            inf_nfe = elem
            break

    if inf_nfe is None:
        raise ValueError("XML sem elemento infNFe.")

    dets = [child for child in list(inf_nfe) if _local_name(child.tag) == "det"]
    por_codigo = {}
    grupos = 0
    removidos = 0

    for det in dets:
        prod = _filho_por_nome(det, "prod")
        if prod is None:
            continue

        cprod_el = _filho_por_nome(prod, "cProd")
        qcom_el = _filho_por_nome(prod, "qCom")
        cprod = (cprod_el.text or "").strip() if cprod_el is not None else ""

        # Sem cProd, nao consolidamos para nao correr risco de unir itens distintos.
        if not cprod:
            continue

        if cprod not in por_codigo:
            por_codigo[cprod] = (det, qcom_el)
            continue

        det_base, qcom_base_el = por_codigo[cprod]
        if qcom_base_el is None or qcom_el is None:
            continue

        try:
            qtd_base = Decimal((qcom_base_el.text or "0").replace(",", "."))
            qtd_atual = Decimal((qcom_el.text or "0").replace(",", "."))
        except InvalidOperation:
            # Se alguma quantidade nao for numerica, preserva as duas linhas.
            continue

        # Decimal evita erro de arredondamento de ponto flutuante.
        # A NF-e normalmente traz qCom com quatro casas decimais.
        total = qtd_base + qtd_atual
        qcom_base_el.text = f"{total:.4f}"

        inf_nfe.remove(det)
        removidos += 1
        grupos += 1 if removidos == 1 else 0

    # Recalcula corretamente a quantidade de codigos que realmente tinham duplicidade.
    contagem = {}
    for det in dets:
        prod = _filho_por_nome(det, "prod")
        if prod is None:
            continue
        cprod_el = _filho_por_nome(prod, "cProd")
        cprod = (cprod_el.text or "").strip() if cprod_el is not None else ""
        if cprod:
            contagem[cprod] = contagem.get(cprod, 0) + 1
    grupos = sum(1 for qtd in contagem.values() if qtd > 1)

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tree.write(destino, encoding="utf-8", xml_declaration=True)
    return grupos, removidos


def processar_xml_entrada(file_path: str, settings, tipo_operacao: str) -> None:
    """
    Cria somente o cabeçalho e mantém o XML consolidado na própria pasta REC/EXP
    para que todos os coletores possam importá-lo enquanto a NF estiver livre.
    """
    if not os.path.isfile(file_path) or os.path.splitext(file_path)[1].lower() != ".xml":
        return
    if not _wait_file_stable(file_path):
        raise RuntimeError("XML não estabilizou (cópia incompleta?).")

    doc = parse_nfe_xml(file_path, group_items=False)
    numdoc = str(doc["NumDoc"]).strip()
    nomecli = _nome_cabecalho_xml(file_path, tipo_operacao)
    nome_arquivo = os.path.basename(file_path)

    tmp_operacional = file_path + ".tmp"
    tmp_original = file_path + ".processing"
    for p in (tmp_operacional, tmp_original):
        if os.path.exists(p):
            os.remove(p)

    conn = get_connection(settings.sql)
    original_em_processamento = False
    try:
        if numdoc_exists(conn, numdoc):
            conn.rollback()
            logging.info(
                f"[XML JÁ CADASTRADO] NumNF={numdoc} | Tipo={tipo_operacao} | "
                f"Arquivo={nome_arquivo} | XML permanece disponível aos coletores."
            )
            return

        grupos, removidos = _consolidar_xml_para_coletor(file_path, tmp_operacional)

        if tipo_operacao == "REC":
            # Recebimento: o prodConf deve refletir exatamente o XML operacional.
            # Se houver cProd duplicado, a consolidação acima soma qCom e remove
            # somente as repetições. Se não houver duplicidade, o XML permanece
            # funcionalmente igual e os itens seguem normalmente.
            doc_consolidado = parse_nfe_xml(tmp_operacional, group_items=False)
            insert_prodconf_items(
                conn,
                numdoc,
                nomecli,
                doc_consolidado["Itens"],
                settings.app.status_inicial,
                coletor_id=None,
                commit=False,
            )
        else:
            # Expedição permanece, por enquanto, somente com o cabeçalho.
            insert_logconf_header(
                conn,
                numdoc,
                nomecli,
                status_conf="AGUARDANDO",
                coletor_id=None,
            )

        os.replace(file_path, tmp_original)
        original_em_processamento = True
        os.replace(tmp_operacional, file_path)
        conn.commit()

        if os.path.exists(tmp_original):
            os.remove(tmp_original)
        original_em_processamento = False

        logging.info(
            f"[XML DISPONÍVEL AOS COLETORES] NumNF={numdoc} | Tipo={tipo_operacao} | "
            f"Cliente={nomecli} | Arquivo={nome_arquivo} | Pasta={os.path.dirname(file_path)} | "
            f"GruposDuplicados={grupos} | LinhasConsolidadas={removidos}"
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if original_em_processamento and os.path.exists(tmp_original):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                os.replace(tmp_original, file_path)
            except Exception:
                logging.exception(f"[XML][ERRO AO RESTAURAR XML] Arquivo={tmp_original}")
        if os.path.exists(tmp_operacional):
            try:
                os.remove(tmp_operacional)
            except Exception:
                pass
        raise
    finally:
        if os.path.exists(tmp_operacional):
            try:
                os.remove(tmp_operacional)
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass

def processados_xml_rec_dir(settings) -> str:
    return os.path.join(settings.watch.processed_dir, "xmlRec")


def processados_xml_exp_dir(settings) -> str:
    return os.path.join(settings.watch.processed_dir, "xmlExp")


def _arquivar_xmls_da_pasta(settings, pasta_entrada: str, pasta_processados: str, tipo_operacao: str) -> None:
    if not os.path.isdir(pasta_entrada):
        return

    xmls = [
        os.path.join(pasta_entrada, nome)
        for nome in sorted(os.listdir(pasta_entrada))
        if os.path.isfile(os.path.join(pasta_entrada, nome))
        and os.path.splitext(nome)[1].lower() == ".xml"
    ]
    if not xmls:
        return

    conn = get_connection(settings.sql)
    try:
        cur = conn.cursor()
        for caminho in xmls:
            try:
                doc = parse_nfe_xml(caminho, group_items=False)
                numdoc = str(doc["NumDoc"]).strip()
                cur.execute(
                    """
                    SELECT TOP 1 StatusConf, ColetorID
                    FROM dbo.logConf
                    WHERE NumNF = ?
                    """,
                    (int(numdoc),),
                )
                row = cur.fetchone()
                if row is None:
                    continue
                status = str(getattr(row, "StatusConf", "") or "").strip().upper()
                coletor_id = str(getattr(row, "ColetorID", "") or "").strip()
                if not coletor_id or status not in {"EM ANDAMENTO", "CONFERIDO"}:
                    continue
                destino = _safe_move(caminho, pasta_processados)
                logging.info(
                    f"[XML ARQUIVADO] NumNF={numdoc} | Tipo={tipo_operacao} | "
                    f"StatusConf={status} | ColetorID={coletor_id} | Origem={caminho} | Destino={destino}"
                )
            except Exception as e:
                logging.warning(
                    f"[XML][ARQUIVAMENTO PENDENTE] Tipo={tipo_operacao} | "
                    f"Arquivo={os.path.basename(caminho)} | Motivo={e}"
                )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def arquivar_xmls_em_andamento(settings) -> None:
    """Arquiva REC/EXP somente após a NF ser assumida no logConf."""
    _arquivar_xmls_da_pasta(
        settings, entrada_xml_rec_dir(settings), processados_xml_rec_dir(settings), "REC"
    )
    _arquivar_xmls_da_pasta(
        settings, entrada_xml_exp_dir(settings), processados_xml_exp_dir(settings), "EXP"
    )


def _processar_pasta_xml_tipo(settings, pasta: str, tipo_operacao: str) -> None:
    os.makedirs(pasta, exist_ok=True)
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if not os.path.isfile(caminho) or os.path.splitext(nome)[1].lower() != ".xml":
            continue
        try:
            processar_xml_entrada(caminho, settings, tipo_operacao)
        except Exception as e:
            logging.warning(f"[XML PENDENTE] Tipo={tipo_operacao} | Arquivo={nome} | Motivo={e}")


def processar_pasta_xml(settings) -> None:
    """Varre somente XML REC/EXP; não altera o processamento TXT."""
    _processar_pasta_xml_tipo(settings, entrada_xml_rec_dir(settings), "REC")
    _processar_pasta_xml_tipo(settings, entrada_xml_exp_dir(settings), "EXP")

