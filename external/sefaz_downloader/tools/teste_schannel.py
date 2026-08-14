from requests_schannel.adapters import create_session

thumbprint = "777B55787D6ACEBA71560CEDF68E7C4DB4E33C43"
try:

    session = create_session(
        client_cert_thumbprint=thumbprint
    )

    print("===================================")
    print("SESSÃO HTTPS CRIADA COM SUCESSO")
    print("===================================")

    try:
        response = session.get(
            "https://www.google.com",
            timeout=10
        )

        print("Status:", response.status_code)

    except Exception as e:
        print("Erro na conexão:")
        print(type(e).__name__)
        print(e)

except Exception as e:
    print("Erro na criação da sessão:")
    print(type(e).__name__)
    print(e)

