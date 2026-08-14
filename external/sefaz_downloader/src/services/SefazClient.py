from src.config.ConfigManager import ConfigManager
from src.services.SefazConnection import SefazConnection
from src.services.SefazSoapBuilder import SefazSoapBuilder
from src.services.WindowsCertificateStore import WindowsCertificateStore

# =====================================================
# Resultados possíveis da comunicação
# =====================================================

STATUS_OK = "OK"

STATUS_CERTIFICADO_NAO_ENCONTRADO = "CERTIFICADO_NAO_ENCONTRADO"

STATUS_CERTIFICADO_VENCIDO = "CERTIFICADO_VENCIDO"

STATUS_CERTIFICADO_INVALIDO = "CERTIFICADO_INVALIDO"

STATUS_SEFAZ_INDISPONIVEL = "SEFAZ_INDISPONIVEL"

STATUS_ERRO_COMUNICACAO = "ERRO_COMUNICACAO"

STATUS_SEM_XML = "SEM_XML"

STATUS_XML_ENCONTRADOS = "XML_ENCONTRADOS"


class SefazClient:

    def __init__(self, log=None):

        self.log = log

        self.certificado = None
        self.conectado = False

        self.uf = "35"
        self.ambiente = "1"

        self.versao = "1.01"

        self.url = ""

        self.config = ConfigManager()

        self.tipoCertificado = ""
        self.arquivoCertificado = ""
        self.thumbprint = ""

    # -------------------------------------------------

    def registrarLog(self, mensagem):

        print(mensagem)

        if callable(self.log):
            self.log(mensagem)

    def configurarCertificado(self, certificado):

        self.certificado = certificado

    # -------------------------------------------------

    def configurarAmbiente(self, ambiente):

        self.ambiente = ambiente

        if ambiente == "1":
            print("Ambiente: Produção")
        else:
            print("Ambiente: Homologação")

    # -------------------------------------------------

    def carregarConfiguracao(self):

        self.tipoCertificado = self.config.get(
            "CERTIFICADO",
            "tipo",
            ""
        )

        self.arquivoCertificado = self.config.get(
            "CERTIFICADO",
            "arquivo",
            ""
        )

        self.thumbprint = self.config.get(
            "CERTIFICADO",
            "thumbprint",
            ""
        )

        print("Tipo:", self.tipoCertificado)
        print("Arquivo:", self.arquivoCertificado)
        print("Thumbprint:", self.thumbprint)


    #---------------------------------------

    def validarCertificado(self):

        self.carregarConfiguracao()

        store = WindowsCertificateStore()

        certificado = store.localizarPorThumbprint(
            self.thumbprint
        )

        if certificado is None:

            return {
                "sucesso": False,
                "codigo": STATUS_CERTIFICADO_NAO_ENCONTRADO,
                "mensagem": "O certificado configurado não foi encontrado."
            }

        if store.certificadoExpirado(
            certificado["certificado"]
        ):

            return {
                "sucesso": False,
                "codigo": STATUS_CERTIFICADO_VENCIDO,
                "mensagem": "O certificado digital está vencido."
            }

        return {
            "sucesso": True,
            "codigo": STATUS_OK,
            "mensagem": "Certificado válido."
        }
    # -------------------------------------------------

    def conectar(self):

        self.registrarLog("Lendo configurações...")
        
        self.carregarConfiguracao()    

        self.registrarLog("Conectando à SEFAZ...")

        store = WindowsCertificateStore() 

        self.registrarLog("Verificando certificado...")

        certificado = store.localizarPorThumbprint(
            self.thumbprint
        )
        
        if certificado is not None:
            self.registrarLog("Certificado localizado.")

        if certificado is None:

            return {
                "sucesso": False,
                "codigo": STATUS_CERTIFICADO_NAO_ENCONTRADO,
                "mensagem": "O certificado configurado não foi encontrado."
            }

        if store.certificadoExpirado(
            certificado["certificado"]
        ):

            return {
                "sucesso": False,
                "codigo": STATUS_CERTIFICADO_VENCIDO,
                "mensagem": "O certificado digital está vencido."
            }

        print(
            "✓ Certificado localizado:",
            certificado["nome"]
        )

        builder = SefazSoapBuilder()

        ultimoNSU = self.config.get(
            "SEFAZ",
            "ultimonsu",
            "000000000000000"
        )

        print("Último NSU:", ultimoNSU)

        xml = builder.montarConsultaNSU(
            self.config.get(
                "GERAL",
                "cnpj"
            ),
            ultimoNSU
        )

        soap = builder.montarEnvelopeSOAP(xml)

        conexao = SefazConnection()

        response = conexao.enviar(
            "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
            soap
        )

        if response:

            dados = builder.lerRespostaDistribuicao(
                response.text
            )

            print("=" * 40)
            print("DADOS EXTRAÍDOS")
            print("=" * 40)
            print(dados)

            print("=" * 40)
            print("DOCUMENTOS ENCONTRADOS:", len(dados["documentos"]))

            for documento in dados["documentos"]:

                print("-----------------------------")
                print("NSU:", documento["nsu"])
                print("Schema:", documento["schema"])

            self.conectado = True

            return {
                "sucesso": True,
                "codigo": STATUS_OK,
                "mensagem": "Comunicação realizada com sucesso."
            }

        return {
            "sucesso": False,
            "codigo": STATUS_ERRO_COMUNICACAO,
            "mensagem": "Não foi possível comunicar com a SEFAZ."
        }

    # -------------------------------------------------

    def desconectar(self):

        self.conectado = False

        print("Desconectado.")

    # -------------------------------------------------

    def consultarUltimoNSU(self):

        if not self.conectado:

            raise Exception("Cliente não conectado.")

        print("Consultando último NSU...")

        return "000000000000000"

    # -------------------------------------------------

    def baixarDocumentos(self, ultimoNSU):

        if not self.conectado:

            raise Exception("Cliente não conectado.")

        print(f"Baixando documentos a partir do NSU {ultimoNSU}")

        return []