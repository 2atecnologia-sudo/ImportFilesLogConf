from requests_schannel.adapters import create_session
from src.config.ConfigManager import ConfigManager
from src.utils.Logger import Logger
from datetime import datetime
import xml.etree.ElementTree as ET
import base64
import gzip
import re
import os


class SefazConnection:

    def __init__(self):

        self.certificado = None
        self.timeout = 30
        self.session = None
        self.config = ConfigManager()
        self.logger = Logger()

    # -------------------------------------------------

    def configurarCertificado(self, certificado):

        self.certificado = certificado

    # -------------------------------------------------

    def criarSessaoHTTPS(self):

        self.logger.info(
        "Criando sessão HTTPS..."
)
        thumbprint = self.config.get(
            "CERTIFICADO",
            "thumbprint",
            ""
        )

        print("Thumbprint:", thumbprint)

        self.session = create_session(
            client_cert_thumbprint=thumbprint
        )

        self.logger.success(
        "Sessão HTTPS criada com sucesso."
        )

    # -------------------------------------------------

    def enviar(self, url, soap):

        if self.session is None:

            self.criarSessaoHTTPS()

        print("=" * 60)
        print("ENVIANDO SOAP PARA A SEFAZ")
        print("=" * 60)

        print("URL:")
        print(url)
        print("SOAP:")
        print(soap)
        print()

        headers = {
            "Content-Type": 'application/soap+xml; charset=utf-8; action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"',
            "SOAPAction": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"
        }

        try:

            response = self.session.post(
                url,
                data=soap.encode("utf-8"),
                headers=headers,
                timeout=self.timeout
            )

            print("=" * 60)
            print("RESPOSTA DA SEFAZ")
            print("=" * 60)

            print("HTTP:", response.status_code)
            print()
            print(response.text)

            # ------------------------------------------
            # Extrai o primeiro docZip da resposta
            # ------------------------------------------

            match = re.search(
                r"<docZip[^>]*>(.*?)</docZip>",
                response.text,
                re.DOTALL
            )

            if match:

                print()
                print("=" * 60)
                print("DOCZIP LOCALIZADO")
                print("=" * 60)

                conteudo = match.group(1)

                xml = gzip.decompress(
                    base64.b64decode(conteudo)
                ).decode("utf-8")

                print()
                print("=" * 60)
                print("XML DESCOMPACTADO")
                print("=" * 60)
                print(xml)

                # ------------------------------------------
# Salva o XML em disco
# ------------------------------------------

                pasta_xml = self.config.get(
                    "GERAL",
                    "pasta_xml",
                    "C:/MIS"
                )

                os.makedirs(
                    pasta_xml,
                    exist_ok=True
                )

                nome_arquivo = (
                    "NFe_"
                    + datetime.now().strftime("%Y%m%d_%H%M%S")
                    + ".xml"
                )

                caminho = os.path.join(
                    pasta_xml,
                    nome_arquivo
                )

                with open(
                    caminho,
                    "w",
                    encoding="utf-8"
                ) as arquivo:

                    arquivo.write(xml)

                print()
                print("=" * 60)
                print("XML SALVO")
                print("=" * 60)
                print(caminho)

            else:

                print()
                print("Nenhum docZip encontrado.")

            # ------------------------------------------
            # Atualiza o último NSU
            # ------------------------------------------

            try:

                root = ET.fromstring(response.text)

                ns = {
                    "soap": "http://www.w3.org/2003/05/soap-envelope",
                    "nfe": "http://www.portalfiscal.inf.br/nfe"
                }

                ultNSU = root.find(".//nfe:ultNSU", ns)

                if ultNSU is not None:

                    self.config.set(
                        "SEFAZ",
                        "ultimonsu",
                        ultNSU.text
                    )

                    print()
                    print("========================================")
                    print("Último NSU atualizado:", ultNSU.text)
                    print("========================================")

            except Exception as e:

                print("Erro ao atualizar o último NSU:", e)

            return response

        except Exception as e:

            print("=" * 60)
            print("ERRO NA COMUNICAÇÃO")
            print("=" * 60)

            print(type(e).__name__)
            print(e)

            return None