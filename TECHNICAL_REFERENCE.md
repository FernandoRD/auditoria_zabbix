# 🛠️ Referência Técnica: Auditoria Inteligente de Zabbix

Este documento descreve o funcionamento interno, a arquitetura e as decisões técnicas do projeto **Auditoria Inteligente de Zabbix**. Seu objetivo é servir como um guia para desenvolvedores que desejam manter, refatorar ou expandir a aplicação.

---

## 🏗️ Arquitetura do Projeto

A aplicação segue uma arquitetura orientada a componentes, vagamente baseada no padrão **MVC (Model-View-Controller)**, para separar a interface gráfica das lógicas de negócio e comunicação com APIs externas.

### Estrutura de Diretórios e Módulos

- **`/gui` (View)**: Módulo responsável pela interface gráfica construída com `ttkbootstrap` (um wrapper moderno para `Tkinter`).
  - `main_view.py`: Janela principal, abas, barras de progresso, captura dos snapshots imutáveis de entrada e consumo da fila de eventos da interface.
  - `manage_accounts_view.py`, `style_settings_view.py`, etc.: Componentização das janelas secundárias (Modais) para evitar inchaço no arquivo principal.
- **`/api` (Integrações / Model)**:
  - `zabbix_api.py`: Classe `ZabbixClient`. Gerencia o protocolo JSON-RPC, autenticação nativa e as regras de negócio de extração de dados.
  - `ai_api.py`: Classe `AIClient`. Abstrai múltiplos provedores de LLMs (Google Gemini, OpenAI, Anthropic, Ollama) e os converte para eventos comuns de stream, com suporte a dois modos de autenticação por conta (`auth_mode`): `api_key` (SDK oficial) ou `cli` (delega para `ai_cli_client.py`).
  - `ai_prompts.py`: Fonte única do system prompt e do dataclass imutável `AIStreamEvent` (`text` ou `final`, com motivo, parcialidade e erro opcional).
  - `ai_cli_client.py`: Funções puras de montagem de comando (`build_cli_command`, `build_cli_input_text`, `extract_cli_json_text`, `cli_binary_status`) e o orquestrador `generate_via_cli()`, que roda `claude`/`codex`/`gemini` como subprocesso sandboxed. Consulte “Modo CLI local dos provedores de IA”.
- **`/core` (Controller)**:
  - `controller.py`: Classe `Controller`. Orquestra as ações do usuário e as workers sem ler widgets nem chamar Tkinter.
  - `run_config.py`: dataclasses imutáveis `ZabbixConfig`, `AIConfig`, `AnalystData`, `CollectionLimits`, `ReportStyle`, `AuditRequest` e `CollectionRequest`. Segredos não aparecem no `repr`, e anexos são congelados como tupla.
  - `operation.py`: `OperationContext` exclusivo por execução, com identidade, estado e cancelamento cooperativo. O contexto nunca é reutilizado; coleta Zabbix e geração via CLI recebem seu callback `is_cancelled`.
  - `anonymizer.py`: anonimização estrutural de objetos/texto, redação de campos sensíveis e pseudonimização estável de IPv4/IPv6 durante uma auditoria.
  - `chart_renderer.py`: Parsers separados para `xychart-beta` e `pie` do Mermaid.js e renderização em PNG via matplotlib (Agg). Consulte “Renderização de Gráficos e Exportação”.
  - `paths.py`: mantém `resource_path()` restrito a prompts/templates empacotados e resolve configuração, cache e dados graváveis com `platformdirs`.
  - `pandoc_runtime.py`: seleciona o Pandoc incorporado em builds PyInstaller, valida a versão mínima e controla o único fallback de download permitido, sempre por fonte e após consentimento explícito.
  - `persistence.py`: valida settings, implementa escrita atômica e gerencia o envelope versionado/migração do cache.
  - `report_exporter.py`: `ReportExporter` sem dependência de Tk, responsável por MD/TXT/DOCX/ODT/PDF, renderização dos gráficos, Pandoc/Typst e ciclo de vida dos temporários.
- **`/prompts`**:
  - `report_template.txt`: O *System Prompt* central. Define a persona, a estrutura de tópicos exigida e as regras de formatação, incluindo `xychart-beta` para tendências e `pie` para distribuições proporcionais.
- **`/templates`**:
  - `report_template.docx`: documento de referência do Pandoc para exportação Word.
  - `report_template.typ`: template Typst (capa, margens, numeração) para exportação PDF.
- **`/tests`**:
  - Testes unitários e smoke tests (`unittest`, stdlib — sem framework de teste adicional) cobrem integrações de IA/Zabbix, controller/GUI, persistência, segurança, gráficos e exportação real. Rodar com `python3 -m unittest discover -s tests -v`.
- **`/.github/workflows`**:
  - `tests.yml`: gate reutilizável de qualidade, disparado também em pushes e pull requests. Executa a suíte `unittest` em Python 3.11/3.12 e o Ruff fixado em `requirements-dev.txt` com as regras críticas `E9`, `F63`, `F7` e `F82`.
  - `release.yml`: ao receber uma tag `v*.*.*`, chama `tests.yml` no job `quality`; a cadeia `quality → build → release` impede build e publicação quando qualquer teste, lint, build ou smoke offline falha.
- **`/tools`**:
  - `prepare_pandoc.py`: baixa o binário de Pandoc da plataforma durante o build, valida a versão mínima e o deixa em `build/pandoc/` para inclusão pelo spec.

### Fronteira GUI, snapshots e fila de eventos

Tkinter pertence exclusivamente à thread principal. Os handlers de `MainView` leem `StringVar`/`BooleanVar`, campos de texto, seleção de modelo, estilo e lista de anexos e constroem snapshots de `core.run_config`. A reserva da operação recebe somente esses valores Python; a worker não consulta widgets nem listas mutáveis da view.

