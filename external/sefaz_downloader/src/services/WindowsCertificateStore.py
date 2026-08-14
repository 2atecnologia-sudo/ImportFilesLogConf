"""
===========================================================
WindowsCertificateStore.py

Leitura dos certificados instalados no Windows
utilizando .NET (pythonnet)

Compatível com:

- Certificado A1
- Certificado A3 (SafeNet)
- ICP-Brasil
===========================================================
"""
import clr
from System import DateTime
try:
    clr.AddReference("System.Security.Cryptography.X509Certificates")
except Exception:
    clr.AddReference("System")

from System.Security.Cryptography.X509Certificates import (
    X509Store,
    StoreName,
    StoreLocation,
    OpenFlags,
)
from System import DateTime


class WindowsCertificateStore:

    def __init__(self):
        pass

    # ----------------------------------------------------------

    def listarCertificados(self):

        certificados = []

        store = X509Store(
            StoreName.My,
            StoreLocation.CurrentUser
        )

        store.Open(OpenFlags.ReadOnly)

        try:

            for cert in store.Certificates:

                assunto = cert.Subject

                # Ignora certificados internos do Windows
                if "ICP-Brasil" not in assunto:
                    continue

                nome = ""
                cnpj = ""

                try:

                    partes = assunto.split(",")

                    primeira = partes[0]

                    if ":" in primeira:

                        nome, cnpj = primeira.replace("CN=", "").split(":", 1)

                    else:

                        nome = primeira.replace("CN=", "")

                except Exception:

                    nome = assunto

                certificados.append({

                    "nome": nome.strip(),

                    "cnpj": cnpj.strip(),

                    "assunto": assunto,

                    "emissor": cert.Issuer,

                    "validade": str(cert.NotAfter),

                    "thumbprint": cert.Thumbprint,

                    "certificado": cert

                })

        finally:

            store.Close()

        return certificados

    def certificadoExpirado(self, certificado):
        return certificado.NotAfter < DateTime.Now

    def localizarPorThumbprint(self, thumbprint):

        if not thumbprint:
            return None

        certificados = self.listarCertificados()

        for item in certificados:
            print("Comparando:", item["thumbprint"])
            if item["thumbprint"].upper() == thumbprint.upper():

                return item

        return None