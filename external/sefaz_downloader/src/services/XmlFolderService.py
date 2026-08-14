"""
===========================================================
2A XML Downloader

Arquivo..........: XmlFolderService.py
Versão...........: 0.4.1
Empresa..........: 2A Tecnologia

Responsável por validar a pasta onde os XMLs serão gravados.
===========================================================
"""

import os


class XmlFolderService:

    def __init__(self):
        pass

    # ---------------------------------------------------------

    def validar(self, pasta):

        resultado = {
            "sucesso": True,
            "mensagens": []
        }

        # ---------------------------------------
        # Pasta informada
        # ---------------------------------------

        if not pasta:

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "Pasta XML não informada."
            )

            return resultado

        # ---------------------------------------
        # Pasta existe
        # ---------------------------------------

        if not os.path.exists(pasta):

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "A pasta informada não existe."
            )

            return resultado

        # ---------------------------------------
        # É realmente uma pasta?
        # ---------------------------------------

        if not os.path.isdir(pasta):

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "O caminho informado não é uma pasta."
            )

            return resultado

        # ---------------------------------------
        # Permissão de gravação
        # ---------------------------------------

        if not os.access(pasta, os.W_OK):

            resultado["sucesso"] = False

            resultado["mensagens"].append(
                "Sem permissão para gravar na pasta."
            )

            return resultado

        # ---------------------------------------

        resultado["mensagens"].append(
            "Pasta XML válida."
        )

        return resultado