No sentido inverso, `Controller` e o exportador chamam publicadores como `log()`, `update_progress()`, `append_report_chunk()` e `set_operation_state()`. Esses métodos apenas inserem tuplas Python em `MainView.ui_event_queue`. O consumidor periódico, agendado com `after()` na thread principal, aplica logs, progresso, chunks, troca de aba, modelos, diálogos e estado dos controles em ordem FIFO. Ao destruir a janela, a fila é fechada e eventos tardios são descartados.

Existe no máximo uma operação Zabbix/IA por vez. `_start_operation()` reserva atomicamente um novo `OperationContext`; iniciar outra operação enquanto a vaga está ocupada é recusado. Cancelar muda somente o contexto atual para `cancelling`. A worker verifica o evento entre fases, durante esperas/retries e durante o stream; `run_if_active()` impede publicar chunks depois do cancelamento, e `begin_completion()` resolve a corrida entre “cancelar” e “concluir”. Somente o `finally` da operação dona do mesmo ID libera os controles, portanto um término antigo não pode reabilitar a GUI de uma execução mais nova.

---

## ✅ Integração Contínua e Gate de Release

O workflow de testes define `workflow_call`, além dos gatilhos de `push` e `pull_request`, para manter uma única implementação do gate. Os jobs usam apenas `ubuntu-latest`, checkout e Python: não iniciam Tk, não configuram `DISPLAY` nem dependem de Xvfb. `MPLBACKEND=Agg` e um `MPLCONFIGDIR` temporário mantêm os testes de gráficos headless.

O job `unit-tests` instala `requirements.txt` e executa `python -m unittest discover -s tests -v` separadamente em Python 3.11 e 3.12. O job `lint` usa Python 3.11, instala `requirements-dev.txt` e executa `ruff check --select E9,F63,F7,F82 .`; esse conjunto inicial bloqueia erros de sintaxe e falhas críticas de nomes/controle de fluxo sem introduzir ainda uma política ampla de estilo.

No workflow de release, `build` declara `needs: quality`, e `release` continua com `needs: build`. Em cada runner Windows/Linux, `tools/prepare_pandoc.py` baixa Pandoc 3.1.7+, `pyinstaller.spec` exige o binário em `build/pandoc/` e o adiciona ao destino interno `pandoc/`. O spec também fixa `pathex` na própria raiz (`SPECPATH`), evitando bundles que iniciem sem os pacotes locais. Antes de compactar, o workflow executa `AuditoriaZabbix --packaging-smoke-test` com proxies apontados para uma porta inválida; o comando precisa gerar DOCX e PDF usando o Pandoc incorporado. Assim, uma tag não pode publicar artefatos que dependam de download em runtime ou que não iniciem corretamente.

O projeto requer Python 3.11 ou superior. `requirements.txt` é a fonte única de dependências de runtime; não há wheelhouse parcial no repositório nem promessa de instalação por fonte totalmente offline. A validação local equivalente do código é:

```bash
pip install -r requirements.txt -r requirements-dev.txt
MPLBACKEND=Agg python -m unittest discover -s tests -v
ruff check --select E9,F63,F7,F82 .
```

Na auditoria integrada final de 17/08/2026 (Onda 16), **215 testes** passaram junto com Ruff, `compileall`, `pip check`, parsing dos scripts Fish e `git diff --check`. Também passaram as buscas obrigatórias por cópia ampla no Docker, `.env` não ignorado, acesso Tk no controller, `subprocess.run()` no adaptador CLI, supressão global de warnings TLS, duplicação da fila principal e placeholders de modelo aceitos indevidamente. O smoke test de exportação gerou MD, TXT, DOCX, ODT e PDF reais e validou os contêineres ZIP dos formatos Office e a assinatura do PDF. A revisão automatizada está concluída; a matriz de smoke tests em ambientes reais continua sendo a etapa humana seguinte.

---

## ⚙️ Fluxos de Funcionamento Interno

### 1. Autenticação e Adaptação de Versão (Zabbix API)
O Zabbix mudou seu método de autenticação da versão 6.4 em diante. O método genérico baseado no *payload* (`"auth": "token"`) foi preterido em favor de cabeçalhos HTTP (`Authorization: Bearer token`).
* **Como funciona:** O método `discover_version()` faz uma chamada não autenticada para `apiinfo.version`. O Python faz o *parse* da string resultante e ajusta a flag `self.use_header_auth`. Todas as chamadas subsequentes no método `api_call` injetam o token no local correto dinamicamente.
* **Transporte e retries:** cada `ZabbixClient` possui uma única `requests.Session`, usa timeout separado de conexão/leitura e incrementa o ID JSON-RPC por chamada lógica. Somente `apiinfo.version` e métodos `*.get` podem repetir falhas transitórias (`408`, `429`, `5xx` selecionados, timeout/conexão), com backoff exponencial e o mesmo ID durante as tentativas. Login, logout e demais chamadas potencialmente mutáveis nunca são repetidos após resultado ambíguo.
* **Erros, URL e TLS:** resposta não JSON gera `ZabbixInvalidResponseError`; erro JSON-RPC gera `ZabbixAPIError`. A validação pura do controller aceita somente HTTP/HTTPS com host, recusa credenciais ou parâmetros sensíveis na URL e distingue loopback de destino remoto. HTTP remoto e HTTPS com `verify_ssl=False` exigem consentimento explícito antes de a operação ser criada. Quando a validação TLS está desligada, a supressão de `InsecureRequestWarning` vale apenas durante aquela requisição, sem alterar warnings HTTPS globais do processo. Loggers e exceções que atravessam o controller passam por redação de senha, token e `Authorization`.
* **Lifecycle:** `close()` é idempotente, tenta `user.logout` somente para sessão criada por usuário/senha e sempre fecha a sessão HTTP. Token de API nunca dispara logout. O controller garante `close()` em `finally` nos fluxos de teste de conexão e coleta, inclusive em falha ou cancelamento.

