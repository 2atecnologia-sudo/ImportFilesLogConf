from __future__ import annotations

import logging
import os
import shutil
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from .db import get_connection, insert_logconf_header, insert_prodconf_items, numdoc_exists
from .parser_xml import parse_nfe_xml


# XMLs já publicados e inalterados nesta execução.
# A varredura pode reencontrá-los, mas não deve reprocessar nem gerar novos logs.
_xml_publicados = {}


def _assinatura_xml(path: str):
    try:
        stat = os.stat(path)
        return (stat.st_size, stat.st_mtime_ns)
    except (FileNotFoundError, OSError):
        return None


def _tipo_operacao_log(tipo_operacao: str) -> str:
    return "RECEBIMENTO" if tipo_operacao == "REC" else "EXPEDIÇÃO"



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
    Processa o XML antes de publicá-lo ao coletor.

    Regra importante: enquanto o XML estiver sendo validado/consolidado, ele fica
    com sufixo .processing e, portanto, não aparece ao Kalipso como arquivo .xml.
    Somente após o processamento terminar com sucesso o XML consolidado volta a ser
    publicado com sua extensão .xml original.
    """
    if not os.path.isfile(file_path) or os.path.splitext(file_path)[1].lower() != ".xml":
        return

    chave_xml = os.path.normcase(os.path.abspath(file_path))
    assinatura_atual = _assinatura_xml(file_path)
    if assinatura_atual is not None and _xml_publicados.get(chave_xml) == assinatura_atual:
        return

    if not _wait_file_stable(file_path):
        raise RuntimeError("XML não estabilizou (cópia incompleta?).")

    nome_arquivo = os.path.basename(file_path)
    tmp_operacional = file_path + ".tmp"
    tmp_original = file_path + ".processing"

    # Enquanto estiver em processamento, o arquivo não pode ficar visível ao
    # coletor como .xml. A publicação só ocorre no final, após sucesso completo.
    if os.path.exists(tmp_operacional):
        os.remove(tmp_operacional)
    if os.path.exists(tmp_original):
        raise RuntimeError(
            f"Já existe processamento pendente para {nome_arquivo}: "
            f"{os.path.basename(tmp_original)}"
        )

    os.replace(file_path, tmp_original)
    processo_log = _tipo_operacao_log(tipo_operacao)
    logging.info(
        f"[XML {processo_log}] Arquivo={nome_arquivo} | Arquivo recebido | Processando"
    )

    conn = None
    publicado = False
    try:
        doc = parse_nfe_xml(tmp_original, group_items=False)
        numdoc = str(doc["NumDoc"]).strip()
        nomecli = _nome_cabecalho_xml(tmp_original, tipo_operacao)

        conn = get_connection(settings.sql)

        if numdoc_exists(conn, numdoc):
            conn.rollback()

            # A NF já existe no SQL, portanto NÃO inserimos logConf/prodConf novamente.
            # Mesmo assim, o XML disponível ao coletor precisa continuar obedecendo
            # à regra operacional atual: itens repetidos pelo mesmo cProd devem ser
            # consolidados antes de o Kalipso importá-lo.
            grupos, removidos = _consolidar_xml_para_coletor(
                tmp_original,
                tmp_operacional,
            )

            # Só aqui o XML volta a ficar visível ao coletor.
            os.replace(tmp_operacional, file_path)
            publicado = True

            if os.path.exists(tmp_original):
                os.remove(tmp_original)

            assinatura_publicada = _assinatura_xml(file_path)
            if assinatura_publicada is not None:
                _xml_publicados[chave_xml] = assinatura_publicada

            logging.info(
                f"[XML {processo_log}] NF={numdoc} | Arquivo={nome_arquivo} | "
                f"Disponível para os coletores | "
                f"GruposDuplicados={grupos} | LinhasConsolidadas={removidos}"
            )
            return

        grupos, removidos = _consolidar_xml_para_coletor(tmp_original, tmp_operacional)

        if tipo_operacao == "REC":
            # Recebimento: o prodConf deve refletir exatamente o XML operacional.
            # Se houver cProd duplicado, a consolidação acima soma qCom e remove
            # somente as repetições. Se não houver duplicidade, os itens seguem
            # normalmente sem alteração funcional.
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

        # Primeiro confirma o SQL. Somente depois o XML consolidado é publicado
        # novamente com extensão .xml para os coletores.
        conn.commit()
        os.replace(tmp_operacional, file_path)
        publicado = True

        if os.path.exists(tmp_original):
            os.remove(tmp_original)

        assinatura_publicada = _assinatura_xml(file_path)
        if assinatura_publicada is not None:
            _xml_publicados[chave_xml] = assinatura_publicada

        logging.info(
            f"[XML {processo_log}] NF={numdoc} | Arquivo={nome_arquivo} | "
            f"Disponível para os coletores | "
            f"GruposDuplicados={grupos} | LinhasConsolidadas={removidos}"
        )
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        # Segurança: em caso de falha, não republicamos o XML original. Ele
        # permanece como .processing e, portanto, não fica disponível ao coletor.
        if publicado and os.path.exists(file_path):
            logging.exception(
                f"[XML][ERRO APÓS PUBLICAÇÃO] Arquivo={file_path}"
            )
        else:
            logging.exception(
                f"[XML][PROCESSAMENTO PENDENTE] Arquivo={tmp_original} | "
                f"XML não liberado aos coletores."
            )
        raise
    finally:
        if os.path.exists(tmp_operacional):
            try:
                os.remove(tmp_operacional)
            except Exception:
                pass
        if conn is not None:
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
                processo_log = _tipo_operacao_log(tipo_operacao)
                logging.info(
                    f"[CONFERÊNCIA] NF={numdoc} | Processo={processo_log} | "
                    f"Importada pelo coletor {coletor_id} | XML arquivado"
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

