# Plano executável de melhorias — `auditoria_zabbix`

## Objetivo

Corrigir os riscos de segurança, concorrência, compatibilidade e confiabilidade encontrados na auditoria do projeto, sem perder funcionalidades existentes.

Este documento é a fonte de verdade para a execução. As tarefas estão em ordem de dependência e foram reduzidas para que um modelo de codificação mais simples consiga executá-las com segurança.

## Perfil recomendado para o executor

- **Forma de execução:** uma tarefa por vez, seguindo a ordem e as dependências deste arquivo.
- **Executor padrão:** `gpt-5.6-terra`, com esforço de raciocínio **high**.
- **Executor das tarefas críticas de segurança, concorrência e arquitetura:** `gpt-5.6-sol`, com esforço **high**.
- **Revisor das tarefas críticas implementadas pelo Terra:** `gpt-5.6-sol`, com esforço **high**.
- **Revisão integrada final:** `gpt-5.6-sol`, com esforço **high**.
- Se custo não for uma restrição, o `gpt-5.6-sol` pode executar todas as tarefas automatizáveis do plano.

Referência de seleção: a documentação atual da OpenAI apresenta `gpt-5.6-sol` como o modelo flagship e `gpt-5.6-terra` como a opção de forte desempenho e menor custo: <https://developers.openai.com/api/docs/guides/latest-model>.

### Alocação obrigatória das tarefas críticas

| Tarefa | Implementação | Revisão | Motivo |
|---|---|---|---|
| HUMAN-01 | Responsável humano | Confirmação humana | Envolve revogação de credenciais e ações externas. |
| SEC-01 | `gpt-5.6-terra` / `high` | `gpt-5.6-sol` / `high` | Mudança delimitada de empacotamento, mas com impacto sobre segredos. |
| SEC-02 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Manipula evidências e dados potencialmente secretos. |
| PRIV-01 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Anonimização incorreta pode expor dados sem falha aparente. |
| GUI-01 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Altera a fronteira de estado entre GUI e workers. |
| GUI-02 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Centraliza concorrência e atualizações da interface. |
| OPS-01 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Corrige corridas entre cancelamento, reinício e operações simultâneas. |
| CLI-01 | `gpt-5.6-terra` / `high` | `gpt-5.6-sol` / `high` | Implementação isolada, mas sensível a diferenças entre sistemas operacionais. |
| ZBX-01 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Afeta sessão, logout, retries e consistência das coletas. |
| ZBX-02 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Compatibilidade incorreta pode produzir auditorias silenciosamente incompletas. |
| AI-01 | `gpt-5.6-sol` / `high` | `gpt-5.6-sol` / `high` | Define o contrato compartilhado entre provedores e modos de resposta. |

As tarefas não listadas na tabela devem ser executadas pelo `gpt-5.6-terra`: usar esforço **high** para mudanças de código e **medium** para documentação ou trabalho mecânico. Uma revisão não substitui testes nem critérios de aceite. Quando implementação e revisão estiverem atribuídas ao Sol, realizar duas passagens separadas: primeiro implementar e testar; depois revisar o diff procurando falhas de segurança, concorrência, compatibilidade, regressões e testes ausentes.

## Execução paralela por subagentes

**Autorização:** o responsável autorizou execução paralela em 2026-08-16. Esta seção substitui a regra de execução estritamente unitária abaixo, mas não altera dependências, critérios de aceite, responsabilidades humanas ou a alocação obrigatória de modelos.

1. Um coordenador mantém a ordem do grafo de dependências e só inicia tarefas cujas dependências automatizáveis estejam concluídas.
2. Tarefas independentes podem ser executadas ao mesmo tempo somente quando seus conjuntos de arquivos editáveis não se sobrepõem. Se houver sobreposição, a tarefa posterior aguarda.
3. Cada subagente usa o modelo e esforço definidos nesta tabela; tarefas críticas implementadas/revisadas pelo Sol continuam exigindo duas passagens separadas.
4. Subagentes não editam este plano, não marcam checkboxes e não escrevem no registro. O coordenador integra o resultado, executa a verificação conjunta, faz a revisão necessária e então atualiza este arquivo.
5. Antes de iniciar uma onda, o coordenador a registra na tabela abaixo. Ao retomar o trabalho, tarefas marcadas como `em andamento` devem ser verificadas pelo coordenador antes de reiniciar ou substituir o agente.
6. Cada subagente executa os testes específicos de sua tarefa. Ao fim de cada onda, o coordenador executa a suíte completa e `git diff --check` uma vez, após os resultados terem sido integrados.

