"""
===========================================================
2A XML Downloader

Arquivo..........: ConfigController.py
Versão...........: 0.4
Empresa..........: 2A Tecnologia
===========================================================
"""

from src.config.ConfigManager import ConfigManager


class ConfigController:

    def __init__(self):

        self.manager = ConfigManager()

    # --------------------------------------------------

    def get(self, section, key, default=""):

        return self.manager.get(section, key, default)

    # --------------------------------------------------

    def set(self, section, key, value):

        self.manager.set(section, key, value)

    # --------------------------------------------------

    def save(self):

        self.manager.save()

    # --------------------------------------------------

    def create(self):

        self.manager.create()

    # --------------------------------------------------

    def carregar(self):

        return self.manager

    # --------------------------------------------------

    def salvar(self):

        self.manager.save()