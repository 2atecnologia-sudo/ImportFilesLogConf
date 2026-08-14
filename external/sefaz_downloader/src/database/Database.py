"""
===========================================================
2A XML Sync Service

Arquivo........: Database.py
Descrição......: Gerenciamento do banco SQLite

===========================================================
"""

import sqlite3
import os


class Database:

    def __init__(self):

        self.database_path = os.path.join(
            "database",
            "xmlsync.db"
        )

    # ---------------------------------------------------------

    def connect(self):

        return sqlite3.connect(self.database_path)

    # ---------------------------------------------------------

    def initialize(self):

        conn = self.connect()

        cursor = conn.cursor()

        # CONFIGURAÇÕES

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS CONFIG(

                CHAVE TEXT PRIMARY KEY,

                VALOR TEXT

            )

        """)

        # XMLS

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS XML(

                ID INTEGER PRIMARY KEY AUTOINCREMENT,

                NSU TEXT,

                CHAVE TEXT,

                ARQUIVO TEXT,

                DATA TEXT

            )

        """)

        # LOGS

        cursor.execute("""

            CREATE TABLE IF NOT EXISTS LOG(

                ID INTEGER PRIMARY KEY AUTOINCREMENT,

                DATA TEXT,

                DESCRICAO TEXT

            )

        """)

        conn.commit()

        conn.close()

    # ---------------------------------------------------------

    def get_config(self, chave):

        conn = self.connect()

        cursor = conn.cursor()

        cursor.execute(

            "SELECT VALOR FROM CONFIG WHERE CHAVE=?",

            (chave,)

        )

        row = cursor.fetchone()

        conn.close()

        if row:

            return row[0]

        return ""

    # ---------------------------------------------------------

    def set_config(self, chave, valor):

        conn = self.connect()

        cursor = conn.cursor()

        cursor.execute("""

            INSERT OR REPLACE INTO CONFIG
            (CHAVE, VALOR)
            VALUES (?,?)

        """, (chave, valor))

        conn.commit()

        conn.close()

    # ---------------------------------------------------------

    def add_log(self, descricao):

        conn = self.connect()

        cursor = conn.cursor()

        cursor.execute("""

            INSERT INTO LOG

            (DATA, DESCRICAO)

            VALUES

            (datetime('now','localtime'),?)

        """, (descricao,))

        conn.commit()

        conn.close()

    # ---------------------------------------------------------

    def total_xml(self):

        conn = self.connect()

        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM XML")

        total = cursor.fetchone()[0]

        conn.close()

        return total