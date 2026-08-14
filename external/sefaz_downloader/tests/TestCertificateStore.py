import py_cert_store

print("=" * 60)
print("LISTANDO CERTIFICADOS")
print("=" * 60)

certificados = py_cert_store.find_windows_cert_all()

print(f"Quantidade: {len(certificados)}")
print()

for i, cert in enumerate(certificados, start=1):

    print("=" * 60)
    print(f"CERTIFICADO {i}")
    print("=" * 60)

    print(cert)

    print()