| Versão coberta por teste | Login usuário/senha | Transporte autenticado | Super Admins | Proxies |
|---|---|---|---|---|
| 5.0 | parâmetro `user` | campo `auth` no payload | `user.get(type=3)`, nome em `alias` | `host`/`status` |
| 5.2 | parâmetro `user` | campo `auth` no payload | `role.get(type=3)` e `user.get` filtrado por `roleid`; nome em `alias` | `host`/`status` |
| 6.0 | parâmetro `username` | campo `auth` no payload | roles/`roleid`; nome em `username` | `host`/`status` |
| 6.4 | parâmetro `username` | header Bearer | roles/`roleid` | `host`/`status` |
| 7.0 e 7.4 | parâmetro `username` | header Bearer | roles/`roleid` | `name`/`operating_mode` |

Os resultados de Super Admins e proxies são normalizados para schemas comuns. A matriz testa as fronteiras que mudam contrato; ela não promete que todo endpoint opcional estará disponível para toda combinação de versão, edição e permissão. Falhas desse tipo entram como warnings estruturados, e autenticação/MFA só é consultada em 7.0+ sem converter “indisponível” em falso negativo.

### 2. Descoberta de Cluster HA (`get_active_node_hostid`)
Extrair dados do nó errado em um cluster Active-Standby gera métricas vazias (gráficos flatlines).
* **Como funciona:** O sistema executa um "Fallback Triplo":
  1. Tenta usar a API nativa `hanode.get` (disponível no Zabbix 6.0+).
  2. Se falhar, busca itens internos críticos (`zabbix[process,poller`) e avalia qual HostID teve o relógio (`clock`) de coleta mais recente nos últimos minutos.
  3. Em último caso, procura por um host estático nomeado `"Zabbix server"`.

### 3. Coleta e Estratégia de Amostragem (Sampling)
A API do Zabbix pode retornar milhões de linhas. Enviar isso para uma IA causaria *Timeout* ou superaria a "Janela de Contexto" (Token Limit).
* **Solução Implementada:** O método `collect_data()` agrupa os problemas. Em vez de enviar todos os itens de delay baixo, envia apenas os Top N (controlado via GUI).
* **Cálculo de Gráficos (Trends):** Para desenhar os gráficos na IA, precisamos de dados históricos. Buscar 15 pontos recentes gera um gráfico "míope" (ex: últimos 15 minutos). A aplicação busca **N pontos (ex: 500)** no Zabbix e usa indexação reversa matemática (`history_data[0::step][:15]`) para espaçar os pontos temporalmente, criando tendências que representam horas ou dias condensados em apenas 15 valores no JSON.
* **Fases independentes:** hosts, itens, templates, saúde interna, banco, higiene/riscos, governança e métricas do SO são coletados com progresso monotônico e cancelamento entre fases e loops. Um endpoint opcional indisponível ou sem permissão gera um warning estruturado e mantém os resultados das demais fases; perda de transporte e cancelamento continuam interrompendo a coleta.
* **Métricas e custo:** o parser `parse_update_interval()` aceita somente intervalos simples com sufixos (`s`, `m`, `h`, `d`, `w`). Só `0 < delay < 30` é agressivo; trapper/`delay=0`, macros e agendas ficam separados como não classificáveis. Itens não suportados preservam chave e `error`; LLD usa `discoveryrule.get` (nunca `drule.get`). A coleta expõe `authentication_summary` e MFA apenas em Zabbix 7.0+ quando API/permissão permitem, e registra a indisponibilidade sem inferir “MFA desligado”. Proxies têm modo, estado, versão normalizada e lag em segundos. Consultas que só precisam de total usam `countOutput`; `_collection_metadata.api_call_count` permite observar o número de chamadas.
* **Schema e metadados:** todas as chaves de saída possuem valores vazios iniciais, permitindo distinguir “sem dados” de chave ausente. `_collection_metadata` registra `schema_version`, UTC da coleta, versão do Zabbix, status de anonimização, contagem de chamadas e a lista de warnings de compatibilidade/coleta. A descoberta de hosts de infraestrutura é compartilhada pelas fases de templates e banco.

