import os
import configparser


class ConfigManager:

    def __init__(self):

        self.folder = "config"
        self.filename = os.path.join(self.folder, "config.ini")

        print("CONFIG:", os.path.abspath(self.filename))

        self.config = configparser.ConfigParser()

        self.create()

    # --------------------------------------------------

    def create(self):

        os.makedirs(self.folder, exist_ok=True)

        # --------------------------------------------------
        # Pasta padrão dos XMLs
        # --------------------------------------------------

        pasta_xml = "C:/MIS"

        os.makedirs(
            pasta_xml,
            exist_ok=True
        )

        # --------------------------------------------------
        # Cria o config.ini na primeira execução
        # --------------------------------------------------

        if not os.path.exists(self.filename):

            self.config["GERAL"] = {
                "empresa": "",
                "cnpj": ""
            }

            self.config["CERTIFICADO"] = {
                "tipo": "A1",
                "arquivo": "",
                "senha": "",
                "thumbprint": "",
                "nome": "",
                "configurado": "nao"
            }

            self.config["XML"] = {
                "pasta": pasta_xml,
                "intervalo": "60"
            }

            self.config["SEFAZ"] = {
                "ultimonsu": "000000000000000"
            }

            self.save()

        # --------------------------------------------------
        # Carrega o arquivo
        # --------------------------------------------------

        self.config.read(
            self.filename,
            encoding="utf-8"
        )

        # --------------------------------------------------
        # Atualiza automaticamente configurações antigas
        # --------------------------------------------------

        alterou = False

        if "XML" not in self.config:

            self.config["XML"] = {}
            alterou = True

        if not self.config["XML"].get("pasta"):

            self.config["XML"]["pasta"] = pasta_xml
            alterou = True

        if "intervalo" not in self.config["XML"]:

            self.config["XML"]["intervalo"] = "60"
            alterou = True

        if alterou:

            print("Atualizando configuração para nova versão...")

            self.save()

    # --------------------------------------------------

    def save(self):

        with open(
            self.filename,
            "w",
            encoding="utf-8"
        ) as arquivo:

            self.config.write(arquivo)

    # --------------------------------------------------

    def get(self, section, key, default=""):

        try:
            return self.config[section][key]
        except Exception:
            return default

    # --------------------------------------------------

    def set(self, section, key, value):

        if section not in self.config:
            self.config[section] = {}

        self.config[section][key] = str(value)

        self.save()