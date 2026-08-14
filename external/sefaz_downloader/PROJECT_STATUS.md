# 2A XML Downloader

## Informações do Projeto

- Empresa: 2A Tecnologia
- Linguagem: Python 3.13
- Interface: PySide6
- Banco: SQLite
- Controle de versão: Git
- Repositório:
  https://github.com/2atecnologia-sudo/2AXMLSyncService

---

# Objetivo

Desenvolver um serviço Windows para download automático de XML da SEFAZ utilizando certificado digital A1/A3.

O sistema deverá:

- Validar licença
- Validar certificado
- Consultar Distribuição DF-e
- Baixar XML automaticamente
- Armazenar XML na pasta configurada
- Executar como Serviço Windows
- Possuir atualização automática

---

# Estrutura Atual

main.py

src/

- gui/
    - MainWindow.py
    - Style.py

- database/
    - Database.py

- utils/
    - Logger.py

---

# Funcionalidades Concluídas

- [x] Estrutura inicial do projeto
- [x] Git instalado
- [x] GitHub configurado
- [x] Primeiro commit realizado
- [x] MainWindow funcionando
- [x] Database funcionando
- [x] Logger funcionando
- [x] Style funcionando

---

# Funcionalidades Pendentes

## Configuração

- [ ] ConfigManager.py
- [ ] config.ini
- [ ] Salvar configurações
- [ ] Carregar configurações

## Licenciamento

- [ ] LicenceManager.py
- [ ] Leitura licence.lic
- [ ] Decrypt
- [ ] Validação da licença

## Certificados

- [ ] Certificado A1
- [ ] Certificado A3
- [ ] Testar Configuração

## SEFAZ

- [ ] Controle NSU
- [ ] Download XML
- [ ] Consulta automática

## Serviço

- [ ] Worker
- [ ] Serviço Windows
- [ ] Inicialização automática

## Atualização

- [ ] Auto Update

---

# Próxima Tarefa

Implementar ConfigManager.py

Objetivos:

- criar pasta config
- criar config.ini automaticamente
- salvar configurações
- carregar configurações ao iniciar

---

# Convenções

Sempre que um arquivo for alterado:

git add .

git commit -m "Descrição"

git push

---

# Histórico

## Versão 0.1

- Estrutura inicial

## Versão 0.2

- MainWindow reconstruído
- Interface funcionando

## Próxima versão

0.3 - ConfigManager