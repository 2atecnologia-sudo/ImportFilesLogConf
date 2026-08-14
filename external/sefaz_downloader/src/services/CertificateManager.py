"""
===========================================================
CertificateManager.py

Gerencia certificados digitais A1 e A3
===========================================================
"""

import os
from src.services.WindowsCertificateStore import WindowsCertificateStore

class CertificateManager:

    def __init__(self):

        self.tipo = None
        self.certificado = None
        self.senha = None
        self.windowsStore = WindowsCertificateStore()
    # -----------------------------------------------------

    def configurarA1(self, arquivo, senha):

        self.tipo = "A1"
        self.certificado = arquivo
        self.senha = senha

    # -----------------------------------------------------

    def configurarA3(self):

        self.tipo = "A3"

    # -----------------------------------------------------

    def configurarCloud(self):

        self.tipo = "CLOUD"

    # -----------------------------------------------------

    def validar(self):

        if self.tipo == "A1":

            if not self.certificado:
                return False, "Arquivo do certificado não informado."

            if not os.path.exists(self.certificado):
                return False, "Arquivo do certificado não encontrado."

            if not self.senha:
                return False, "Senha do certificado não informada."

        return True, "OK"

    # -----------------------------------------------------

    def getTipo(self):

        return self.tipo

    def listarCertificadosWindows(self):

        return self.windowsStore.listarCertificados()