### 4. Geração do Relatório via IA
* O `Controller` consolida o JSON do Zabbix, as instruções customizadas capturadas no snapshot e os arquivos de texto anexados; o coletor de SO produz um formato recomendado, mas o fluxo não depende de um nome fixo.
* O `ai_api.py` empacota isso no `report_template.txt`.
* **Fronteira de dados:** o controlador usa somente `Path.name` nos anexos e limita a leitura a 10 arquivos, 1 MiB por arquivo e 5 MiB no total; truncamentos e rejeições são avisados. JSON importado/cache é limitado a 10 MiB, exige objeto na raiz e valida a versão de schema quando os metadados existem.
* **Resistência a prompt injection:** JSON, evidências e instruções adicionais recebem delimitadores explícitos. O system prompt comum instrui os provedores a tratar nomes, métricas, logs e anexos como dados não confiáveis, nunca como instruções de sistema.
* **Contrato de stream:** cada transporte emite `AIStreamEvent` de texto e exatamente um evento `final`. Gemini ignora `chunk.text` vazio; OpenAI (`finish_reason`), Anthropic (`stop_reason`) e Ollama (`done_reason`) preservam o motivo de término. `length`, `max_tokens` e erros tornam o relatório parcial. O controller só registra sucesso após um `final` válido; caso contrário, conserva o texto exibido, avisa o usuário e indica a regeneração pelo cache quando aplicável. Os SDKs têm timeout explícito (Gemini recebe milissegundos em `HttpOptions`) e Anthropic usa limite configurável, padrão 8192.
* **Retries sem duplicação:** `_stream_provider_events()` aplica no máximo três tentativas totais a falhas de conexão, `408`, `429` e `5xx`, usando `Retry-After` quando presente e backoff exponencial nos demais casos. OpenAI e Anthropic recebem `max_retries=0`, e o Gemini recebe uma única tentativa interna, deixando uma só política no aplicativo. O retry é permitido apenas enquanto nenhum texto foi emitido; depois do primeiro trecho, qualquer quebra gera `final(error, partial=True)` sem reiniciar o stream. A espera entre tentativas continua observando o cancelamento da operação.
* **Descoberta e estado de modelos:** Anthropic, assim como os demais provedores por API, consulta a listagem do SDK (`client.models.list()`). Se apenas essa chamada falhar, `AIClient` devolve uma lista curta de fallback e expõe um warning que o controller envia ao log. O controller atribui um ID monotônico a cada carregamento e ignora resposta cuja conta/provedor já foi substituído. A GUI mantém `idle`, `loading`, `ready` e `error` separados de `_model_values`; mensagens visuais nunca entram nos valores do combobox nem no `AIConfig`. Antes da auditoria, `AIConfig.validation_error()` valida provedor, modo de autenticação, credencial e, no modo API, um modelo selecionável. O modo CLI permite modelo vazio para conservar o default da CLI.

* **Risco de nuvem:** API e CLI de Claude/OpenAI/Gemini podem transmitir JSON, instruções e anexos aos serviços remotos do provedor; “CLI local” descreve o binário e a autenticação, não o local de inferência. Ollama só mantém o processamento sob controle local quando a URL aponta para infraestrutura controlada. A anonimização remove valores de chaves sensíveis e pseudonimiza IPs, inclusive em texto livre, mas não garante remover nomes, e-mails ou contexto de negócio. A confirmação obrigatória cobre o envio remoto com anonimização desativada; a avaliação de política, retenção e LGPD continua sendo responsabilidade do operador.

### 5. Persistência, paths, salvamento e cache versionado

* **Separação de paths:** `resource_path()` nunca é usado para dados mutáveis. `get_app_paths()` retorna `AppPaths` com diretórios nativos de configuração, cache e dados do usuário para `auditoria-zabbix`, independentes do `cwd`. Os diretórios são criados sob demanda com modo `0700` quando suportado; o diretório de dados é o default dos diálogos de salvar/abrir.
* **Escrita atômica:** `atomic_write_text()` cria um temporário `0600` no mesmo diretório do destino, grava, executa `flush()` e `fsync()`, troca com `os.replace()`, restringe o destino a `0600` e sincroniza o diretório. Falha antes da troca mantém o arquivo anterior e remove o temporário. Settings, cache, coleta JSON e saídas diretas de log/Markdown/TXT usam esse helper.
* **Settings:** `SettingsStore` aceita somente campos conhecidos, normaliza inteiros/booleanos/escolhas dentro de limites e remove chaves sensíveis/desconhecidas. Erros de JSON ou tipo são devolvidos como warnings para a fila de log da GUI, que usa defaults. `ai_accounts` tem formato e quantidade limitados; chaves de API permanecem vazias no JSON e são recuperadas do keyring.
* **Quando há gravação:** settings são salvos antes de testar/iniciar fluxos e ao confirmar mudanças de contas, estilo ou diretórios escolhidos; não existe autosave por tecla nem garantia de salvar uma edição se a janela for apenas fechada. Cada coleta nova tenta atualizar o cache automaticamente. Relatório e logs só são persistidos quando o usuário escolhe explicitamente **Salvar/Exportar Relatório** ou **Salvar Logs**.
* **Envelope de cache:** `CacheStore` grava `cache_schema_version`, `created_at_utc`, `server.name`, `server.fingerprint`, `zabbix_version`, `anonymized`, `warnings` e `data`. O fingerprint deriva somente de esquema/host/porta/path normalizados, nunca de usuário, senha ou query. O loader limita tamanho, valida o envelope e também extrai `data` quando um cache versionado é escolhido manualmente como coleta.
* **Reutilização:** o handler cria `AuditRequest(use_cache=True)`; `Controller.start_audit(request)` carrega e valida o registro ainda na thread principal, registra origem/data/versão/anonimização e passa o mesmo snapshot à worker. Servidor diferente, opção de anonimização divergente ou fingerprint desconhecido chama `MainView.confirm_cache_mismatch()` antes de reservar a operação.
* **Migração:** na ausência do novo arquivo, `SettingsStore` e `CacheStore` procuram os nomes legados no diretório de execução. A migração só publica o novo arquivo após escrita atômica; o original não é removido. Credenciais legadas são excluídas do novo JSON e migradas para o keyring. Como cache legado não registra origem confiável, recebe fingerprint desconhecido e exige confirmação na primeira reutilização.

### 6. Coleta sem IA e geração a partir de arquivo

Três botões relacionados em `control_frame` de `main_view.py`: **"🔄 Regerar (Apenas IA)"** (reusa o cache versionado no diretório de cache do usuário), **"📥 Apenas Coleta"** (só extrai e salva, sem IA) e **"📂 Iniciar de Coleta"** (gera o relatório a partir de um `.json` de coleta escolhido pelo usuário, sem tocar no Zabbix). Os três existem para permitir separar totalmente a etapa de coleta da etapa de geração via IA — útil para arquivar evidências, revisar a coleta antes de gastar tokens, ou coletar em um ambiente e gerar o relatório em outro.

