import clr

clr.AddReference("System")

from System.Security.Cryptography.X509Certificates import (
    X509Store,
    StoreName,
    StoreLocation,
    OpenFlags
)

store = X509Store(StoreName.My, StoreLocation.CurrentUser)
store.Open(OpenFlags.ReadOnly)

try:
    for cert in store.Certificates:

        print("=" * 80)
        print("Subject :", cert.Subject)
        print("Issuer  :", cert.Issuer)
        print("Thumb   :", cert.Thumbprint)
        print("Válido  :", cert.NotAfter)
        print("HasKey  :", cert.HasPrivateKey)

        try:
            rsa = cert.PrivateKey

            print("PrivateKey:", rsa)

            if rsa:

                print("Tipo Python :", type(rsa))
                print("Classe .NET :", rsa.GetType().FullName)

                try:
                    info = rsa.CspKeyContainerInfo

                    print("ProviderName   :", info.ProviderName)
                    print("ProviderType   :", info.ProviderType)
                    print("HardwareDevice :", info.HardwareDevice)
                    print("MachineKeyStore:", info.MachineKeyStore)

                except Exception as e:
                    print("Erro CSP:", e)

        except Exception as e:
            print("Erro PrivateKey:", e)

finally:
    store.Close()