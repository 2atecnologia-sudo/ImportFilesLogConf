# Resumo do projeto — ImportFilesLogConf

## Objetivo
Importador de arquivos **TXT ou XML** (configurável no `config.ini`) que monitora uma pasta e grava itens no **SQL Server** na tabela `dbo.prodConf`.
Inclui um app de **bandeja (Tray)** para iniciar/parar/reiniciar o importador e abrir Config/Logs/Pasta.

## Pasta do projeto (DEV)
- `C:\Projetos\ImportFilesLogConf`

## Ambiente
- `venv` dentro do projeto: `.\venv\`
- Dependências: `pyodbc`, `watchdog`, `pystray`, `pillow`
- Executar sempre pela raiz do projeto:
  - Importador: `python -m src.main`
  - Config UI: `python -m src.config_ui`
  - Tray: `python -m src.tray`

## Configuração
- `config.ini` (local, **não versionar**)
- `config.ini.example` (modelo)

Parâmetros importantes:
- `[input] format = txt | xml`
- `[sql] driver = ODBC Driver 17 for SQL Server`
- `[watch] input_dir / processed_dir / error_dir / duplicate_dir`
- `[logging] log_dir`
- `[app] status_inicial = PEN, group_items = yes/no`
- `[txt] delimiter=',' encoding='utf-8' has_header=yes`

## SQL Server (Servidor)
- Instância: `WIN-4LDPKMOC3M6\SQLEXPRESS`
- IP público: `181.224.25.30`
- Porta TCP atual (dinâmica): `50579`
- Firewall: liberada TCP 50579 somente para o IP dev `189.78.139.226`
- Banco: `logConf`
- Tabela: `dbo.prodConf`
- Colunas: `NumDoc`, `NomeCli`, `DataImp`, `CodProd`, `GTIN`, `DescProd`, `QtdeDoc`, `QtdeLido`, `Status`, `DataeHora`
- Ajuste no código: INSERT usa `DataImp` (não `DatImp`).

## Código principal
- `src/settings.py`: lê `config.ini`
- `src/db.py`: conexão SQL + `insert_prodconf_items()` + `numdoc_exists()`
- `src/parser_txt.py`: `parse_txt_documents()` (CSV por vírgula; qtde = último campo numérico)
- `src/parser_xml.py`: `parse_nfe_xml()` (NF-e 4.00)
- `src/main.py`: watchdog; escolhe XML/TXT pelo config; grava no SQL; move para processados/erros/duplicados; log em `logs\importador.log`
- `src/tray.py`: bandeja com menu completo (Status/Config/Logs/Pasta/Iniciar/Parar/Reiniciar/Sair)

## Tray — status atual
- Rodar: `python -m src.tray`
- Abre ícone na bandeja e faz **auto-start** do importador (fica verde)
- Menu:
  - Status / Configuração / Abrir pasta de entrada / Abrir logs
  - Iniciar (desabilita quando rodando) / Parar (habilita quando rodando) / Reiniciar
  - Sair (para o importador e fecha o tray)
- Obs.: hoje o Tray controla um **processo filho** (não serviço Windows).

## Funcionando hoje
- Importação TXT OK: grava na `dbo.prodConf` e move para `processados`
- Conexão SQL OK via ODBC Driver 17 (`tcp:181.224.25.30,50579`)
- Tray OK com auto-start e menu habilitando/desabilitando Iniciar/Parar

## Pendências / próximos passos
1) Testar fluxo **XML NF-e** real (`format=xml` no config.ini)
2) Robustez: retry de “arquivo não estabilizou”
3) Depois: instalar como **Serviço Windows** e Tray controlar o serviço

## Comandos úteis
- Tray: `.\venv\Scripts\python.exe -m src.tray`
- Importador console: `.\venv\Scripts\python.exe -m src.main`
- Config: `.\venv\Scripts\python.exe -m src.config_ui`
- Drivers ODBC: `python -c "import pyodbc; print(pyodbc.drivers())"`