* **Handler “Apenas Coleta” (GUI):** abre `filedialog.asksaveasfilename`, lembra `settings["last_collect_dir"]`, cria um `CollectionRequest` imutável na thread principal e chama `Controller.start_collection_only(request)`.
* **`Controller.start_collection_only(request)`:** valida o snapshot e o transporte, reserva um `OperationContext` novo e roda `run_collection_only_flow` em uma thread daemon. Não há evento global para limpar/reutilizar.
* **`Controller.run_collection_only_flow(request, operation)`:** chama `_collect_zabbix_data(...)`, que também tenta atualizar o cache automático, e grava atomicamente o resultado no destino do request (JSON indentado para leitura humana). Não instancia `AIClient` nem troca para a aba do relatório.
* **Handler “Iniciar de Coleta” (GUI):** abre `filedialog.askopenfilename`, cria `AuditRequest(data_file=...)` e chama `Controller.start_audit(request)`.
* **`Controller.start_audit(request)` / `run_audit_flow(request, operation, ...)`:** com `data_file`, pula conexão e credenciais do Zabbix, limita/valida o objeto JSON e segue para a IA. `use_cache` reutiliza o registro previamente carregado e confirmado na thread principal. A GUI constrói esses modos separadamente.
* **`Controller._collect_zabbix_data(...)`:** helper privado extraído de `run_audit_flow` — conecta, autentica, chama `zabbix.collect_data()`, anonimiza se `anonimizar` estiver ativo e envia os dados ao `CacheStore`, que grava o envelope versionado. É compartilhado pelos fluxos que efetivamente coletam do Zabbix (`run_audit_flow` quando `use_cache=False` e `data_file` é `None`, e `run_collection_only_flow`), então qualquer mudança na lógica de coleta/anonimização vale para ambos automaticamente.
* **`Controller._validate_zabbix_credentials(...)`:** helper privado com a validação de token/usuário-senha, também compartilhado pelos fluxos que tocam o Zabbix (pulado quando `data_file` é usado).

### 7. Robustez da coleta de métricas internas/SO/DB (`api/zabbix_api.py`)

Auditorias reais mostraram várias chaves do `audit_data` chegando vazias ou omitidas no JSON mesmo quando o Zabbix tinha o dado — quase sempre por o código descartar o que a API já retornava, não por falta do dado no Zabbix. Padrões a preservar ao tocar em `collect_data()`:

* **`ZabbixClient._fetch_trend_values(itemid, value_type, history_limit, sample_limit)`**: tenta `history.get` primeiro; se vier vazio (comum quando o ambiente reduz a retenção de `history` de itens internos para economizar disco, mantendo só `trends`), cai para `trend.get` (**singular** — `trends.get` não existe na API do Zabbix e retorna `"Incorrect API 'trends'"`; já aconteceu uma vez). Usado por `zabbix_server_health_metrics`, `database_health_metrics`, `nvps` e `zabbix_server_os_metrics` — qualquer nova métrica histórica deve reusar este helper em vez de chamar `history.get` isolado.
* **Whitelists de chave devem ser prefixos amplos, não uma lista fechada de nomes.** `zabbix_server_health_metrics` usava `["zabbix[process,poller", "zabbix[process,history", ...]` e descartava silenciosamente itens reais como `zabbix[process,trapper,...]`/`zabbix[process,unreachable poller,...]` que o Zabbix retornava. Hoje usa o prefixo genérico `"zabbix[process,"` (cobre qualquer tipo de processo interno) + `"zabbix[queue"`/`"zabbix[wcache"`/`"zabbix[rcache"`/`"zabbix[vcache"`/`"zabbix[vps"`. O mesmo valia para `database_health_metrics` (`critical_db_terms` não incluía `tmp`/`table`/`disk`/`innodb`, descartando ex. `mysql.status[Created_tmp_disk_tables]`).
* **`zabbix_server_os_metrics`:** busca CPU/swap/memória/disk I/O do host ativo por **categoria separada** (uma chamada `item.get` por categoria: `system.cpu`, `system.swap`, `vm.memory`, `vfs.dev`), não uma busca única fatiada por `sample_limit` — senão dezenas de itens de disco por dispositivo (descobertos via LLD) engolem o "slice" e deixam CPU/swap/memória de fora. O prefixo é `vfs.dev` (não `vfs.dev.io`): templates mais novos usam `vfs.dev.read.await`/`vfs.dev.write.await` em vez da chave antiga `vfs.dev.io[...]`.
* **Toda chave de `audit_data` que alimenta o prompt deve ser inicializada com um valor "vazio" padrão (`[]`/`0`) *antes* do `try`, nunca só dentro de um `if resultado:`.** Um resultado vazio (sem proxies, sem manutenções ativas) e uma falha de coleta pareciam idênticos no JSON final (chave ausente) antes desse ajuste — `proxies_details`, `super_admin_users_samples/count`, `global_scripts_samples/count`, `database_health_metrics` e `zabbix_server_health_metrics` seguem esse padrão.
* **Coletores adicionados que só existiam referenciados no prompt, nunca implementados:** `active_mediatypes_samples/count` (`mediatype.get`), `business_services_count/samples` (`service.get`), `active_maintenances_samples/count` (`maintenance.get`, filtrado por `active_since <= now <= active_till` — só a janela geral de vigência, não a recorrência diária/semanal interna).
* **`nvps`:** usar `filter` exato `zabbix[wcache,values]`, nunca `search` (`"zabbix[wcache,values"` batia por LIKE em `zabbix[wcache,values,float]`/`,uint`/`,str` também, e a API não garante ordem — `[0]` podia pegar um sub-tipo zerado em vez do agregado).