| Onda | Tarefas | Modelo/esforço | Arquivos com propriedade | Estado |
|---|---|---|---|---|
| 1 | SEC-02; GUI-01 | Sol / high; Sol / high | `tools/coleta_zabbix_os.sh`, `tests/test_os_collector.py`, `README.md`; `core/run_config.py`, `gui/main_view.py`, `core/controller.py`, testes do controller | concluída em 2026-08-16 |
| 2 | GUI-02; PKG-02 | Sol / high; Terra / high | `gui/main_view.py`, `core/controller.py`, testes GUI/controller; `exec_wayland.fish`, `Dockerfile`, `README.md` | concluída em 2026-08-16 |
| 3 | OPS-01 | Sol / high | `core/operation.py`, `core/controller.py`, `api/zabbix_api.py`, `gui/main_view.py`, testes do controller/GUI | concluída em 2026-08-16 |
| 4 | ZBX-01; CLI-01 | Sol / high; Terra / high | `api/zabbix_api.py`, `core/controller.py`, `tests/test_zabbix_client.py`; `api/ai_cli_client.py`, `core/operation.py`, testes da CLI | concluída em 2026-08-16 |
| 5 | ZBX-02; PRIV-01 | Sol / high; Sol / high | `api/zabbix_api.py`, `tests/test_zabbix_versions.py`, `README.md`; `core/anonymizer.py`, `core/controller.py`, `gui/main_view.py`, testes novos | concluída em 2026-08-16 |
| 6 | ZBX-03; PRIV-02 | Terra / high; Terra / high | `api/zabbix_api.py`, `core/controller.py`, testes de coleta; `core/controller.py`, `api/ai_api.py`, `api/ai_cli_client.py`, prompt e testes | concluída em 2026-08-17 |
| 7 | ZBX-04; AI-01 | Sol / high; Sol / high | `api/zabbix_api.py`, prompt e testes; `api/ai_api.py`, `api/ai_cli_client.py`, `api/ai_prompts.py`, controller e testes | concluída em 2026-08-17 |
| 8 | PRIV-03; AI-02; AI-04 | Terra / high; Terra / high; Terra / high | `gui/main_view.py`, `core/controller.py`, testes de validação; `api/ai_api.py`, testes de retry; `api/ai_cli_client.py`, testes da CLI, `README.md` | concluída em 2026-08-17 |
| 9 | DATA-01 | Terra / high | `core/paths.py`, helper de persistência, `core/controller.py`, `gui/main_view.py`, `requirements.txt`, testes | concluída em 2026-08-17 |
| 10 | EXP-01 | Terra / high | `core/report_exporter.py`, `gui/main_view.py`, `tests/test_pdf_pipeline.py`, testes de exportação | concluída em 2026-08-17 |
| 11 | AI-03; EXP-02 | Terra / high; Terra / high | `api/ai_api.py`, `core/controller.py`, `gui/main_view.py`, testes de modelos; `core/chart_renderer.py`, prompt, `gui/style_settings_view.py`, testes de gráficos | concluída em 2026-08-17 |
| 12 | UX-01 | Terra / high | views de contas/estilo/principal e testes de UX | concluída em 2026-08-17 |
| 13 | CI-01 | Terra / high | workflow de testes, workflow de release e dependências de desenvolvimento | concluída em 2026-08-17 |
| 14 | PKG-01 | Terra / high | `README.md`, `requirements.txt`, `whl/`, `pyinstaller.spec`, workflow de release e helper Pandoc | concluída em 2026-08-17; opção 1 aprovada pelo responsável |
| 15 | DOC-01 | Terra / medium | `README.md`, `CLAUDE.md`, `TECHNICAL_REFERENCE.md` e este plano | concluída em 2026-08-17 |
| 16 | FINAL-01 | Sol / high | repositório completo, somente correções necessárias após revisão integrada | concluída em 2026-08-17 |
| 17 | HUMAN-02 | Responsável humano / — | smoke tests em ambientes reais e aprovação final | aguardando execução pelo responsável |

As ondas futuras permanecem em estado `planejada` até o coordenador iniciá-las. `HUMAN-01` é uma pendência humana transversal, fora das ondas automatizáveis; enquanto ela estiver aberta, continuam proibidos pushes de imagem e publicações de release.

## Regras obrigatórias para o modelo executor

1. Leia esta seção e toda a tarefa atual antes de editar qualquer arquivo.
2. Consulte a “Alocação obrigatória das tarefas críticas” e confirme que está usando o executor indicado.
3. Execute somente a primeira tarefa automatizável desmarcada ou uma tarefa atribuída à onda paralela atual pelo coordenador, sempre após suas dependências estarem concluídas.
4. Não antecipe refactors ou funcionalidades pertencentes a tarefas posteriores.
5. Antes de editar, execute `git status --short` e preserve alterações não relacionadas.
6. Use `apply_patch` para editar arquivos manualmente.
7. Nunca exiba, copie, registre, faça commit ou altere o conteúdo do `.env`.
8. Nunca execute `docker push`, remova tags/imagens remotas, rotacione credenciais, publique releases ou faça commit/push sem autorização explícita do usuário.
9. Não adicione uma dependência sem atualizar `requirements.txt`, documentar a razão e verificar compatibilidade com Python 3.11.
10. Todo acesso a Tkinter — inclusive `.get()`, `.set()`, `.configure()`, seleção de abas e leitura de widgets — deve ocorrer na thread principal.
11. Toda mudança funcional deve vir acompanhada de testes que falhariam antes da correção.
12. Ao terminar uma tarefa:
    - execute os testes indicados nela;
    - execute a suíte completa quando for a única tarefa em execução; em onda paralela, execute os testes específicos e deixe a suíte completa para o coordenador ao integrar a onda;
    - revise `git diff --check`;
    - não marque a tarefa nem acrescente registro se estiver atuando como subagente; entregue ao coordenador os testes e achados para integração;
    - fora de execução paralela, marque a tarefa como concluída somente se tudo passar e acrescente uma linha no “Registro de execução” com data, tarefa e resumo.
13. Se um teste falhar por causa da mudança, corrija antes de prosseguir. Se falhar por ambiente ou dependência externa, não marque a tarefa e registre o bloqueio.
14. Se a tarefa exigir revisão pelo Sol, não marque a revisão como concluída até que ela seja realizada em uma passagem separada e seus achados sejam corrigidos.
15. Se a implementação exigir uma decisão não prevista, pare e peça ao usuário. Não invente requisitos.

## Comandos padrão de verificação

Executar a partir da raiz do repositório:

```bash
git status --short
MPLCONFIGDIR=/tmp/auditoria-zabbix-mpl venv/bin/python -m unittest discover -v
git diff --check
```

Se `venv/bin/python` não existir, não instale pacotes silenciosamente. Informe o usuário e solicite autorização para criar o ambiente e instalar `requirements.txt`.

## Definição global de concluído

Uma tarefa somente pode ser marcada como concluída quando:

- os passos descritos foram implementados;
- os critérios de aceite foram verificados;
- os testes novos e antigos passaram;
- nenhuma credencial ou dado real foi incluído em testes ou logs;
- documentação afetada foi atualizada na mesma tarefa;
- não restaram comentários temporários, arquivos de debug ou código morto.

---

# Fase 0 — Baseline e contenção imediata

## [x] BASE-01 — Registrar o baseline

**Tipo:** automatizável, somente leitura.

**Objetivo:** confirmar o estado inicial antes de qualquer correção.

**Passos:**

1. Executar os três comandos padrão de verificação.
2. Registrar no fim deste arquivo a quantidade de testes, testes ignorados, falhas e arquivos já modificados ou não rastreados.
3. Não editar código nesta tarefa.

**Critério de aceite:** baseline registrado sem exposição do conteúdo do `.env`.

## [ ] HUMAN-01 — Tratar possível vazamento das credenciais Docker

**Tipo:** ação humana obrigatória. O modelo não pode executar.

**Executor:** responsável humano; nenhum modelo pode concluir esta tarefa em seu lugar.

**Risco:** `Dockerfile` usa `COPY . .`, o `.env` não está no `.dockerignore` e a imagem é publicada no Docker Hub.

**Ações do responsável:**

1. Suspender temporariamente novos pushes da imagem.
2. Rotacionar/revogar todas as credenciais que estavam no `.env` durante builds já publicados.
3. Verificar tags, datas, histórico de builds e camadas no Docker Hub.
4. Remover ou substituir imagens comprometidas conforme a política da organização.
5. Registrar quais credenciais e tags foram tratadas, sem colocar valores secretos neste arquivo.

