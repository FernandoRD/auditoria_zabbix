# 🛠️ Referência Técnica: Auditoria Inteligente de Zabbix

Este documento descreve o funcionamento interno, a arquitetura e as decisões técnicas do projeto **Auditoria Inteligente de Zabbix**. Seu objetivo é servir como um guia para desenvolvedores que desejam manter, refatorar ou expandir a aplicação.

---

## 🏗️ Arquitetura do Projeto

A aplicação segue uma arquitetura orientada a componentes, vagamente baseada no padrão **MVC (Model-View-Controller)**, para separar a interface gráfica das lógicas de negócio e comunicação com APIs externas.

### Estrutura de Diretórios e Módulos

- **`/gui` (View)**: Módulo responsável pela interface gráfica construída com `ttkbootstrap` (um wrapper moderno para `Tkinter`).
  - `main_view.py`: Janela principal, abas, barras de progresso e motor de exportação de relatórios.
  - `manage_accounts_view.py`, `style_settings_view.py`, etc.: Componentização das janelas secundárias (Modais) para evitar inchaço no arquivo principal.
- **`/api` (Integrações / Model)**:
  - `zabbix_api.py`: Classe `ZabbixClient`. Gerencia o protocolo JSON-RPC, autenticação nativa e as regras de negócio de extração de dados.
  - `ai_api.py`: Classe `AIClient`. Abstrai múltiplos provedores de LLMs (Google Gemini, OpenAI, Anthropic, Ollama) entregando uma interface de consumo unificada via *Streams*, com suporte a dois modos de autenticação por conta (`auth_mode`): `api_key` (SDK oficial) ou `cli` (delega para `ai_cli_client.py`).
  - `ai_cli_client.py`: Funções puras de montagem de comando (`build_cli_command`, `build_cli_input_text`, `extract_cli_json_text`, `cli_binary_status`) e o orquestrador `generate_via_cli()`, que roda `claude`/`codex`/`gemini` como subprocesso sandboxed. Ver seção 4.1.
- **`/core` (Controller)**:
  - `controller.py`: Classe `Controller`. Orquestra as ações do usuário. Gerencia as *Threads* (para evitar o congelamento da interface gráfica) e controla o estado da GUI (habilitar/desabilitar botões, atualizar barra de progresso).
  - `chart_renderer.py`: Parsing puro da sintaxe `xychart-beta` do Mermaid.js e renderização em PNG via matplotlib (Agg). Ver seção 5.
- **`/prompts`**:
  - `report_template.txt`: O *System Prompt* central. Define a persona, a estrutura de tópicos exigida e as regras de formatação (ex: obrigatoriedade do uso de Mermaid.js `xychart-beta`).
- **`/templates`**:
  - `report_template.docx`: documento de referência do Pandoc para exportação Word.
  - `report_template.typ`: template Typst (capa, margens, numeração) para exportação PDF.
- **`/tests`**:
  - Testes unitários (`unittest`, stdlib — sem dependência de teste adicional) para `ai_cli_client.py`, o modo CLI de `ai_api.py` e o wiring de `auth_mode` em `controller.py`. Rodar com `python3 -m unittest discover -s tests -v`.

---

## ⚙️ Fluxos de Funcionamento Interno

### 1. Autenticação e Adaptação de Versão (Zabbix API)
O Zabbix mudou seu método de autenticação da versão 6.4 em diante. O método genérico baseado no *payload* (`"auth": "token"`) foi preterido em favor de cabeçalhos HTTP (`Authorization: Bearer token`).
* **Como funciona:** O método `discover_version()` faz uma chamada não autenticada para `apiinfo.version`. O Python faz o *parse* da string resultante e ajusta a flag `self.use_header_auth`. Todas as chamadas subsequentes no método `api_call` injetam o token no local correto dinamicamente.

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

### 4. Geração do Relatório via IA
* O `Controller` consolida o JSON do Zabbix, as instruções customizadas da tela e arquivos de texto anexados do SO (`evidencias_os.txt`).
* O `ai_api.py` empacota isso no `report_template.txt`.
* **Stream Mode:** O SDK da IA correspondente é chamado com `stream=True`. O `yield` do Python retorna os pedaços (*chunks*) do texto assim que chegam. O método `append_report_chunk` da GUI usa o `self.after(0, ...)` do Tkinter para desenhar essas letras na interface em tempo real de forma thread-safe.

### 3.1. Coleta sem IA e geração a partir de arquivo (`Controller.start_collection_only` / `start_audit(data_file=...)`)

