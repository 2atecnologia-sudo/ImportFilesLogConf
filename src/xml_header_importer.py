from __future__ import annotations

import logging
import os
import shutil
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from .db import get_connection, insert_logconf_header, numdoc_exists
from .parser_xml import parse_nfe_xml


def entrada_xml_dir(settings) -> str:
    """Pasta exclusiva de chegada dos XMLs antes de serem liberados ao coletor."""
    return os.path.join(
        os.path.dirname(os.path.normpath(settings.watch.input_dir)),
        "entrada_xml",
    )


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


def processar_xml_entrada(file_path: str, settings) -> None:
    """
    Fluxo XML isolado:

    entrada_xml -> valida NF-e -> cria SOMENTE dbo.logConf ->
    gera copia operacional consolidada em entrada

    O prodConf nao e criado aqui. O XML recebido em entrada_xml e usado apenas
    como origem para gerar a copia operacional e e removido apos o COMMIT.
    """
    if not os.path.isfile(file_path):
        return

    if os.path.splitext(file_path)[1].lower() != ".xml":
        return

    if not _wait_file_stable(file_path):
        raise RuntimeError("XML não estabilizou (cópia incompleta?).")

    doc = parse_nfe_xml(file_path, group_items=False)
    numdoc = str(doc["NumDoc"]).strip()
    nomecli = str(doc["NomeCli"]).strip()

    nome_arquivo = os.path.basename(file_path)
    destino_coletor = os.path.join(settings.watch.input_dir, nome_arquivo)

    if os.path.exists(destino_coletor):
        raise FileExistsError(
            "Já existe um XML com o mesmo nome em C:\\MIS\\entrada; "
            "o novo arquivo permanecerá em entrada_xml."
        )

    os.makedirs(settings.watch.input_dir, exist_ok=True)

    # A copia operacional e montada em arquivo temporario. So depois de pronta ela e
    # liberada para os coletores. O XML de entrada fica preservado ate o COMMIT.
    tmp_operacional = destino_coletor + ".tmp"
    if os.path.exists(tmp_operacional):
        os.remove(tmp_operacional)

    # Durante a transacao, o original e apenas renomeado para uma extensao que a
    # varredura nao processa. Em caso de erro, ele volta ao nome .xml original.
    tmp_original = file_path + ".processing"
    if os.path.exists(tmp_original):
        os.remove(tmp_original)

    conn = get_connection(settings.sql)
    original_em_processamento = False
    operacional_liberado = False

    try:
        if numdoc_exists(conn, numdoc):
            destino_dup = _safe_move(
                file_path,
                os.path.join(settings.watch.duplicate_dir, "xml"),
            )
            conn.rollback()
            logging.warning(
                f"[XML CABECALHO DUPLICADO] NumNF={numdoc} | "
                f"Arquivo={nome_arquivo} | Destino={destino_dup}"
            )
            return

        grupos, removidos = _consolidar_xml_para_coletor(file_path, tmp_operacional)

        # Esta função NÃO faz commit. Assim o cabeçalho e a liberação da copia
        # operacional ficam tratados como uma unica operacao controlada aqui.
        insert_logconf_header(
            conn,
            numdoc,
            nomecli,
            status_conf="AGUARDANDO",
            coletor_id=None,
        )

        # Retira temporariamente o .xml de entrada_xml para impedir nova leitura
        # enquanto a transacao esta sendo concluida.
        os.replace(file_path, tmp_original)
        original_em_processamento = True

        # Libera a copia consolidada para os coletores com o MESMO nome.
        os.replace(tmp_operacional, destino_coletor)
        operacional_liberado = True

        conn.commit()

        # Somente depois do COMMIT confirmado o XML de entrada e consumido.
        if os.path.exists(tmp_original):
            os.remove(tmp_original)
        original_em_processamento = False

        logging.info(
            f"[XML LIBERADO AO COLETOR] NumNF={numdoc} | Cliente={nomecli} | "
            f"Arquivo={nome_arquivo} | Cabecalho=dbo.logConf | Destino={destino_coletor} | "
            f"GruposDuplicados={grupos} | LinhasConsolidadas={removidos}"
        )

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

        # Se a copia operacional foi liberada e o COMMIT falhou, remove-a para nao
        # existir XML de coletor sem o respectivo cabecalho confirmado no banco.
        if operacional_liberado and os.path.exists(destino_coletor):
            try:
                os.remove(destino_coletor)
            except Exception:
                logging.exception(
                    f"[XML][ERRO AO REMOVER COPIA OPERACIONAL] Arquivo={destino_coletor}"
                )

        # Devolve o XML ao nome original em entrada_xml para permitir nova tentativa.
        if original_em_processamento and os.path.exists(tmp_original):
            try:
                if not os.path.exists(file_path):
                    os.replace(tmp_original, file_path)
            except Exception:
                logging.exception(
                    f"[XML][ERRO AO DEVOLVER XML PARA ENTRADA_XML] Arquivo={tmp_original}"
                )

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


def processados_xml_dir(settings) -> str:
    """Pasta final dos XMLs cuja conferência já foi iniciada."""
    return os.path.join(settings.watch.processed_dir, "xml")


def arquivar_xmls_em_andamento(settings) -> None:
    """
    Retira de C:\\MIS\\entrada somente XMLs cuja NF já foi assumida.

    Regra oficial do fluxo XML:
    - AGUARDANDO: XML permanece em entrada e pode ser importado por todos os coletores.
    - EM ANDAMENTO: a NF já foi assumida; o XML é arquivado em processados\\xml.
    - CONFERIDO: também é arquivado como proteção caso a verificação periódica não tenha
      observado o intervalo em que o status esteve EM ANDAMENTO.

    A verificação é feita pelo NumNF existente dentro do próprio XML, portanto não interfere
    em TXT, NFLOG, LOGCONF ou PRODCONF.
    """
    pasta_entrada = settings.watch.input_dir
    pasta_processados = processados_xml_dir(settings)

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

                # A NF só é considerada assumida quando existe um coletor identificado.
                # CONFERIDO entra apenas como salvaguarda para não perder um EM ANDAMENTO
                # muito rápido entre duas verificações do Importer.
                if not coletor_id or status not in {"EM ANDAMENTO", "CONFERIDO"}:
                    continue

                destino = _safe_move(caminho, pasta_processados)
                logging.info(
                    f"[XML ARQUIVADO] NumNF={numdoc} | StatusConf={status} | "
                    f"ColetorID={coletor_id} | Origem={caminho} | Destino={destino}"
                )

            except Exception as e:
                # Um XML problemático não impede os demais de serem avaliados.
                logging.warning(
                    f"[XML][ARQUIVAMENTO PENDENTE] Arquivo={os.path.basename(caminho)} | Motivo={e}"
                )

    finally:
        try:
            conn.close()
        except Exception:
            pass

def processar_pasta_xml(settings) -> None:
    """Varre somente entrada_xml; não chama nem altera o processamento TXT."""
    pasta = entrada_xml_dir(settings)
    os.makedirs(pasta, exist_ok=True)

    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if not os.path.isfile(caminho):
            continue
        if os.path.splitext(nome)[1].lower() != ".xml":
            continue

        try:
            processar_xml_entrada(caminho, settings)
        except Exception as e:
            # Mantém o XML em entrada_xml para nova tentativa automática.
            logging.warning(
                f"[XML PENDENTE] Arquivo={nome} | Motivo={e}"
            )
