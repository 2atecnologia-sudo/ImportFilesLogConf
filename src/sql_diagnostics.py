from __future__ import annotations

import pyodbc


def diagnosticar_erro_sql(exc: Exception) -> dict:
    """
    Retorna uma classificação amigável do erro SQL/ODBC
    com orientação curta para o usuário.
    """
    texto = str(exc)
    texto_lower = texto.lower()

    codigo = ""
    if isinstance(exc, pyodbc.Error) and getattr(exc, "args", None):
        try:
            codigo = str(exc.args[0])
        except Exception:
            codigo = ""

    # DRIVER
    if (
        "data source name not found" in texto_lower
        or "driver" in texto_lower and "not found" in texto_lower
        or "im002" in texto_lower
    ):
        return {
            "tipo": "DRIVER_ODBC",
            "titulo": "Driver ODBC não encontrado",
            "mensagem": texto,
            "orientacao": (
                "Verifique se o Microsoft ODBC Driver 17 ou 18 para SQL Server "
                "está instalado e se o driver configurado na aplicação existe."
            ),
            "codigo": codigo,
        }

    # AUTENTICAÇÃO
    if (
        "login failed" in texto_lower
        or "18456" in texto_lower
        or "authentication" in texto_lower
        or "usuário ou senha" in texto_lower
        or "usuario ou senha" in texto_lower
    ):
        return {
            "tipo": "AUTENTICACAO",
            "titulo": "Falha de autenticação no SQL Server",
            "mensagem": texto,
            "orientacao": (
                "Verifique usuário, senha, modo de autenticação do SQL Server "
                "e se o login está habilitado."
            ),
            "codigo": codigo,
        }

    # BANCO
    if (
        "cannot open database" in texto_lower
        or "4060" in texto_lower
        or "database" in texto_lower and "not found" in texto_lower
    ):
        return {
            "tipo": "BANCO",
            "titulo": "Banco de dados não encontrado ou indisponível",
            "mensagem": texto,
            "orientacao": (
                "Verifique o nome do banco na configuração, se o banco está online "
                "e se o usuário possui acesso a ele."
            ),
            "codigo": codigo,
        }

    # PERMISSÃO
    if (
        "permission" in texto_lower
        or "229" in texto_lower
        or "denied" in texto_lower
        or "permissão" in texto_lower
        or "permissao" in texto_lower
    ):
        return {
            "tipo": "PERMISSAO",
            "titulo": "Permissão insuficiente no SQL Server",
            "mensagem": texto,
            "orientacao": (
                "A conexão pode estar funcionando, mas o usuário não possui "
                "permissão suficiente nas tabelas dbo.logConf e dbo.prodConf."
            ),
            "codigo": codigo,
        }

    # REDE / TIMEOUT
    if (
        "08001" in texto_lower
        or "timeout" in texto_lower
        or "tempo limite" in texto_lower
        or "server was not found" in texto_lower
        or "servidor não foi encontrado" in texto_lower
        or "servidor nao foi encontrado" in texto_lower
        or "network-related" in texto_lower
        or "tcp provider" in texto_lower
        or "provedor tcp" in texto_lower
    ):
        return {
            "tipo": "REDE",
            "titulo": "SQL Server não está acessível",
            "mensagem": texto,
            "orientacao": (
                "Verifique se o servidor está ligado, IP/nome do servidor, porta, "
                "VPN, firewall e se o SQL Server aceita conexões remotas."
            ),
            "codigo": codigo,
        }

    return {
        "tipo": "SQL_DESCONHECIDO",
        "titulo": "Erro SQL não classificado",
        "mensagem": texto,
        "orientacao": (
            "Consulte os detalhes técnicos do erro no histórico/log e verifique "
            "a configuração do SQL Server."
        ),
        "codigo": codigo,
    }