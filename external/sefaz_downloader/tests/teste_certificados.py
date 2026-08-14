import win32crypt

store = win32crypt.CertOpenSystemStore(None, "MY")

cert = win32crypt.CertEnumCertificatesInStore(store, None)

contador = 0

while cert:

    contador += 1

    print("--------------------------------")

    print(cert)

    cert = win32crypt.CertEnumCertificatesInStore(store, cert)

print()

print("TOTAL:", contador)