Três botões relacionados em `control_frame` de `main_view.py`: **"🔄 Regerar (Apenas IA)"** (reusa `last_audit_cache.json`), **"📥 Apenas Coleta"** (só extrai e salva, sem IA) e **"📂 Iniciar de Coleta"** (gera o relatório a partir de um `.json` de coleta escolhido pelo usuário, sem tocar no Zabbix). Os três existem para permitir separar totalmente a etapa de coleta da etapa de geração via IA — útil para arquivar evidências, revisar a coleta antes de gastar tokens, ou coletar em um ambiente e gerar o relatório em outro.

* **`collect_only_clicked` (GUI):** valida que a URL do Zabbix foi preenchida, abre `filedialog.asksaveasfilename` para o usuário escolher onde salvar o JSON (lembra o último diretório em `settings["last_collect_dir"]`), e chama `controller.start_collection_only(file_path)`.
* **`Controller.start_collection_only(file_path)`:** limpa o `cancel_event`, desabilita a UI e roda `run_collection_only_flow` em uma thread daemon — mesmo padrão de `start_audit`.
* **`Controller.run_collection_only_flow(file_path)`:** valida URL/credenciais do Zabbix, chama `_collect_zabbix_data(...)` e grava o resultado em `file_path` (JSON com `indent=2`, para leitura humana — diferente do cache interno, que é compacto). Não instancia `AIClient` nem troca de aba.
* **`start_from_file_clicked` (GUI):** abre `filedialog.askopenfilename` para escolher qualquer `.json` de coleta (reaproveita `settings["last_collect_dir"]`) e chama `controller.start_audit(data_file=file_path)`.
* **`Controller.start_audit(use_cache=False, data_file=None)` / `run_audit_flow(use_cache, data_file=None)`:** quando `data_file` é passado, pula totalmente a conexão/validação de credenciais do Zabbix (só exige provedor/modelo de IA configurados), carrega o JSON diretamente de `data_file` e segue para a geração do relatório como o fluxo normal. `data_file` tem prioridade sobre `use_cache` (ambos são mutuamente exclusivos na prática, já que a GUI só passa um ou outro).
* **`Controller._collect_zabbix_data(...)`:** helper privado extraído de `run_audit_flow` — conecta, autentica, chama `zabbix.collect_data()`, anonimiza se `anonimizar` estiver ativo e grava `last_audit_cache.json`. É compartilhado pelos fluxos que efetivamente coletam do Zabbix (`run_audit_flow` quando `use_cache=False` e `data_file` é `None`, e `run_collection_only_flow`), então qualquer mudança na lógica de coleta/anonimização vale para ambos automaticamente.
* **`Controller._validate_zabbix_credentials(...)`:** helper privado com a validação de token/usuário-senha, também compartilhado pelos fluxos que tocam o Zabbix (pulado quando `data_file` é usado).

### 3.2. Robustez da coleta de métricas internas/SO/DB (`api/zabbix_api.py`)

Auditorias reais mostraram várias chaves do `audit_data` chegando vazias ou omitidas no JSON mesmo quando o Zabbix tinha o dado — quase sempre por o código descartar o que a API já retornava, não por falta do dado no Zabbix. Padrões a preservar ao tocar em `collect_data()`:

* **`Controller._fetch_trend_values(itemid, value_type, history_limit, sample_limit)`** (`api/zabbix_api.py`): tenta `history.get` primeiro; se vier vazio (comum quando o ambiente reduz a retenção de `history` de itens internos para economizar disco, mantendo só `trends`), cai para `trend.get` (**singular** — `trends.get` não existe na API do Zabbix e retorna `"Incorrect API 'trends'"`; já aconteceu uma vez). Usado por `zabbix_server_health_metrics`, `database_health_metrics`, `nvps` e `zabbix_server_os_metrics` — qualquer nova métrica histórica deve reusar este helper em vez de chamar `history.get` isolado.
* **Whitelists de chave devem ser prefixos amplos, não uma lista fechada de nomes.** `zabbix_server_health_metrics` usava `["zabbix[process,poller", "zabbix[process,history", ...]` e descartava silenciosamente itens reais como `zabbix[process,trapper,...]`/`zabbix[process,unreachable poller,...]` que o Zabbix retornava. Hoje usa o prefixo genérico `"zabbix[process,"` (cobre qualquer tipo de processo interno) + `"zabbix[queue"`/`"zabbix[wcache"`/`"zabbix[rcache"`/`"zabbix[vcache"`/`"zabbix[vps"`. O mesmo valia para `database_health_metrics` (`critical_db_terms` não incluía `tmp`/`table`/`disk`/`innodb`, descartando ex. `mysql.status[Created_tmp_disk_tables]`).
* **`zabbix_server_os_metrics`:** busca CPU/swap/memória/disk I/O do host ativo por **categoria separada** (uma chamada `item.get` por categoria: `system.cpu`, `system.swap`, `vm.memory`, `vfs.dev`), não uma busca única fatiada por `sample_limit` — senão dezenas de itens de disco por dispositivo (descobertos via LLD) engolem o "slice" e deixam CPU/swap/memória de fora. O prefixo é `vfs.dev` (não `vfs.dev.io`): templates mais novos usam `vfs.dev.read.await`/`vfs.dev.write.await` em vez da chave antiga `vfs.dev.io[...]`.
* **Toda chave de `audit_data` que alimenta o prompt deve ser inicializada com um valor "vazio" padrão (`[]`/`0`) *antes* do `try`, nunca só dentro de um `if resultado:`.** Um resultado vazio (sem proxies, sem manutenções ativas) e uma falha de coleta pareciam idênticos no JSON final (chave ausente) antes desse ajuste — `proxies_details`, `super_admin_users_samples/count`, `global_scripts_samples/count`, `database_health_metrics` e `zabbix_server_health_metrics` seguem esse padrão.
* **Coletores adicionados que só existiam referenciados no prompt, nunca implementados:** `active_mediatypes_samples/count` (`mediatype.get`), `business_services_count/samples` (`service.get`), `active_maintenances_samples/count` (`maintenance.get`, filtrado por `active_since <= now <= active_till` — só a janela geral de vigência, não a recorrência diária/semanal interna).
* **`nvps`:** usar `filter` exato `zabbix[wcache,values]`, nunca `search` (`"zabbix[wcache,values"` batia por LIKE em `zabbix[wcache,values,float]`/`,uint`/`,str` também, e a API não garante ordem — `[0]` podia pegar um sub-tipo zerado em vez do agregado).

### 4.1. Modo CLI local dos provedores de IA (`api/ai_cli_client.py`)

Alternativa ao SDK: quando a conta tem `auth_mode == "cli"`, `AIClient.generate_audit_report()` não chama nenhum SDK — delega para `ai_cli_client.generate_via_cli(provider, prompt, model_override)`, que roda o binário da CLI oficial do provedor (`claude`/`codex`/`gemini`) como subprocesso.

* **Por que não SDK/API key:** o objetivo é usar a assinatura (Claude Pro/Max, ChatGPT Plus/Pro, Gemini Advanced) do usuário, não cobrança por token. Isso é feito chamando a própria CLI oficial em modo headless — não reimplementando o fluxo OAuth dela (o que violaria os Termos de Uso de cada provedor e dependeria de Client IDs não documentados).
* **Sandboxing obrigatório:** as três CLIs são agentes de codificação por padrão (têm acesso a shell/arquivos). `generate_via_cli` sempre roda com ferramentas desabilitadas ou sandbox somente-leitura (`--allowedTools ""` no `claude`, `--sandbox read-only` no `codex`, `--approval-mode plan` no `gemini`) e com `cwd` em um diretório temporário isolado (removido em `finally`), para que a CLI se comporte só como motor de texto.
* **Entrada via stdin:** o prompt completo (JSON de auditoria + template) é enviado via stdin do subprocesso, nunca como argumento de linha de comando — evita estourar limites de tamanho de argumento do SO com JSONs grandes.
* **Extração da resposta:** `claude`/`gemini` usam `--output-format json`; `extract_cli_json_text` tenta as chaves `result`/`response`/`text`/`content` e cai para o stdout bruto se o schema não bater (defensivo — os schemas dessas CLIs não são um contrato público estável). `codex` grava a última mensagem direto em arquivo via `-o` (`--output-last-message`), sem necessidade de parsing.
* **Sem streaming na v1:** todas as três variantes fazem `yield` do texto completo de uma vez (sem incrementalidade) — os schemas de evento `stream-json` de `codex`/`gemini` não foram validados contra chamadas reais.

### 5. Renderização de Gráficos e Exportação (`core/chart_renderer.py` + Typst)