### 8. Modo CLI local dos provedores de IA (`api/ai_cli_client.py`)

Alternativa ao SDK: quando a conta tem `auth_mode == "cli"`, `AIClient.generate_audit_report()` não chama nenhum SDK — delega para `ai_cli_client.generate_via_cli(provider, prompt, model_override)`, que roda o binário da CLI oficial do provedor (`claude`/`codex`/`gemini`) como subprocesso.

* **Por que não SDK/API key:** o objetivo é usar a assinatura (Claude Pro/Max, ChatGPT Plus/Pro, Gemini Advanced) do usuário, não cobrança por token. Isso é feito chamando a própria CLI oficial em modo headless — não reimplementando o fluxo OAuth dela (o que violaria os Termos de Uso de cada provedor e dependeria de Client IDs não documentados).
* **Sandboxing obrigatório:** as três CLIs são agentes de codificação por padrão (têm acesso a shell/arquivos). `generate_via_cli` sempre roda com ferramentas desabilitadas ou sandbox somente-leitura (`--allowedTools ""` no `claude`, `--sandbox read-only` no `codex`, `--approval-mode plan` no `gemini`) e com `cwd` em um diretório temporário isolado (removido em `finally`), para que a CLI se comporte só como motor de texto.
* **Entrada via stdin:** o prompt completo (JSON de auditoria + template) é enviado via stdin do subprocesso, nunca como argumento de linha de comando — evita estourar limites de tamanho de argumento do SO com JSONs grandes.
* **Adaptadores e detecção de capacidade:** Claude, Codex e Gemini têm adaptadores separados para comando, entrada e parsing. Antes de cada geração, uma sonda curta executa `claude --help`, `codex exec --help` ou `gemini --help`. Falha/timeout da sonda desativa formatos estruturados; nenhuma flag JSON/JSONL é presumida universalmente.
* **Streaming confirmado:** Claude só usa `stream-json` quando o help anuncia também `--verbose` e `--include-partial-messages`; o parser aceita exclusivamente envelopes `stream_event`/`content_block_delta`/`text_delta` cobertos por fixture. Codex só acrescenta `exec --json` quando anunciado e aceita exclusivamente `item.completed` de `agent_message`, também coberto por fixture. Eventos de metadados e transcrições finais repetidas são ignorados para não duplicar conteúdo.
* **Fallbacks:** Gemini permanece deliberadamente não incremental por não haver schema JSONL estável validado; Claude/Gemini só pedem JSON final se a versão anunciar `--output-format json`. Sem isso, usam texto final. Codex conserva o arquivo de última mensagem via `-o` como fallback e não o reapresenta quando eventos JSONL reconhecidos já emitiram texto. Todos os caminhos terminam no mesmo `AIStreamEvent.final` do contrato comum.
* **Cancelamento e timeout:** todos os comandos, inclusive o `taskkill` auxiliar do Windows, usam `Popen`; não há caminho bloqueante baseado em `subprocess.run()`. O fallback final consulta `communicate()` em intervalos curtos, enquanto o caminho incremental drena stdout/stderr em leitores dedicados e entrega linhas por fila. O callback segue `OperationContext.is_cancelled` → `Controller` → `AIClient.generate_audit_report()` → `generate_via_cli()`. Em POSIX, a CLI inicia uma nova sessão e todo o grupo recebe `SIGTERM`, seguido de `SIGKILL` após a tolerância; no Windows, cria um novo grupo e inicia `taskkill /T /F` com espera limitada para encerrar a árvore, caindo para `terminate()`/`kill()` se o auxiliar falhar ou exceder o prazo. Cancelamento, timeout, binário ausente e retorno não zero têm exceções distintas, e o diretório temporário é removido em todos esses caminhos.
* **Privacidade de erros:** stdout e stderr são drenados para evitar bloqueio, mas nunca são copiados integralmente para logs ou exceções, pois podem conter o prompt e dados da auditoria.

### 9. Renderização de Gráficos e Exportação (`core/report_exporter.py` + `core/chart_renderer.py`)

A IA gera gráficos `xychart-beta` e `pie` do Mermaid.js dentro de blocos ```` ```mermaid ````. Em vez de interpretar essa sintaxe via um motor JS real (o que exigiria um browser), o app faz o parsing diretamente em Python.

* **Fronteira GUI/worker:** `MainView.save_report_clicked()` lê todos os widgets na thread principal e cria `ReportStyle` e `ReportMetadata` imutáveis. A worker recebe somente strings e esses snapshots; ela instancia `ReportExporter` com callbacks Python de log/progresso, que publicam eventos na fila da GUI sem acessar Tk diretamente.
* **O Fluxo de Renderização (`ReportExporter._render_mermaid_charts` → `core/chart_renderer.py`)**:
  1. `chart_renderer.MERMAID_CODE_FENCE_RE` varre o Markdown extraindo blocos ```` ```mermaid ````.
  2. `parse_pie()` tenta primeiro a gramática própria de pizza. Somente blocos que não são `pie` passam por `normalize_mermaid()`, que corrige alucinações de `xychart-beta` e força Linha/Barra. Assim, a normalização de séries nunca altera um `pie`.
  3. `parse_xychart()` extrai título, eixos e múltiplas séries. Cada token inválido, vazio ou `N/A` vira `NaN`, preservando os demais pontos; uma série totalmente inválida permanece diagnosticável e gera warning. Na renderização, rótulos excedentes são truncados e os ausentes recebem índices estáveis. `parse_pie()` aceita apenas fatias finitas, não negativas e com soma positiva. Bloco não suportado ou inválido permanece como código no documento final.
  4. `render_chart()` desenha linhas, barras agrupadas ou `ax.pie()` com a **API orientada a objetos do matplotlib** (`Figure` + `FigureCanvasAgg`, nunca `pyplot`) e salva um PNG.
  5. O bloco de texto markdown do Mermaid é substituído localmente por uma tag de imagem `![Gráfico N](caminho/absoluto/chart_N.png)`.
