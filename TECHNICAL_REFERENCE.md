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