from src.services.WindowsCertificateStore import WindowsCertificateStore

store = WindowsCertificateStore()

lista = store.listarCertificados()

print(lista)