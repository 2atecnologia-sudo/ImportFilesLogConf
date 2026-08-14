"""
===========================================================
2A XML Downloader

Arquivo...........: Application.py
Versão............: 0.4
Empresa...........: 2A Tecnologia
===========================================================
"""

import os
import sys

from PySide6.QtWidgets import QApplication

from src.config.ConfigManager import ConfigManager
from src.controllers.ConfigController import ConfigController
from src.controllers.SyncController import SyncController
from src.database.Database import Database
from src.gui.Style import load_style
from src.utils.Logger import Logger


APP_NAME = "2A XML Downloader"
APP_VERSION = "0.4.0"


class Application:

    def __init__(self):

        self.logger = Logger()

        self.logger.info("========================================")
        self.logger.info(APP_NAME)
        self.logger.info(APP_VERSION)
        self.logger.info("Inicializando...")

        self.create_directories()

        self.database = Database()
        self.database.initialize()

        self.logger.info("Banco inicializado.")

        self.config = ConfigManager()

        self.logger.info("Configuração carregada.")

        self.configController = ConfigController()

        self.logger.info("ConfigController inicializado.")
        self.syncController = SyncController()
        self.logger.info("SyncController inicializado.")

        self.logger.info("Application pronta.")

    # ----------------------------------------------------

    def create_directories(self):

        folders = [

            "assets",

            "config",

            "database",

            "logs",

            "temp",

            "xml"

        ]

        for folder in folders:

            os.makedirs(folder, exist_ok=True)

    # ----------------------------------------------------

    def create_qt_application(self):

        app = QApplication(sys.argv)

        app.setApplicationName(APP_NAME)

        app.setApplicationVersion(APP_VERSION)

        app.setStyleSheet(load_style())

        return app

    # ----------------------------------------------------

    def create_main_window(self):

        from src.gui.MainWindow import MainWindow

        window = MainWindow()

        return window

    # ----------------------------------------------------

    def run(self):

        self.logger.info("Abrindo interface...")

        app = self.create_qt_application()

        window = self.create_main_window()

        window.show()

        self.logger.info("Sistema iniciado.")

        sys.exit(app.exec())