**Critério de aceite:** responsável confirma por escrito que a contenção terminou.

**Observação:** tarefas locais podem continuar, mas nenhuma imagem deve ser publicada enquanto esta tarefa estiver aberta.

## [x] SEC-01 — Impedir que segredos entrem em imagens Docker

**Depende de:** BASE-01.

**Executor e revisão:** implementar com `gpt-5.6-terra` / `high`; revisar separadamente com `gpt-5.6-sol` / `high`.

**Arquivos:** `.dockerignore`, `Dockerfile`, `build_image.fish`, `tests/test_packaging_security.py`.

**Passos:**

1. Adicionar ao `.dockerignore`: `.env`, `.env.*`, exceção para `.env.example`, caches, ambientes virtuais, instaladores, wheelhouse, testes, documentos locais e artefatos gerados.
2. Substituir `COPY . .` no `Dockerfile` por cópias explícitas apenas dos pacotes `api/`, `core/`, `gui/`, `prompts/`, `templates/`, `main.py`, `__init__.py` e arquivos necessários em runtime.
3. Criar usuário não-root no `Dockerfile` e executar o aplicativo com esse usuário.
4. Alterar `build_image.fish` para fazer somente build por padrão. O push deve exigir opção explícita e confirmação visível.
5. Criar testes estáticos confirmando `.env` ignorado, `.env.example` permitido, inexistência de `COPY . .`, usuário não-root e ausência de push no caminho padrão.

**Não fazer:** não construir nem publicar imagem sem autorização; não apagar o `.env`.

**Critério de aceite:** testes novos passam e nenhum segredo local integra o conjunto explícito de arquivos copiados.

## [x] SEC-02 — Sanitizar o coletor de evidências do sistema operacional

**Depende de:** BASE-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** `tools/coleta_zabbix_os.sh`, `tests/test_os_collector.py`, `README.md`.

**Passos:**

1. Permitir sobrescrever em testes os paths de entrada e saída por variáveis específicas, mantendo os defaults atuais em produção.
2. Parar de copiar o `zabbix_server.conf` inteiro.
3. Implementar allowlist de parâmetros operacionais. Nunca coletar chaves contendo `password`, `passwd`, `secret`, `token`, `community`, `psk` ou `credential`, sem diferenciar caixa.
4. Substituir a coleta de processos por uma forma que inclua PID, nome do executável, CPU e memória, mas não argumentos.
5. Aplicar uma última redação defensiva antes de gravar o arquivo.
6. Testar com configuração sintética contendo valores seguros e secretos.
7. Atualizar o README explicando o que o coletor inclui e exclui.

**Critério de aceite:** o teste prova que `DBPassword`, tokens, communities e PSKs sintéticos não aparecem na evidência.

---

# Fase 1 — Fronteira entre GUI e threads

## [x] GUI-01 — Criar snapshots imutáveis das entradas da GUI

**Depende de:** BASE-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** novo `core/run_config.py`, `gui/main_view.py`, `core/controller.py`, testes do controller.

**Passos:**

1. Criar dataclasses imutáveis para configurações Zabbix/IA, dados do analista, limites, estilo, pedido de auditoria e pedido de coleta.
2. Campos secretos devem usar `repr=False`.
3. Converter `attached_files` para tupla no snapshot.
4. Criar em `MainView` métodos que montem snapshots na thread principal.
5. Fazer auditoria, coleta, teste de conexão e carregamento de modelos receberem dados prontos, sem ler Tk nas workers.
6. Centralizar extração e validação de credenciais nesses snapshots, removendo os três blocos duplicados do controller.
7. Remover do controller leituras diretas de `.get()`, widgets, `notebook`, `custom_instructions_text` e listas mutáveis da view.
8. Criar testes com view falsa que falhe se o controller tentar ler um widget.

**Verificação adicional:**

```bash
rg -n "self\.view\..*(\.get\(|_var|\.text\.|notebook)" core/controller.py
```

O comando não deve encontrar acessos diretos; chamadas a métodos de saída da view podem permanecer temporariamente até GUI-02.

**Critério de aceite:** workers recebem apenas objetos Python comuns e não consultam estado Tk.

## [x] GUI-02 — Criar fila de eventos para atualizações da interface

**Depende de:** GUI-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** `gui/main_view.py`, `core/controller.py`, testes da GUI/controller.

**Passos:**

1. Criar uma `queue.Queue` de eventos em `MainView`.
2. Agendar na thread principal um consumidor periódico usando `after()`.
3. Fazer workers apenas inserirem eventos Python na fila.
4. Encaminhar pela fila logs/estilos, progresso, chunks, limpeza, modelos, troca de aba, estado dos botões e diálogos.
5. `after()`, widgets e Tk Variables só podem ser usados pelo consumidor na thread principal.
6. Garantir ordem FIFO entre limpar relatório, selecionar aba e inserir chunks.
7. Testar ordem e descarte seguro depois do fechamento da janela.

**Critério de aceite:** nenhuma worker chama Tkinter direta ou indiretamente.

## [x] OPS-01 — Isolar cada operação e corrigir cancelar/reiniciar

**Depende de:** GUI-02.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** novo `core/operation.py`, `core/controller.py`, `api/zabbix_api.py`, testes do controller.

**Passos:**

1. Criar `OperationContext` com ID único, `cancel_event`, thread e estado.
2. Nunca reutilizar nem limpar evento de operação anterior.
3. Impedir nova operação enquanto outra estiver ativa.
4. Ao cancelar, apenas sinalizar o contexto, mostrar “Cancelando...”, manter Iniciar desabilitado e desabilitar Cancelar.
5. Reabilitar a interface somente no `finally` da mesma operação e se seu ID ainda for o ativo.
6. Passar `is_cancelled` a `collect_data()` e verificar entre fases e em loops longos.
7. Criar exceção própria de cancelamento para não tratá-lo como erro.
8. Testar reinício imediato, término atrasado, cancelamento durante coleta e ausência de chunks posteriores.

**Critério de aceite:** nunca existem duas auditorias ativas e uma operação não pode reativar outra.

## [x] CLI-01 — Tornar o subprocesso CLI cancelável em Linux e Windows

**Depende de:** OPS-01.

**Executor e revisão:** implementar com `gpt-5.6-terra` / `high`; revisar separadamente com `gpt-5.6-sol` / `high`.

