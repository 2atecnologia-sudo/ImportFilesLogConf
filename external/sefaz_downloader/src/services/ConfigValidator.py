"""
===========================================================
2A XML Downloader

Arquivo..........: ConfigValidator.py
Versão...........: 0.4.1
Empresa..........: 2A Tecnologia

Responsável por validar toda a configuração do sistema.
===========================================================
"""

from src.services.CertificateService import CertificateService
from src.services.XmlFolderService import XmlFolderService


class ConfigValidator:

    def __init__(self):

        self.certificateService = CertificateService()
        self.xmlFolderService = XmlFolderService()

    # ---------------------------------------------------------

    def validar(
        self,
        empresa,
        cnpj,
        certificado,
        senha,
        pasta_xml,
        intervalo
    ):

        resultado = {
            "sucesso": True,
            "mensagens": []
        }

        # -----------------------------------------
        # Empresa
        # -----------------------------------------

        if not empresa.strip():

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "Empresa não informada."
            )

        # -----------------------------------------
        # CNPJ
        # -----------------------------------------

        if not cnpj.strip():

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "CNPJ não informado."
            )

        else:

            numeros = "".join(filter(str.isdigit, cnpj))

            if len(numeros) != 14:

                resultado["sucesso"] = False

                resultado["mensagens"].append(
                    "CNPJ deve possuir 14 dígitos."
                )

        # -----------------------------------------
        # Certificado
        # -----------------------------------------

        cert = self.certificateService.validar(
            certificado,
            senha
        )

        if not cert["sucesso"]:

            resultado["sucesso"] = False

        resultado["mensagens"].extend(
            cert["mensagens"]
        )

        # -----------------------------------------
        # Pasta XML
        # -----------------------------------------

        pasta = self.xmlFolderService.validar(
            pasta_xml
        )

        if not pasta["sucesso"]:

            resultado["sucesso"] = False

        resultado["mensagens"].extend(
            pasta["mensagens"]
        )

        # -----------------------------------------
        # Intervalo
        # -----------------------------------------

        try:

            intervalo = int(intervalo)

            if intervalo < 10:

                resultado["sucesso"] = False

                resultado["mensagens"].append(
                    "O intervalo mínimo é de 10 segundos."
                )

        except Exception:

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "Intervalo inválido."
            )

        # -----------------------------------------

        if resultado["sucesso"]:

            resultado["mensagens"].append(
                "Configuração validada com sucesso."
            )

        return resultado