A IA gera gráficos escrevendo blocos de código na sintaxe `xychart-beta` do Mermaid.js dentro de blocos ```` ```mermaid ````. Em vez de interpretar essa sintaxe via um motor JS real (o que exigiria um browser), o app faz o parsing dela diretamente em Python.

* **O Fluxo de Renderização (`_render_mermaid_charts` → `core/chart_renderer.py`)**:
  1. `chart_renderer.MERMAID_CODE_FENCE_RE` varre o Markdown extraindo blocos ```` ```mermaid ````.
  2. `normalize_mermaid()` corrige alucinações comuns da IA (`lineChart`/`barChart` → `xychart-beta`, `data: [` → `line [`/`bar [`) e força o tipo de série escolhido pelo usuário na GUI.
  3. `parse_xychart()` extrai título, rótulos do eixo X, rótulo/faixa do eixo Y e as séries de valores. Retorna `None` se o bloco não for um `xychart-beta` parseável (ex.: a IA gerou um flowchart, ignorando a REGRA DE OURO 4 do prompt) — nesse caso o bloco permanece como código no documento final, sem abortar a exportação.
  4. `render_chart()` desenha o gráfico com a **API orientada a objetos do matplotlib** (`Figure` + `FigureCanvasAgg`, nunca `pyplot`) e salva um PNG.
  5. O bloco de texto markdown do Mermaid é substituído localmente por uma tag de imagem `![Gráfico N](caminho/absoluto/chart_N.png)`.
* **A Geração Final (`_export_report_thread`)**:
  * Para **Word (.docx)** e **OpenDocument (.odt)**, o Markdown manipulado (com links para os PNGs) é passado direto para `pypandoc`, sem etapa extra.
  * Para **PDF**, o Markdown é convertido para markup **Typst** via `pypandoc.convert_text(..., 'typst', ...)` (requer Pandoc ≥ 3.1.7 — checado e baixado via `pypandoc.download_pandoc()` se necessário). Os caminhos de imagem, absolutos no Markdown, são reescritos para relativos ao diretório dos gráficos (caminhos em `.typ` são resolvidos relativos ao próprio arquivo `.typ`, não ao `root` do compilador). O corpo Typst é combinado com `templates/report_template.typ` (capa, margens, numeração de página) e compilado direto para PDF via `typst.compile(..., root=<diretório dos PNGs>)` — sem HTML intermediário, sem browser.

### 6. Layout da aba "⚙️ Configurações" (dashboard)

* **Janela inicial `1500x760`** (`MainView.__init__`) — largura aumentada para caber os 5 botões de ação + combobox de modelo em `control_frame` sem cortar.
* **A aba inteira é um `ttkbootstrap.scrolled.ScrolledFrame`** (`autohide=True`), não um `ttk.Frame` puro. Ao adicionar a um `Notebook`, o container precisa ser adicionado, não o frame de conteúdo: `notebook.add(config_frame.container, ...)` — ver docstring da própria classe. Existe para não cortar campos quando janela/DPI/fonte deixam o conteúdo mais alto que a área visível da aba.
* **"Dados do Analista / Empresa" (esquerda) e "Instruções Customizadas para a IA" (direita) terminam na mesma altura por coincidência ajustada, não por layout automático.** As duas colunas (`left_col`/`right_col`) são pilhas `pack` independentes — não há como o `pack` sincronizar a altura de duas frames em colunas diferentes nativamente. A tentativa óbvia (grid de 2 colunas x 3 linhas com a última linha compartilhada) **foi revertida**: fazia `analyst_frame` esticar (`sticky="nsew"`) para preencher a altura da linha, mudando sua aparência original — o pedido era só encurtar Instruções, sem tocar em Analista. A solução final é a mais simples que não mexe em mais nada: `inst_frame` não usa mais `expand=True` (só `fill=X`, igual às outras LabelFrames), e o `ScrolledText` interno tem `height=20` (linhas) fixo, calibrado empiricamente para que a base bata perto da base de `analyst_frame` nesta janela. **Isso não é dinâmico** — se o número de campos de qualquer uma das duas LabelFrames mudar, o valor `height=20` precisa ser recalibrado à mão (relançar `python main.py` e comparar visualmente, ou instrumentar com `winfo_rooty()`/`winfo_height()` como no diagnóstico original). Uma tentativa de calcular isso dinamicamente via bind em `<Configure>` + `winfo_rooty()` foi tentada e descartada por não convergir de forma confiável no primeiro layout.

---

## 🔌 Como Extender e Modificar

