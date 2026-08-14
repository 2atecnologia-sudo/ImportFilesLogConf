import xml.etree.ElementTree as ET
import re
class SefazSoapBuilder:

    def __init__(self):

        self.versao = "1.01"

    # -------------------------------------------------

    def montarConsultaNSU(self, cnpj, ultimoNSU):

        xml = f"""<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="{self.versao}">
    <tpAmb>1</tpAmb>
    <cUFAutor>35</cUFAutor>
    <CNPJ>{cnpj}</CNPJ>
    <distNSU>
        <ultNSU>{ultimoNSU}</ultNSU>
    </distNSU>
</distDFeInt>"""

        return xml

    # -------------------------------------------------

    def montarEnvelopeSOAP(self, xmlNFe):

        soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">

    <soap12:Header>

        <nfeCabecMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">

            <cUF>35</cUF>

            <versaoDados>{self.versao}</versaoDados>

        </nfeCabecMsg>

    </soap12:Header>

    <soap12:Body>

        <nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">

            <nfeDadosMsg>

                {xmlNFe}

            </nfeDadosMsg>

        </nfeDistDFeInteresse>

    </soap12:Body>

</soap12:Envelope>
"""

        return soap

    def montarConsultaChave(self, cnpj, chave):

        return f"""<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
        <tpAmb>1</tpAmb>
        <cUFAutor>35</cUFAutor>
        <CNPJ>{cnpj}</CNPJ>
        <consChNFe>
            <chNFe>{chave}</chNFe>
        </consChNFe>
    </distDFeInt>
    """

        # -------------------------------------------------

    def lerRespostaDistribuicao(self, xml):

        resultado = {
            "cStat": "",
            "xMotivo": "",
            "ultNSU": "",
            "maxNSU": "",
            "documentos": []
        }

        try:

            root = ET.fromstring(xml)

            ns = {
                "soap": "http://www.w3.org/2003/05/soap-envelope",
                "nfe": "http://www.portalfiscal.inf.br/nfe"
            }

            retorno = root.find(".//nfe:retDistDFeInt", ns)

            if retorno is None:
                return resultado

            resultado["cStat"] = retorno.findtext(
                "nfe:cStat",
                default="",
                namespaces=ns
            )

            resultado["xMotivo"] = retorno.findtext(
                "nfe:xMotivo",
                default="",
                namespaces=ns
            )

            resultado["ultNSU"] = retorno.findtext(
                "nfe:ultNSU",
                default="",
                namespaces=ns
            )

            resultado["maxNSU"] = retorno.findtext(
                "nfe:maxNSU",
                default="",
                namespaces=ns
            )

            documentos = retorno.findall(
                "nfe:loteDistDFeInt/nfe:docZip",
                ns
            )

            for documento in documentos:

                resultado["documentos"].append(
                    {
                        "nsu": documento.attrib.get("NSU", ""),
                        "schema": documento.attrib.get("schema", ""),
                        "conteudo": documento.text or ""
                    }
                )

            return resultado

        except Exception as e:

            print("Erro lendo XML:", e)

            return resultado