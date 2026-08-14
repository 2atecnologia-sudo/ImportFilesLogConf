import requests

try:
    import requests_schannel
    print("✓ requests-schannel carregado com sucesso")
except Exception as e:
    print("Erro ao carregar requests-schannel:")
    print(e)