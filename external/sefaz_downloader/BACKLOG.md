# BACKLOG - 2A XML Downloader

Este arquivo contém melhorias planejadas para o projeto.

**Regra do projeto**

O objetivo atual é concluir a versão 1.0.

Somente serão implementadas antes da versão 1.0 funcionalidades essenciais para o funcionamento do sistema.

Todo o restante ficará registrado neste backlog.

---

# Versão 1.0 (Objetivo Atual)

- [ ] Conectar na SEFAZ
- [ ] Consultar distribuição de documentos (distDFe)
- [ ] Baixar XMLs
- [ ] Descompactar docZip
- [ ] Salvar XML na pasta configurada
- [ ] Gravar informações no banco de dados
- [ ] Atualizar automaticamente o último NSU
- [ ] Executar automaticamente conforme intervalo configurado
- [ ] Executar em segundo plano (ícone na bandeja)

---

# Melhorias Futuras

## Download

- [ ] Permitir baixar apenas NF-e de Entrada
- [ ] Permitir baixar apenas NF-e de Saída
- [ ] Permitir baixar Entrada e Saída
- [ ] Suporte a eventos (cancelamento, CC-e, manifestação etc.)

---

## Interface

- [ ] Melhorar mensagens de status
- [ ] Melhorar tela de configurações
- [ ] Histórico das últimas sincronizações

---

## Banco de Dados

- [ ] Classificar documentos como Entrada ou Saída
- [ ] Registrar data/hora da sincronização
- [ ] Registrar quantidade de XMLs baixados por execução

---

## Serviço

- [ ] Inicializar automaticamente com o Windows
- [ ] Reiniciar automaticamente em caso de falha
- [ ] Monitorar execução em segundo plano

---

## Código

- [ ] Revisão geral da arquitetura após a versão 1.0
- [ ] Melhorar logs
- [ ] Refatorações para facilitar futuras alterações da SEFAZ

---

## Ideias

(Espaço para novas ideias durante o desenvolvimento.)

---

# Melhorias Identificadas Durante o Desenvolvimento

Estas melhorias foram identificadas durante a implementação da versão 1.0.

A regra continua sendo:

**Somente implementar após a versão 1.0 estar funcional**, salvo se alguma delas for indispensável para o funcionamento do sistema.

---

## Confiabilidade

- [ ] Atualizar o último NSU somente após concluir com sucesso todo o processamento dos documentos.

Fluxo atual:

Consulta SEFAZ

↓

Recebe resposta

↓

Atualiza NSU

Fluxo desejado:

Consulta SEFAZ

↓

Recebe resposta

↓

Descompacta docZip

↓

Salvar XML

↓

Gravar informações no banco

↓

Confirmar processamento concluído

↓

Atualizar último NSU

Objetivo:

Evitar perda de documentos caso ocorra alguma falha durante o processamento.

---

## Certificado Digital

- [ ] Solicitar a senha (PIN) do certificado A3 apenas uma única vez durante a execução do aplicativo.
- [ ] Manter a sessão autenticada enquanto o aplicativo permanecer aberto.
- [ ] Evitar solicitar novamente o PIN a cada sincronização.

---

## Serviço Windows

- [ ] Reutilizar exatamente a mesma rotina utilizada pelo botão "Testar".

O botão será apenas um gatilho para testes.

Na versão final o serviço utilizará exatamente a mesma função, alterando apenas o gatilho para o intervalo configurado.

Evitar duplicação de código.

---

## Manutenção

- [ ] Centralizar URLs da SEFAZ.
- [ ] Centralizar versões dos WebServices.
- [ ] Centralizar Namespaces XML.
- [ ] Centralizar Schemas.

Objetivo:

Facilitar adaptações futuras caso a Receita Federal altere algum serviço.

---

## Desenvolvimento

Durante o desenvolvimento sempre seguir as regras abaixo:

- Dividir implementações grandes em pequenas etapas.
- Validar cada etapa antes de iniciar a próxima.
- Evitar alterar muitos arquivos simultaneamente.
- Sempre informar caminho completo do arquivo que deverá ser alterado.
- Sempre informar o nome exato do arquivo.
- Sempre informar o método ou trecho exato a ser alterado.
- Para arquivos pequenos, preferir substituir o arquivo inteiro.
- Para arquivos grandes, substituir apenas o método completo.

---

## Interface

- [ ] Mostrar data/hora da última sincronização.
- [ ] Mostrar data/hora da próxima sincronização.
- [ ] Mostrar quantidade de XMLs baixados na última execução.
- [ ] Mostrar tempo gasto na sincronização.
- [ ] Melhorar mensagens de erro e status.

---

## Download

- [ ] Permitir configurar a pasta de destino dos XMLs.
- [ ] Validar automaticamente se a pasta configurada existe.
- [ ] Criar automaticamente a pasta caso não exista.

---

## Banco de Dados

- [ ] Registrar tempo de processamento de cada sincronização.
- [ ] Registrar quantidade de documentos recebidos.
- [ ] Registrar quantidade de documentos processados com sucesso.
- [ ] Registrar quantidade de erros ocorridos.

---

## Organização do Projeto

Sempre que surgir uma nova ideia durante o desenvolvimento:

