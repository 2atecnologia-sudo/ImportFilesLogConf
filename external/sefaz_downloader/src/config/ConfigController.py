"""
===========================================================
2A XML Downloader

ConfigController.py

Versão 0.4
===========================================================
"""

from src.config.ConfigManager import ConfigManager


class ConfigController:

    def __init__(self):

        self.config = ConfigManager()

    # --------------------------------------------

    def carregar(self):

        return self.config

    # --------------------------------------------

    def salvar(self):

        self.config.save()

    # --------------------------------------------

    def get(self, section, key, default=""):

        return self.config.get(section, key, default)

    # --------------------------------------------

    def set(self, section, key, value):

        self.config.set(section, key, value)