**Arquivos:** `api/ai_cli_client.py`, `core/operation.py`, testes da CLI.

**Passos:**

1. Substituir `subprocess.run()` por `subprocess.Popen()`.
2. Usar `communicate()` com timeouts curtos em loop para verificar cancelamento.
3. Em POSIX, iniciar nova sessão e encerrar o grupo com `SIGTERM`, seguido de `SIGKILL` após tolerância curta.
4. No Windows, criar novo grupo e encerrar a árvore com mecanismo nativo testável; não usar `os.killpg`.
5. Limpar diretório temporário em sucesso, erro, timeout e cancelamento.
6. Diferenciar cancelamento, timeout, binário ausente e retorno não zero.
7. Testar ramificações por mocks e integração POSIX com subprocesso sintético quando possível.

**Critério de aceite:** cancelar encerra processo e filhos em tempo limitado e não deixa temporários.

---

# Fase 2 — Privacidade dos dados enviados à IA

## [x] PRIV-01 — Substituir anonimização por transformação estrutural

**Depende de:** GUI-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** novo `core/anonymizer.py`, `core/controller.py`, `gui/main_view.py`, testes novos.

**Passos:**

1. Criar função recursiva para dicionários, listas e escalares.
2. Redigir valores de chaves contendo `password`, `passwd`, `senha`, `pwd`, `secret`, `token`, `apikey`, `api_key`, `community`, `credential` ou `psk`.
3. Anonimizar IPv4/IPv6 válidos usando `ipaddress`.
4. Não tratar `1.3.6.1.4.1` como IPv4; criar teste de OID SNMP.
5. Usar mapeamento estável dentro da auditoria para pseudônimos repetíveis.
6. Criar redator separado para texto livre.
7. Ativar anonimização por padrão.
8. Se desligada e o destino não for Ollama local, exigir confirmação explícita.
9. Testar JSON, texto, caixa mista, IPv4, IPv6, OID, tokens e valores repetidos.

**Critério de aceite:** segredos são redigidos sem corromper OIDs e pseudônimos são consistentes.

## [x] PRIV-02 — Limitar anexos, proteger prompt e evitar vazamento de paths

**Depende de:** PRIV-01.

**Arquivos:** `core/controller.py`, `api/ai_api.py`, `prompts/report_template.txt`, testes.

**Passos:**

1. Usar `pathlib.Path(filepath).name`; nunca enviar caminho absoluto.
2. Definir limites constantes por arquivo, total de anexos e total lido.
3. Rejeitar ou truncar explicitamente, com aviso; nunca silenciosamente.
4. Delimitar JSON, evidências e instruções em seções inequívocas do prompt.
5. Informar no system prompt que nomes, métricas, logs e anexos são dados não confiáveis e não substituem instruções do sistema.
6. Validar JSON carregado: tipo raiz, tamanho máximo e versão de schema quando existir.
7. Testar path Windows, tamanhos excessivos e conteúdo com instrução maliciosa.

**Critério de aceite:** nenhum path absoluto aparece no prompt e limites produzem mensagem clara.

## [x] PRIV-03 — Alertar sobre transporte Zabbix inseguro

**Depende de:** GUI-01.

**Arquivos:** `gui/main_view.py`, `core/controller.py`, testes de validação.

**Passos:**

1. Criar validação pura da URL.
2. Pedir confirmação ao enviar senha/token por HTTP fora de localhost.
3. Pedir confirmação quando TLS estiver sem validação.
4. Nunca registrar senha, token ou Authorization.
5. Testar HTTPS, localhost HTTP, HTTP remoto e TLS ignorado.

**Critério de aceite:** conexões inseguras exigem consentimento e logs não contêm credenciais.

---

# Fase 3 — Cliente e coleta Zabbix

## [x] ZBX-01 — Implementar sessão, timeouts, retries seguros e logout

**Depende de:** OPS-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** `api/zabbix_api.py`, `core/controller.py`, novo `tests/test_zabbix_client.py`.

**Passos:**

1. Criar uma `requests.Session` por cliente.
2. Separar timeout de conexão e leitura.
3. Implementar retry com backoff somente para chamadas idempotentes e falhas transitórias.
4. Não repetir login/logout quando a resposta for ambígua.
5. Incrementar o ID JSON-RPC.
6. Criar exceções próprias para resposta não JSON e erro JSON-RPC.
7. Implementar lifecycle que faça logout apenas de sessão usuário/senha, nunca de API token, e sempre feche a `Session`.
8. Usar o lifecycle em teste, coleta e auditoria.
9. Remover `urllib3.disable_warnings()` global; limitar supressão à chamada com `verify_ssl=False`.
10. Testar retries, timeout, JSON inválido, logout e fechamento em sucesso/falha/cancelamento.

**Critério de aceite:** toda sessão usuário/senha tenta logout e a conexão HTTP é reutilizada.

## [x] ZBX-02 — Criar compatibilidade explícita por versão

**Depende de:** ZBX-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** `api/zabbix_api.py`, `tests/test_zabbix_versions.py`, `README.md`.

**Passos:**

1. Criar parser de versão em tupla numérica.
2. Implementar e testar:
   - anterior a 5.4: login `user` e auth no payload;
   - 5.4–6.2: `username` e auth no payload;
   - 6.4+: `username` e Bearer header;
   - anterior a 5.2: Super Admin por `user.type`;
   - 5.2+: roles Super Admin por `role.get`, depois usuários por `roleids`;
   - anterior a 7.0: proxy `host`/`status`;
   - 7.0+: proxy `name`/`operating_mode`.
3. Normalizar saída interna para campos únicos.
4. Não converter incompatibilidade em zero silencioso; registrar warning estruturado.
5. Criar fixtures/mocks para 5.0, 6.0, 6.4, 7.0 e 7.4.
6. Documentar versões cobertas por testes.

**Critério de aceite:** testes confirmam payloads corretos e saída normalizada comum.

## [x] ZBX-03 — Dividir `collect_data()` em fases resilientes

**Depende de:** ZBX-02.

**Arquivos:** `api/zabbix_api.py`, testes de coleta.

**Passos:**

