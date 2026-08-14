"""
===========================================================
2A XML Downloader

Arquivo...........: SyncController.py
Versão............: 0.1
Empresa...........: 2A Tecnologia
===========================================================
"""

from src.utils.Logger import Logger


class SyncController:

    def __init__(self):

        self.logger = Logger()

        self.em_sincronizacao = False

        self.logger.info("SyncController inicializado.")

    # ----------------------------------------------------

    def sincronizar(self):

        if self.em_sincronizacao:

            self.logger.warning(
                "Sincronização já está em andamento."
            )

            return False

        self.em_sincronizacao = True

        try:

            self.logger.info(
                "Iniciando sincronização..."
            )

            # Aqui ficará todo o fluxo da sincronização.

            self.logger.info(
                "Sincronização finalizada."
            )

            return True

        finally:

            self.em_sincronizacao = False