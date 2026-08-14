print("1 - Iniciando")

import clr

print("2 - CLR carregado")

clr.AddReference("System")

print("3 - System carregado")

from System.Security.Cryptography.X509Certificates import (
    X509Store,
    StoreName,
    StoreLocation
)

print("4 - Namespace importado")

store = X509Store(StoreName.My, StoreLocation.CurrentUser)

print("5 - Store criado")

from System.Security.Cryptography.X509Certificates import OpenFlags

store.Open(OpenFlags.ReadOnly)

print("6 - Store aberto")

print("Quantidade:", store.Certificates.Count)

for cert in store.Certificates:

    print("--------------------------------")
    print(cert.Subject)

store.Close()

print("7 - Finalizado")