1. Definir todas as chaves e valores vazios antes das chamadas.
2. Criar helper por seção: hosts, itens, templates, saúde interna, banco, triggers, discovery, alertas, problemas, housekeeping, usuários/roles, scripts, proxies, mídias, serviços, manutenção e SO.
3. Extrair uma única função de descoberta dos hosts de infraestrutura e reutilizá-la nas seções de templates e banco.
4. Cada helper recebe cancelamento e retorna dados ou warning estruturado.
5. Falha de seção não descarta seções anteriores, salvo autenticação inválida ou perda total de transporte.
6. Distinguir sucesso com dados, sucesso vazio, sem permissão, incompatível e falha transitória.
7. Acrescentar `_collection_metadata` com schema, data UTC, versão Zabbix, anonimização e warnings.
8. Emitir progresso por fase, sem regressão percentual.
9. Verificar cancelamento entre fases e em loops históricos.
10. Preservar `_fetch_trend_values()` e fallback `trend.get` singular.

**Critério de aceite:** falha sintética intermediária preserva dados anteriores e continua fases independentes.

## [x] ZBX-04 — Corrigir métricas e reduzir custo da coleta

**Depende de:** ZBX-03.

**Arquivos:** `api/zabbix_api.py`, `prompts/report_template.txt`, testes.

**Passos:**

1. Considerar agressivo somente `0 < delay < 30`; `delay=0` não é polling agressivo.
2. Criar parser de sufixos; macros/intervalos complexos ficam “não classificáveis”.
3. Incluir `error` nas amostras de itens não suportados.
4. Coletar LLD por `discoveryrule.get`, sem confundir com `drule.get`.
5. Coletar autenticação/MFA quando suportado e permitido, registrando indisponibilidade.
6. Reutilizar `zabbix[queue` existente; não duplicar métrica.
7. Normalizar lag, versão, modo e estado de proxy.
8. Usar `countOutput` somente quando não forem necessárias amostras/classificação.
9. Instrumentar número de chamadas; não fazer batching histórico que altere amostragem por item.
10. Atualizar prompt para novas chaves.

**Critério de aceite:** testes cobrem trapper, delay zero, sufixos, item error, LLD e proxies.

---

# Fase 4 — Provedores de IA

## [x] AI-01 — Criar contrato comum de streaming e conclusão

**Depende de:** OPS-01.

**Executor e revisão:** implementar e revisar em passagens separadas com `gpt-5.6-sol` / `high`.

**Arquivos:** `api/ai_api.py`, `api/ai_cli_client.py`, novo `api/ai_prompts.py`, testes dos provedores.

**Passos:**

1. Mover o system prompt comum para `api/ai_prompts.py` e remover suas cinco cópias dos caminhos API/CLI.
2. Criar evento comum com texto, tipo e motivo de término.
3. Cada provedor produz eventos de texto e exatamente um evento final.
4. Ignorar texto `None`/vazio do Gemini.
5. Capturar `finish_reason` da OpenAI, `stop_reason` da Anthropic e `done_reason` do Ollama.
6. Configurar timeouts explícitos; respeitar milissegundos no `HttpOptions` do Gemini.
7. Tornar limite Anthropic configurável, default maior que 4096, detectando `max_tokens`.
8. Controller só registra sucesso após evento final válido.
9. Em truncamento/quebra, preservar texto, marcar parcial e avisar.
10. Testar conclusão, `None`, truncamento, timeout e quebra após texto parcial em todos os provedores.

**Critério de aceite:** relatório incompleto nunca aparece como concluído com sucesso.

## [x] AI-02 — Padronizar retries sem duplicar relatórios

**Depende de:** AI-01.

**Arquivos:** `api/ai_api.py`, testes.

**Passos:**

1. Tornar explícitos retries dos SDKs OpenAI/Anthropic sem empilhar loops.
2. Definir política equivalente para Gemini/Ollama em 408, 429, conexão e 5xx.
3. Respeitar `Retry-After`.
4. Repetir automaticamente somente antes do primeiro chunk.
5. Depois do primeiro chunk, marcar parcial e oferecer regeneração pelo cache.
6. Testar que texto parcial nunca é duplicado.

**Critério de aceite:** falha inicial pode repetir; falha posterior não reinicia silenciosamente.

## [x] AI-03 — Corrigir descoberta e estado dos modelos

**Depende de:** GUI-02.

**Arquivos:** `api/ai_api.py`, `core/controller.py`, `gui/main_view.py`, testes.

**Passos:**

1. Usar `client.models.list()` para Anthropic.
2. Manter fallback pequeno e rotulado somente se a lista falhar.
3. Separar estado `idle`, `loading`, `ready`, `error` dos valores selecionáveis.
4. Placeholders visuais nunca são modelos.
5. Associar ID ao carregamento e ignorar resposta antiga após troca de provedor.
6. Validar provedor, autenticação e modelo antes da auditoria.
7. Testar resposta fora de ordem e falha.

**Critério de aceite:** placeholders não passam pela validação.

## [x] AI-04 — Implementar streaming CLI por capacidade

**Depende de:** CLI-01 e AI-01.

**Arquivos:** `api/ai_cli_client.py`, testes da CLI, README.

**Passos:**

1. Criar adaptador separado para Claude, Codex e Gemini CLI.
2. Confirmar flags na versão instalada via `--help` antes de usar JSONL/streaming.
3. Não assumir `--output-format stream-json` universal.
4. Implementar parser incremental somente para formatos confirmados e com fixtures.
5. Preservar JSON não-streaming quando não houver saída incremental estável.
6. Integrar cancelamento/timeout.
7. Não logar stdout/stderr integral contendo prompt.
8. Documentar streaming ou fallback por provedor.

**Critério de aceite:** cada provedor tem parser testado ou fallback documentado.

---

# Fase 5 — Persistência, exportação e UX

## [x] DATA-01 — Corrigir paths, validação e gravação atômica

**Depende de:** ZBX-03.

**Arquivos:** `core/paths.py`, helper novo, `core/controller.py`, `gui/main_view.py`, `requirements.txt`, testes.

**Passos:**

1. Adicionar `platformdirs` com versão fixa compatível com Python 3.11.
2. Manter `resource_path()` somente para recursos empacotados.
3. Criar paths de configuração, cache e dados do usuário; criar diretórios sob demanda.
4. Implementar escrita atômica: temporário no mesmo diretório, flush, `fsync`, `os.replace`.
5. Usar permissão `0600` quando suportado.
6. Validar/normalizar tipos e limites de settings; avisar e carregar defaults se inválido.
7. Criar envelope de cache com schema, UTC, fingerprint/nome seguro do servidor, versão Zabbix, anonimização, dados e warnings.
8. Mostrar origem/data e confirmar divergência ao regenerar.
9. Migrar legado sem apagar o original antes do sucesso.