* **A Geração Final (`ReportExporter.export`)**:
  * Para **Markdown (.md)** e **texto (.txt)**, o conteúdo é gravado por `atomic_write_text()`, sem criar diretório de conversão.
  * Para **Word (.docx)** e **OpenDocument (.odt)**, o Markdown manipulado (com links para os PNGs) é passado direto para `pypandoc`, sem etapa extra.
  * Para **PDF**, o Markdown é convertido para markup **Typst** via `pypandoc.convert_text(..., 'typst', ...)` (requer Pandoc ≥ 3.1.7). Os caminhos de imagem, absolutos no Markdown, são reescritos para relativos ao diretório dos gráficos (caminhos em `.typ` são resolvidos relativos ao próprio arquivo `.typ`, não ao `root` do compilador). O corpo Typst é combinado com `templates/report_template.typ` (capa, margens, numeração de página) e compilado direto para PDF via `typst.compile(..., root=<diretório dos PNGs>)` — sem HTML intermediário, sem browser.
  * `core.pandoc_runtime.load_pandoc()` diferencia os ambientes: no PyInstaller, define `PYPANDOC_PANDOC` para `pandoc/pandoc[.exe]`, valida o binário incorporado e nunca chama `download_pandoc`; por fonte, procura primeiro o binário persistido no diretório de dados e só permite download após `MainView.confirm_pandoc_download()`. O download usa temporário isolado e publica o binário no diretório privado de dados do usuário.
  * DOCX, ODT e PDF compartilham um diretório de trabalho exclusivo criado pelo exportador. Um `finally` remove esse diretório depois de sucesso ou exceção; a fronteira da GUI mostra diálogo de sucesso ou erro para todos os cinco formatos e colore o log conforme a severidade.
* **Prévia sem corrida:** `StyleSettingsWindow.update_preview()` aplica debounce com `after_cancel()` exclusivamente na main thread. Cada geração recebe ID e arquivo PNG próprios; workers publicam o resultado em uma fila Python, sem chamar `after()` ou widgets. O consumidor Tk aceita apenas o ID atual, e o fechamento cancela callbacks de debounce/polling antes de remover o diretório temporário.
* **Testes do pipeline real:** `tests/test_chart_renderer.py` cobre diferenças de rótulos/valores, `NaN`, múltiplas séries e `pie`; `tests/test_report_exporter.py` cobre gravação direta, callbacks, consentimento explícito, formato inválido, pizza válida/inválida, sucesso/falha e limpeza. `tests/test_pandoc_runtime.py` prova que source sem consentimento e executável nunca baixam; `tests/test_release_packaging.py` verifica requisitos, spec e ordem do workflow. `tests/test_pdf_pipeline.py` chama `ReportExporter` de ponta a ponta com templates reais, Pandoc, Typst e Mermaid representativo.

### 10. Layout da aba "⚙️ Configurações" (dashboard)

* **Janela inicial `1500x760`** (`MainView.__init__`) — largura aumentada para caber os 5 botões de ação + combobox de modelo em `control_frame` sem cortar.
* **A aba inteira é um `ttkbootstrap.scrolled.ScrolledFrame`** (`autohide=True`), não um `ttk.Frame` puro. Ao adicionar a um `Notebook`, o container precisa ser adicionado, não o frame de conteúdo: `notebook.add(config_frame.container, ...)` — ver docstring da própria classe. Existe para não cortar campos quando janela/DPI/fonte deixam o conteúdo mais alto que a área visível da aba.
* **"Dados do Analista / Empresa" (esquerda) e "Instruções Customizadas para a IA" (direita) terminam na mesma altura por coincidência ajustada, não por layout automático.** As duas colunas (`left_col`/`right_col`) são pilhas `pack` independentes — não há como o `pack` sincronizar a altura de duas frames em colunas diferentes nativamente. A tentativa óbvia (grid de 2 colunas x 3 linhas com a última linha compartilhada) **foi revertida**: fazia `analyst_frame` esticar (`sticky="nsew"`) para preencher a altura da linha, mudando sua aparência original — o pedido era só encurtar Instruções, sem tocar em Analista. A solução final é a mais simples que não mexe em mais nada: `inst_frame` não usa mais `expand=True` (só `fill=X`, igual às outras LabelFrames), e o `ScrolledText` interno tem `height=20` (linhas) fixo, calibrado empiricamente para que a base bata perto da base de `analyst_frame` nesta janela. **Isso não é dinâmico** — se o número de campos de qualquer uma das duas LabelFrames mudar, o valor `height=20` precisa ser recalibrado à mão (relançar `python main.py` e comparar visualmente, ou instrumentar com `winfo_rooty()`/`winfo_height()` como no diagnóstico original). Uma tentativa de calcular isso dinamicamente via bind em `<Configure>` + `winfo_rooty()` foi tentada e descartada por não convergir de forma confiável no primeiro layout.

### 11. Contas, keyring e feedback visual

