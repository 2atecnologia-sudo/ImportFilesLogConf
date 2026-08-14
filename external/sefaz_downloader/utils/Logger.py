from datetime import datetime
import os


class Logger:

    def __init__(self):

        self.callback = None

        pasta = "logs"

        os.makedirs(
            pasta,
            exist_ok=True
        )

        self.arquivo = os.path.join(
            pasta,
            datetime.now().strftime("%Y%m%d") + ".log"
        )

    # -------------------------------------------------

    def conectar(self, callback):

        self.callback = callback

    # -------------------------------------------------

    def _gravar(self, simbolo, mensagem):

        horario = datetime.now().strftime("%H:%M:%S")

        texto = f"{horario}  {simbolo}  {mensagem}"

        # Console
        print(texto)

        # Arquivo
        with open(
            self.arquivo,
            "a",
            encoding="utf-8"
        ) as arq:

            arq.write(texto + "\n")

        # Tela
        if self.callback:

            self.callback(texto)

    # -------------------------------------------------

    def info(self, mensagem):

        self._gravar(
            "ℹ",
            mensagem
        )

    # -------------------------------------------------

    def success(self, mensagem):

        self._gravar(
            "✓",
            mensagem
        )

    # -------------------------------------------------

    def warning(self, mensagem):

        self._gravar(
            "⚠",
            mensagem
        )

    # -------------------------------------------------

    def error(self, mensagem):

        self._gravar(
            "✗",
            mensagem
        )