**Critério de aceite:** outro `cwd` não muda paths, escrita interrompida não corrompe e cache divergente exige confirmação.

## [x] EXP-01 — Extrair o motor de exportação e testar código real

**Depende de:** GUI-01 e DATA-01.

**Arquivos:** novo `core/report_exporter.py`, `gui/main_view.py`, `tests/test_pdf_pipeline.py`, testes novos.

**Passos:**

1. Mover exportação Markdown/DOCX/ODT/PDF e temporários para classe sem Tk.
2. Passar estilo/metadados como snapshot.
3. Usar callbacks Python para logs/progresso.
4. Preservar limpeza em `finally`.
5. Fazer teste PDF chamar o exportador real e preservar smoke tests Typst.
6. Testar sucesso/falha e limpeza para formatos não interativos.

**Critério de aceite:** GUI não contém pipeline pesado e testes chamam `ReportExporter`.

## [x] EXP-02 — Tornar gráficos tolerantes e adicionar pie

**Depende de:** EXP-01.

**Arquivos:** `core/chart_renderer.py`, prompt, preview, testes.

**Passos:**

1. Tratar quantidades diferentes de rótulos/valores com política previsível.
2. Converter `N/A`, vazio e inválido isolado em `NaN`, sem descartar a série.
3. Avisar sobre série totalmente inválida.
4. Criar parser Mermaid `pie` separado e renderizar com `ax.pie`.
5. Não aplicar normalização line/bar a pie.
6. Atualizar prompt/preview.
7. Testar rótulos curtos/longos, `N/A`, múltiplas séries e pie válido/inválido.

**Critério de aceite:** ponto inválido não elimina série e pie válido é exportado.

## [x] UX-01 — Corrigir contas, preview, logs e exportação

**Depende de:** GUI-02, DATA-01 e EXP-01.

**Arquivos:** views de contas/estilo/principal e testes.

**Passos:**

1. Confirmar overwrite e remoção de conta.
2. Ao renomear/remover, apagar credencial antiga do keyring após persistência nova ter sucesso.
3. Aplicar debounce com `after_cancel` na thread principal.
4. Usar ID de geração e arquivo único; ignorar preview antigo e cancelar callbacks ao fechar.
5. Aplicar cores de severidade no log.
6. Mostrar sucesso/erro para MD, TXT, DOCX, ODT e PDF.
7. Autosave, se implementado, deve ser opt-in, desligado por padrão e restrito ao data dir.
8. Testar conflitos, keyring por mocks, debounce e resultados fora de ordem.

**Critério de aceite:** sem overwrite silencioso, credencial órfã conhecida ou corrida visível.

---

# Fase 6 — CI, empacotamento e documentação

## [x] CI-01 — Executar testes e lint antes de releases

**Depende de:** testes das fases anteriores.

**Arquivos:** novo workflow de testes, workflow de release, dependências dev.

**Passos:**

1. Fixar Ruff compatível com Python 3.11.
2. Criar workflow para PR/push em Python 3.11 e 3.12.
3. Executar `unittest discover`.
4. Executar Ruff inicialmente com `E9`, `F63`, `F7`, `F82`.
5. Fazer build de release depender dos testes.
6. Não exigir display.

**Critério de aceite:** falha de teste impede release.

## [x] PKG-01 — Alinhar Python, wheels e Pandoc

**Depende de:** EXP-01 e CI-01.

**Arquivos:** README, requirements, `whl/`, spec PyInstaller, release, helper Pandoc.

**Passos:**

1. Declarar Python 3.11 mínimo.
2. Tratar `requirements.txt` como fonte única e remover divergência dos wheels.
3. Pedir decisão ao usuário entre wheelhouse completo por plataforma ou remoção da promessa totalmente offline.
4. Baixar Pandoc durante build de cada plataforma e incluí-lo no bundle.
5. Configurar caminho do Pandoc empacotado em runtime.
6. Não baixar Pandoc em runtime no executável; por fonte, pedir confirmação antes do fallback.
7. Adicionar smoke test de Pandoc no bundle e exportação offline.

**Critério de aceite:** docs/dependências concordam e release exporta sem download.

## [x] PKG-02 — Endurecer Docker/Wayland

**Depende de:** SEC-01.

**Arquivos:** `exec_wayland.fish`, Dockerfile, README.

**Passos:**

1. Executar com UID/GID do usuário.
2. Remover `xhost +local:root`; se necessário, usar autorização restrita e cleanup por `trap`.
3. Remover `--net host` padrão; oferecer somente opção explícita.
4. Remover montagem de `$PWD` sobre `/app`.
5. Montar apenas saída/configuração com permissões mínimas.
6. Não montar Wayland inexistente.
7. Validar paths/argumentos e documentar X11/Wayland.

**Critério de aceite:** padrão sem root, host network, `xhost +local:root` ou overlay de código.

## [x] DOC-01 — Sincronizar documentação e arquitetura

**Depende de:** tarefas automatizáveis anteriores.

**Arquivos:** README, CLAUDE, referência técnica, este plano.

**Passos:**

1. Corrigir Python mínimo e autosave descrito.
2. Documentar paths, cache, anonimização, anexos e riscos de nuvem.
3. Documentar matriz Zabbix coberta.
4. Documentar cancelamento e streaming/fallback CLI.
5. Atualizar arquitetura de snapshots/event queue.
6. Substituir números de linha frágeis por referências conceituais quando possível.

**Critério de aceite:** documentação descreve o comportamento real.

---

# Fase 7 — Verificação final

## [x] FINAL-01 — Auditoria automatizada final

**Executor:** `gpt-5.6-sol` / `high`, realizando a revisão integrada de todas as alterações.

**Depende de:** todas as tarefas automatizáveis.

**Passos:**

1. Executar suíte, lint e `git diff --check`.
2. Confirmar por busca: sem `COPY . .`, `.env` ignorado, controller sem Tk, CLI sem `subprocess.run`, sem warnings SSL globais, queue não duplicada e placeholders inválidos.
3. Inspecionar diff por segredos/gerados.
4. Testar exportação PDF/DOCX/ODT/MD/TXT.
5. Registrar resultado.

**Critério de aceite:** verificações automatizadas passam.

## [ ] HUMAN-02 — Smoke test e aprovação final

**Tipo:** ação humana obrigatória.

**Cenários:** Linux por fonte/empacotado, Windows empacotado, Zabbix 6.0 e 7.0/7.4, todos os fluxos, cancelamento em coleta/API/CLI, exportações, anonimização e Docker/Wayland se suportado.