* `ManageAccountsWindow` exige confirmação quando o nome de destino já existe e antes de remover uma conta. A alteração ocorre sobre uma cópia recuperável; falha de `save_settings()` restaura o dicionário anterior.
* `MainView.save_settings()` publica primeiro o JSON sem segredos. Só depois grava credenciais no keyring. Em renomeação ou remoção, `delete_ai_account_credential()` é chamado depois da persistência bem-sucedida, usando o nome antigo; ausência da credencial é idempotente e outras falhas são avisadas no log.
* O consumidor da fila aplica as tags `info`, `warning`, `danger` e `success` ao `ScrolledText`. Workers de exportação e operações publicam apenas `(mensagem, severidade)` e diálogos como eventos Python.

---

## 🔌 Como Extender e Modificar

### 1. Adicionando um Novo Provedor de IA
Para adicionar um provedor como Groq, Cohere, etc:
1. Adicione o nome a `SUPPORTED_AI_PROVIDERS` em `core/run_config.py` e à configuração inicial de contas em `MainView`.
2. Em `AIClient`, implemente descoberta de modelos e um transporte que produza `AIStreamEvent.text_chunk(...)` e exatamente um `AIStreamEvent.final(...)`, preservando motivo de término, erro e parcialidade.
3. Passe o mesmo system prompt neutro de `api/ai_prompts.py`, timeout explícito, cancelamento e política de retry sem repetir depois do primeiro texto.
4. Adicione testes de modelo, conclusão normal, limite de tokens, falha parcial e cancelamento. Se houver modo CLI, crie um adaptador próprio e só habilite JSON/JSONL após sondar a versão instalada.

### 2. Coletando Novas Métricas do Zabbix
Deseja coletar o tempo médio de resposta de Pings, por exemplo?
1. Modifique a função `collect_data()` em `api/zabbix_api.py`.
2. Adicione uma nova chave no dicionário local: `audit_data["nova_metrica"] = dados_buscados`.
3. **Obrigatório:** Vá no arquivo `prompts/report_template.txt` e adicione instruções para a IA analisar a sua nova métrica. Exemplo: *"Analise a seção `nova_metrica` e julgue se a latência está alta"*. Se não fizer isso, a IA frequentemente ignorará o dado solto no JSON.

### 3. Alterando as Ferramentas Nativas Docker (Wayland / GUI)
O projeto utiliza Tkinter, que requer um servidor gráfico. `exec_wayland.fish` encaminha X11/XWayland com `XAUTHORITY` e monta o socket Wayland somente quando ele existe. O padrão usa UID/GID do usuário, volume de dados explícito, rede bridge e nenhum overlay do código; `--host-network` é uma opção consciente. No Windows, o caminho suportado de distribuição é o executável PyInstaller produzido pelo workflow de release, não um contêiner GUI.

---

## ⚠️ Pontos Críticos de Atenção (Gotchas)

- **Manipulação de Interface Fora da Main Thread:** Workers nunca podem chamar widgets, variáveis Tk nem `after()`. Devem usar `self.view.log()`, `update_progress()` e os demais publicadores, que colocam eventos Python na fila; somente o consumidor agendado na main thread toca o Tk.
- **Mudanças no google-genai:** A API oficial do Gemini mudou em 2025 (`google-generativeai` descontinuado para `google-genai`). Mantenha os `requirements.txt` atualizados utilizando os objetos `Client` e `types.GenerateContentConfig` implementados atualmente na `ai_api.py`.
- **Limpeza de Temp:** DOCX, ODT e PDF criam imagens e fontes Typst em um diretório de trabalho. O `finally` de `ReportExporter.export()` deve continuar removendo esse diretório com `shutil.rmtree()` para cobrir tanto sucesso quanto falha e evitar esgotamento de disco (inodes).
- **Pandoc empacotado é obrigatório e offline:** builds devem executar `tools/prepare_pandoc.py` antes do PyInstaller. Não reintroduza `download_pandoc()` em `ReportExporter` nem em qualquer caminho `sys.frozen`; um bundle ausente/antigo deve falhar com orientação de reinstalação. Downloads por código-fonte exigem consentimento explícito e ficam no diretório de dados, nunca no repositório.
- **Nunca use `claude --bare` em `ai_cli_client.py`:** essa flag desativa explicitamente a leitura de OAuth/keychain ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper... OAuth and keychain are never read") — quebraria exatamente a autenticação via assinatura que o modo CLI local depende. Reduções de overhead da CLI devem vir do `cwd` isolado (diretório temp sem `CLAUDE.md`/config de projeto por perto), não dessa flag.
- **Nunca importe `matplotlib.pyplot` em `chart_renderer.py`:** a renderização de gráficos roda em threads de background (tanto na exportação de relatório quanto na prévia de estilos); `pyplot` mantém estado global de figuras/backend que pode colidir com o event loop do Tkinter na main thread. Use sempre `matplotlib.figure.Figure` + `matplotlib.backends.backend_agg.FigureCanvasAgg` diretamente.
- **Fontes em `templates/report_template.typ` precisam estar genuinamente embutidas no wheel do `typst`, não só instaladas na sua máquina.** O Typst resolve fonte ausente com *fallback silencioso* (sem erro/aviso), então um nome de fonte "errado" ainda compila um PDF válido — só que com a fonte errada. Isso já aconteceu: o template usava `"DejaVu Sans"`, que só "funcionava" porque a máquina de dev tinha essa fonte instalada via fontconfig; ela não vem no wheel do `typst` (que só embute `DejaVu Sans Mono`, `Libertinus Serif` e `New Computer Modern`), então em Docker/Windows sem essa fonte instalada o PDF saía com uma fonte diferente da pretendida — o oposto do objetivo de portabilidade desta seção. Antes de trocar a fonte do template, confirme com `typst.Fonts(include_system_fonts=False, include_embedded_fonts=True).families()` que o nome escolhido está na lista.
