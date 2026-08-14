"""
===========================================================
2A XML Downloader

Arquivo..........: CertificateService.py
Versão...........: 0.4.1
Empresa..........: 2A Tecnologia

Responsável por validar o certificado digital.
===========================================================
"""

import os


class CertificateService:

    def __init__(self):
        pass

    # ---------------------------------------------------------

    def validar(self, caminho_certificado, senha):

        resultado = {
            "sucesso": True,
            "mensagens": []
        }

        # -----------------------------
        # Caminho do certificado
        # -----------------------------

        if not caminho_certificado:

            resultado["sucesso"] = False
            resultado["mensagens"].append(
                "Certificado não informado."
            )

        elif not os.path.isfile(caminho_certificado):

            resultado["sucesso"] = False
            resultado["mensagens"].append(
                "Arquivo do certificado não encontrado."
            )

        # -----------------------------
        # Extensão
        # -----------------------------

        elif not caminho_certificado.lower().endswith(".pfx"):

            resultado["sucesso"] = False
            resultado["mensagens"].append(
                "O certificado deve possuir extensão .pfx"
            )

        # -----------------------------
        # Senha
        # -----------------------------

        if not senha:

            resultado["sucesso"] = False
            resultado["mensagens"].append(
                "Senha do certificado não informada."
            )

        # -----------------------------

        if resultado["sucesso"]:

            resultado["mensagens"].append(
                "Certificado válido."
            )

        return resultado