**Critério de aceite:** responsável confirma cenários aplicáveis e exceções conhecidas.

---

# Registro de execução

| Data | Tarefa | Resultado | Testes/observações |
|---|---|---|---|
| 2026-08-15 | BASE-01 | Concluída | 50 testes executados; 50 passaram; 0 ignorados; 0 falhas; `git diff --check` limpo. Estado inicial: `docs/superpowers/plans/melhorias.md` já estava não rastreado; nenhum outro arquivo modificado ou não rastreado. |
| 2026-08-15 | SEC-01 | Concluída | Implementação e revisão separada realizadas. `.dockerignore` protege `.env` e contexto local; Dockerfile copia somente runtime e usa usuário não-root; build padrão não publica e `--push` exige confirmação. 55 testes passaram, incluindo 5 novos testes de segurança; `fish --no-execute build_image.fish` e `git diff --check` passaram. Nenhuma imagem foi construída ou publicada. |
| 2026-08-16 | SEC-02 | Concluída | Implementação e revisão Sol em passagens separadas. Coletor aceita paths injetáveis para testes, coleta somente allowlist operacional, não inclui argumentos de processos e aplica redação final. Teste sintético confirma que DBPassword, tokens, communities e PSKs não aparecem na evidência. |
| 2026-08-16 | GUI-01 | Concluída | Implementação e revisão Sol em passagens separadas. Snapshots imutáveis removem leituras Tk das workers, ocultam segredos no `repr` e convertem anexos em tupla. Busca obrigatória no controller não retornou acessos diretos. |
| 2026-08-16 | ONDA-01 | Concluída | Integração validada: 60 testes passaram; `git diff --check` passou. |
| 2026-08-16 | GUI-02 | Concluída | Implementação e revisão Sol em passagens separadas. Fila FIFO centraliza logs, progresso, chunks, abas, modelos, diálogos e estado de botões; testes validam ordem e descarte após fechamento. |
| 2026-08-16 | PKG-02 | Concluída | Implementado por Terra e revisado pelo coordenador. Lançador usa UID/GID atual, sem root, host network ou overlay de código por padrão; Wayland é condicional e dados persistentes recebem permissões `0700`. |
| 2026-08-16 | ONDA-02 | Concluída | Integração validada: 68 testes passaram; `fish --no-execute exec_wayland.fish` e `git diff --check` passaram. |
| 2026-08-16 | OPS-01 | Concluída | Implementação e revisão Sol em passagens separadas. Contextos únicos impedem operações concorrentes; cancelamento cooperativo preserva o estado da operação e descarta chunks tardios. Teste de corrida repetido 200 vezes sem falhas. |
| 2026-08-16 | ONDA-03 | Concluída | Integração validada: 74 testes passaram; `git diff --check` passou. |
| 2026-08-16 | CLI-01 | Concluída | Implementada por Terra e revisada separadamente por Sol. A CLI usa `Popen` com polling, encerramento de grupos POSIX/árvores Windows, erros distintos e limpeza garantida; o cancelamento da operação chega ao subprocesso. |
| 2026-08-16 | ZBX-01 | Concluída | Implementação e revisão Sol em passagens separadas. Sessões HTTP reutilizáveis têm timeout dividido, IDs JSON-RPC incrementais, retries idempotentes conservadores, logout apenas para usuário/senha e fechamento garantido. |
| 2026-08-16 | ONDA-04 | Concluída | Integração validada: 93 testes passaram; `git diff --check` passou. `TECHNICAL_REFERENCE.md` atualizado para CLI cancelável e lifecycle da sessão Zabbix. |
| 2026-08-16 | ZBX-02 | Concluída | Implementação e revisão Sol em passagens separadas. Matriz explícita de 5.0, 5.2, 6.0, 6.4, 7.0 e 7.4 para login, transporte de autenticação, Super Admins e proxies; warnings estruturados preservados mesmo sem logger. Revisão corrigiu o filtro de `roleid` e endureceu o parser de versão. |
| 2026-08-16 | PRIV-01 | Concluída | Implementação e revisão Sol em passagens separadas. Anonimizador estrutural redige chaves sensíveis, pseudonimiza IPv4/IPv6 de forma estável e preserva OIDs; inclui texto livre/JSON, anexos, cache e coleta. A anonimização é padrão e o envio remoto sem ela exige confirmação explícita. |
| 2026-08-16 | ONDA-05 | Concluída | Integração validada: 118 testes passaram; `git diff --check` passou. As revisões independentes identificaram e corrigiram falhas de filtro de roles, OID, IP com pontuação e valores JSON escapados/não textuais. |
| 2026-08-17 | ZBX-03 | Concluída | Coleta preserva schema e dados anteriores quando endpoints opcionais falham, registra warnings e metadados UTC/versionados, emite progresso por fase e reutiliza a descoberta de hosts de infraestrutura. Teste sintético cobre falha intermediária. |
| 2026-08-17 | PRIV-02 | Concluída | Anexos têm limites explícitos e usam somente o basename; JSON importado é limitado/validado; dados, evidências e instruções são delimitados e todos os modos de IA recebem orientação contra prompt injection. |
| 2026-08-17 | ONDA-06 | Concluída | Integração validada: 123 testes passaram; `git diff --check` passou. README e referência técnica sincronizados. |
| 2026-08-17 | ZBX-04 | Concluída | Parser de intervalos evita classificar `delay=0`, macros e agendas como polling agressivo; itens não suportados preservam `error`; LLD usa `discoveryrule.get`; autenticação e MFA (7.0+) registram indisponibilidade sem falso negativo; proxies expõem estado/lag normalizados; metadados registram `api_call_count`. |
| 2026-08-17 | AI-01 | Concluída | `AIStreamEvent` unifica texto e finalização para SDKs e CLI. Motivos de término, timeout explícito, limite Anthropic configurável, parcialidade e falhas são tratados sem anunciar relatório incompleto como sucesso. |
| 2026-08-17 | ONDA-07 | Concluída | Revisão integrada concluída: 130 testes passaram; `git diff --check` passou. README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | PRIV-03 | Concluída | Validação pura recusa URLs Zabbix inválidas ou com credenciais; HTTP remoto e TLS sem validação exigem consentimento antes da operação. Senha, token e `Authorization` são redigidos dos logs. |
| 2026-08-17 | AI-02 | Concluída | Política única realiza até três tentativas somente antes do primeiro texto, cobre conexão/408/429/5xx, respeita `Retry-After`, observa cancelamento e desativa retries internos dos SDKs. Falha posterior preserva o texto parcial sem duplicação e orienta regeneração pelo cache. |
| 2026-08-17 | AI-04 | Concluída | Adaptadores separados sondam o help instalado antes de habilitar formatos estruturados. Fixtures validam deltas Claude e eventos Codex; Gemini mantém fallback final. A sonda real confirmou streaming para Claude/Codex e JSON final para Gemini nesta máquina; erros omitem stdout/stderr. |
| 2026-08-17 | ONDA-08 | Concluída | Revisão integrada concluída: 155 testes passaram; sonda real das três CLIs e `git diff --check` passaram. README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | DATA-01 | Concluída | `platformdirs` separa recursos empacotados de configuração/cache/dados do usuário. Settings são validados e gravados atomicamente; cache versionado registra UTC, origem segura/fingerprint, versão, anonimização, warnings e dados. Reutilização divergente exige confirmação e migrações preservam os arquivos legados. |
| 2026-08-17 | ONDA-09 | Concluída | Revisão integrada concluída: 169 testes passaram; `pip check`, buscas estáticas de paths/Tk e `git diff --check` passaram. README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | EXP-01 | Concluída | `ReportExporter` sem Tk concentra MD/TXT/DOCX/ODT/PDF, gráficos, Pandoc/Typst, callbacks e temporários. Snapshots imutáveis chegam da GUI; testes cobrem sucesso, falha, limpeza e o pipeline PDF real com gráfico Mermaid. |
| 2026-08-17 | ONDA-10 | Concluída | Integração validada: 173 testes passaram; `git diff --check` passou. README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | AI-03 | Concluída | Anthropic usa `models.list()` com fallback curto e avisado; estados `idle/loading/ready/error` não contaminam valores selecionáveis. IDs monotônicos descartam respostas antigas, e a validação recusa provedor, autenticação ou modelo inválidos. |
| 2026-08-17 | EXP-02 | Concluída | Séries `xychart-beta` preservam pontos válidos quando há `N/A`/vazio, ajustam rótulos de forma determinística e avisam quando totalmente inválidas. Parser `pie` separado renderiza com `ax.pie` sem normalização line/bar; prompt e prévia foram atualizados. |
| 2026-08-17 | ONDA-11 | Concluída | Testes focados de descoberta, fila GUI, gráficos e exportação passaram; integração conjunta incluída na validação de 198 testes. |
| 2026-08-17 | UX-01 | Concluída | Contas confirmam conflitos/remoção e limpam nomes antigos do keyring após persistência. Prévia usa debounce, IDs e arquivos únicos; resultados atrasados são ignorados. Logs aplicam severidade e todos os formatos exibem sucesso/erro. |
| 2026-08-17 | ONDA-12 | Concluída | Integração validada: 198 testes passaram; compilação dos módulos, buscas estáticas e `git diff --check` passaram. README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | CI-01 | Concluída | Workflow reutilizável executa `unittest` em Python 3.11/3.12 e Ruff 0.16.0 com `E9,F63,F7,F82`, sem display. O release exige o job `quality` antes do build; testes estáticos cobrem os gatilhos e a cadeia de dependências. |
| 2026-08-17 | ONDA-13 | Concluída | Integração validada: 202 testes passaram; Ruff e `git diff --check` passaram. README e TECHNICAL_REFERENCE.md sincronizados com o gate de CI/release. |
| 2026-08-17 | PKG-01 | Concluída | Responsável escolheu remover a promessa offline por wheelhouse parcial. Python mínimo alinhado em 3.11; `requirements.txt` é a fonte única e os wheels divergentes foram removidos. Pandoc é preparado por plataforma e incorporado ao PyInstaller; executável nunca baixa em runtime, fonte exige consentimento. Build Linux real e smoke DOCX/PDF com proxies inválidos passaram. |
| 2026-08-17 | ONDA-14 | Concluída | Integração validada: 214 testes, Ruff, `pip check` e `git diff --check` passaram. Bundle Linux real exportou DOCX/PDF offline; README e TECHNICAL_REFERENCE.md sincronizados. |
| 2026-08-17 | DOC-01 | Concluída | README, CLAUDE.md e referência técnica foram alinhados ao comportamento real: Python 3.11+, persistência sem autosave de relatório/log, paths/cache, limites e alcance da anonimização, riscos de nuvem, matriz Zabbix 5.0–7.4, cancelamento, streaming/fallback CLI e fronteira de snapshots/fila da GUI. Referências conceituais substituíram assinaturas e seções obsoletas. |
| 2026-08-17 | ONDA-15 | Concluída | Validação integrada: 214 testes passaram; Ruff crítico, buscas de consistência documental e `git diff --check` passaram. |
| 2026-08-17 | FINAL-01 | Concluída | Revisão integrada encontrou um `subprocess.run()` residual no encerramento da árvore CLI no Windows; ele foi substituído por `Popen` com espera limitada e fallback, com teste de timeout do próprio `taskkill`. Suíte, lint, buscas obrigatórias, inspeção de segredos/gerados e exportações reais passaram. |
| 2026-08-17 | ONDA-16 | Concluída | Validação final: 215 testes, Ruff crítico, `compileall`, `pip check`, sintaxe Fish e `git diff --check` passaram. Smoke real gerou MD, TXT, DOCX, ODT e PDF; README e TECHNICAL_REFERENCE.md foram atualizados. HUMAN-02 permanece pendente. |

# Resumo de dependências

```text
BASE-01
├── SEC-01 ─────────────────────────────── PKG-02
├── SEC-02
├── GUI-01 ── GUI-02 ── OPS-01 ── CLI-01 ── AI-04
│              │          ├── ZBX-01 ── ZBX-02 ── ZBX-03 ── ZBX-04
│              │          └── AI-01 ── AI-02
│              ├── AI-03
│              ├── PRIV-01 ── PRIV-02
│              ├── PRIV-03
│              └── UX-01
└──────────────────────────── DATA-01 ── EXP-01 ── EXP-02

Testes acumulados ── CI-01 ── PKG-01
Todas automatizáveis ── DOC-01 ── FINAL-01 ── HUMAN-02
```

# Fora da autonomia do modelo

- Rotacionar ou revelar credenciais.
- Apagar imagens/tags remotas.
- Publicar imagem ou release.
- Fazer commit, push ou PR sem pedido.
- Desabilitar TLS/SSL para contornar erro.
- Declarar HUMAN-01/HUMAN-02 concluída sem confirmação humana.