Se for essencial para atingir o objetivo atual:

→ Implementar.

Se não for essencial:

→ Registrar neste BACKLOG e continuar o desenvolvimento principal.

---

## Lembrete

O objetivo continua sendo:

Conectar na SEFAZ.

Consultar documentos.

Baixar XML.

Salvar XML.

Executar automaticamente.

Somente após a versão 1.0 estar totalmente funcional serão iniciadas as melhorias descritas neste documento.

---

## Interface (Prioridade Alta após a versão 1.0 funcional)

Implementar um painel de log em tempo real dentro da aplicação.

Objetivos:

- [ ] Exibir todas as etapas da sincronização na área de log da tela.
- [ ] Mostrar data e hora de cada evento.
- [ ] Informar cada etapa executada (conexão, consulta, download, gravação, banco de dados etc.).
- [ ] Exibir mensagens de erro amigáveis ao usuário.
- [ ] Rolar automaticamente para a última mensagem.
- [ ] Manter também a saída no console durante o desenvolvimento.

Exemplo:

10:45:01 - Iniciando sincronização...

10:45:02 - Certificado localizado.

10:45:03 - Conectando à SEFAZ...

10:45:04 - Sessão HTTPS criada.

10:45:05 - Consulta enviada.

10:45:06 - Documento localizado.

10:45:06 - XML salvo em C:\MIS\3526....xml

10:45:07 - Banco de dados atualizado.

10:45:07 - Último NSU atualizado.

10:45:07 - Sincronização concluída.

Motivação:

Permitir que o usuário acompanhe todo o processamento da sincronização sem depender do terminal do VSCode, facilitando suporte, diagnóstico e operação da aplicação.

## Validações

- [ ] Validar consistência entre o CNPJ informado e o certificado digital selecionado.
      Caso sejam diferentes, exibir uma mensagem de confirmação ao usuário antes de prosseguir.

Exemplo:

"O CNPJ informado nas configurações é diferente do CNPJ do certificado digital selecionado.

CNPJ informado: XX.XXX.XXX/XXXX-XX
CNPJ do certificado: YY.YYY.YYY/YYYY-YY

Deseja continuar mesmo assim?"

Motivação:

Evitar configurações incorretas sem impedir cenários onde o usuário realmente precise utilizar um certificado diferente (casos específicos de procuração eletrônica, certificados de terceiros, etc.).

## BACKLOG-UI-001
Status: Adiado
Prioridade: Baixa
Versão: Pós 1.0

Título:
Padronizar a comunicação da aplicação utilizando exclusivamente o painel de Log.

Descrição:
- Remover gradualmente os QMessageBox utilizados para mensagens operacionais.
- Utilizar o DiagnosticLogger como canal padrão para informações, avisos, erros e sucesso.
- Manter QMessageBox apenas para confirmações do usuário (Excluir, Sair, Sobrescrever, etc.).
- Padronizar o formato das mensagens utilizando:
  - ℹ️ Informação
  - ✓ Sucesso
  - ⚠️ Aviso
  - ❌ Erro
- Exibir todas as ocorrências operacionais no painel de Log com data e hora.
- Centralizar a comunicação da aplicação em um único componente para facilitar manutenção e suporte.

Motivo do adiamento:
Esta melhoria não impacta o funcionamento da aplicação. Será implementada após a conclusão da versão 1.0, quando todas as funcionalidades principais de comunicação com a SEFAZ, download automático de XML e sincronização estiverem concluídas e estabilizadas.

Benefícios esperados:
- Interface mais profissional.
- Comunicação padronizada.
- Eliminação de interrupções desnecessárias durante a operação.
- Histórico completo de eventos no painel de Log.
- Maior facilidade de suporte e diagnóstico.


Revisar o comportamento do botão "Testar conexão SEFAZ" após a implementação completa da comunicação com a SEFAZ. Avaliar se deve permanecer habilitado apenas com certificado válido ou se sua função deve ser exclusivamente testar a comunicação com o WebService.



-------------------------

Backlog

Refatoração: Centralização do gerenciamento de estado dos certificados

Objetivo
Criar um gerenciador único para o estado dos certificados (A1/A3), centralizando a validação, atualização da interface e mensagens de log.

Escopo

Criar um enum StatusCertificado.
Criar um método único setStatusCertificado() responsável por:
Atualizar o status interno.
Atualizar os textos da interface.
Atualizar as cores e ícones.
Registrar mensagens no log.
Separar o conceito de tipo do certificado (A1/A3) do estado do certificado (válido, vencido, aguardando, não encontrado, erro).
Eliminar validações duplicadas espalhadas pela interface.
Preparar a arquitetura para a comunicação com a SEFAZ.

Estados previstos

Nenhum certificado configurado.
Aguardando seleção do arquivo PFX (A1).
Aguardando seleção do certificado do Windows (A3).
Certificado válido.
Certificado vencido.
Certificado não encontrado.
Erro de leitura do certificado.

Benefícios

Código mais organizado e de fácil manutenção.
Interface sempre consistente.
Redução de código duplicado.
Facilidade para futuras implementações (SEFAZ, certificados em nuvem, renovação de certificados, etc.)