### 1. Adicionando um Novo Provedor de IA
Para adicionar um provedor como Groq, Cohere, etc:
1. No `gui/main_view.py`, adicione o provedor no dicionário estático `self.ai_accounts` no `__init__`.
2. No `api/ai_api.py`, atualize a classe `AIClient`:
   * Modifique `get_available_models()` implementando o SDK ou chamada REST do provedor para listar os modelos.
   * Modifique `generate_audit_report()` para inicializar o cliente do provedor, montar a mensagem com `system_instruction` e realizar o laço `for chunk in response: yield chunk.text`.

### 2. Coletando Novas Métricas do Zabbix
Deseja coletar o tempo médio de resposta de Pings, por exemplo?
1. Modifique a função `collect_data()` em `api/zabbix_api.py`.
2. Adicione uma nova chave no dicionário local: `audit_data["nova_metrica"] = dados_buscados`.
3. **Obrigatório:** Vá no arquivo `prompts/report_template.txt` e adicione instruções para a IA analisar a sua nova métrica. Exemplo: *"Analise a seção `nova_metrica` e julgue se a latência está alta"*. Se não fizer isso, a IA frequentemente ignorará o dado solto no JSON.

### 3. Alterando as Ferramentas Nativas Docker (Wayland / GUI)
O projeto utiliza o `tkinter`, que requer comunicação com o Display Server (`X11`).
O arquivo de script em bash/fish `exec_wayland.sh` mapeia os soquetes `/tmp/.X11-unix` e injeta `DISPLAY` para o contêiner rodar graficamente. Se você deseja portar isso para Windows localmente, deve-se gerar um arquivo `.exe` (via PyInstaller), visto que mapear servidor X no Windows Docker é complexo (requer VcXsrv).

---

## ⚠️ Pontos Críticos de Atenção (Gotchas)

- **Manipulação de Interface Fora da Main Thread:** Nunca altere `self.log_text` ou `self.progress_bar` diretamente dentro dos métodos de `controller.py`. Use as interfaces do Tkinter (`self.view.log()`, `self.after(...)`) para enfileirar as atualizações visuais. Caso contrário, a aplicação sofrerá falhas silenciosas de violação de segmentação (Segfault).
- **Mudanças no google-genai:** A API oficial do Gemini mudou em 2025 (`google-generativeai` descontinuado para `google-genai`). Mantenha os `requirements.txt` atualizados utilizando os objetos `Client` e `types.GenerateContentConfig` implementados atualmente na `ai_api.py`.
- **Limpeza de Temp:** O gerador Mermaid cria instâncias e imagens temporárias. O bloco `finally` dentro da exportação deve ser mantido para garantir `shutil.rmtree()` e evitar esgotamento de disco no SO (inodes).
- **Nunca use `claude --bare` em `ai_cli_client.py`:** essa flag desativa explicitamente a leitura de OAuth/keychain ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper... OAuth and keychain are never read") — quebraria exatamente a autenticação via assinatura que o modo CLI local depende. Reduções de overhead da CLI devem vir do `cwd` isolado (diretório temp sem `CLAUDE.md`/config de projeto por perto), não dessa flag.
- **Nunca importe `matplotlib.pyplot` em `chart_renderer.py`:** a renderização de gráficos roda em threads de background (tanto na exportação de relatório quanto na prévia de estilos); `pyplot` mantém estado global de figuras/backend que pode colidir com o event loop do Tkinter na main thread. Use sempre `matplotlib.figure.Figure` + `matplotlib.backends.backend_agg.FigureCanvasAgg` diretamente.
- **Fontes em `templates/report_template.typ` precisam estar genuinamente embutidas no wheel do `typst`, não só instaladas na sua máquina.** O Typst resolve fonte ausente com *fallback silencioso* (sem erro/aviso), então um nome de fonte "errado" ainda compila um PDF válido — só que com a fonte errada. Isso já aconteceu: o template usava `"DejaVu Sans"`, que só "funcionava" porque a máquina de dev tinha essa fonte instalada via fontconfig; ela não vem no wheel do `typst` (que só embute `DejaVu Sans Mono`, `Libertinus Serif` e `New Computer Modern`), então em Docker/Windows sem essa fonte instalada o PDF saía com uma fonte diferente da pretendida — o oposto do objetivo de portabilidade desta seção. Antes de trocar a fonte do template, confirme com `typst.Fonts(include_system_fonts=False, include_embedded_fonts=True).families()` que o nome escolhido está na lista.