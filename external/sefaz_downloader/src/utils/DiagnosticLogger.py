from datetime import datetime


class DiagnosticLogger:
    """
    Logger central da aplicação.
    """

    def __init__(self):
        self.callback = None

    def conectar(self, callback):
        """
        Conecta uma função que receberá as mensagens.
        """
        self.callback = callback

    def _agora(self):
        return datetime.now().strftime("%H:%M:%S")

    def escrever(self, mensagem):
        texto = f"{self._agora()}  {mensagem}"

        # Console
        print(texto)

        # Interface
        if self.callback:
            self.callback(texto)

    def info(self, mensagem):
        self.escrever(f"ℹ️ {mensagem}")

    def sucesso(self, mensagem):
        self.escrever(f"✓ {mensagem}")

    def aviso(self, mensagem):
        self.escrever(f"⚠️ {mensagem}")

    def erro(self, mensagem):
        self.escrever(f"✗ {mensagem}")