# 📊 Auditoria Inteligente de Zabbix com IA

Uma ferramenta avançada com interface gráfica (GUI) desenvolvida em Python que realiza a extração de métricas vitais de um ambiente Zabbix (Standalone ou Cluster HA) via API e utiliza Inteligência Artificial para gerar um relatório de auditoria técnico, detalhado e priorizado.

Ideal para consultores, arquitetos de monitoramento e equipes de infraestrutura que precisam diagnosticar rapidamente a saúde de um ambiente Zabbix.

## ✨ Funcionalidades

- **Suporte Multi-IA**: Compatível com provedores líderes de mercado (**Google Gemini**, **OpenAI**, **Anthropic Claude**) e suporte a execução de LLMs locais via **Ollama** para ambientes restritos ou isolados.
- **Autenticação via CLI local (assinatura)**: Além de API key, cada conta Anthropic/OpenAI/Google Gemini pode usar a CLI oficial já instalada e autenticada na máquina (`claude`, `codex`, `gemini`) em vez de cobrança por token — útil para quem já tem Claude Pro/Max, ChatGPT Plus/Pro ou Gemini Advanced. A aplicação chama a CLI em modo headless/somente-leitura (sem acesso a arquivos ou shell), nunca lê ou manipula o token OAuth diretamente. Veja "Modo CLI local" abaixo.
- **Extração Automatizada via Zabbix API**: Coleta Hosts, Itens, Templates, regras LLD, configuração de autenticação e MFA em Zabbix 7.0+ quando disponível e Proxies. Polling agressivo é somente intervalo simples entre 1 e 29 segundos; `delay=0`, macros e agendas complexas não são classificados incorretamente.
- **Coleta resiliente e rastreável**: Uma falha de permissão ou compatibilidade em uma seção opcional não descarta os dados já coletados. O JSON sempre traz o schema de coleta e `_collection_metadata` com versão, data UTC, versão do Zabbix, indicação de anonimização, avisos estruturados e `api_call_count` para dimensionar o custo da coleta.
- **Persistência segura e independente do diretório atual**: Configurações, cache e dados usam os diretórios nativos do usuário via `platformdirs`. Gravações diretas são atômicas e recebem permissão `0600` quando suportada; configurações inválidas são avisadas e substituídas por padrões seguros.
- **Coleta sem IA ("📥 Apenas Coleta")**: Executa somente a extração de dados do Zabbix e salva o JSON coletado onde você escolher, sem enviar nada para a IA — útil para arquivar evidências, revisar a coleta antes de gastar tokens, ou rodar a coleta em um ambiente e gerar o relatório em outro.
- **Gerar relatório a partir de uma coleta existente ("📂 Iniciar de Coleta")**: Carrega qualquer arquivo `.json` gerado pela "Apenas Coleta" (ou pelo cache automático) e envia direto para a IA, sem tocar no Zabbix — complementa o botão acima para separar totalmente coleta e geração do relatório.
- **Inteligência de Cluster (HA Nativo)**: Descobre automaticamente qual é o nó *Active* do servidor em ambientes de Alta Disponibilidade para coletar métricas reais, ignorando nós *Standby*.
- **Análise de Saúde Interna (Zabbix Health)**: Extrai o histórico recente de processos internos críticos (pollers, history syncers, caches, queue).
- **Suporte Multi-Versão**: Identifica automaticamente a versão do Zabbix e adapta login, autenticação, consulta de Super Admins e coleta de proxies. A matriz de compatibilidade possui testes para Zabbix **5.0, 5.2, 6.0, 6.4, 7.0 e 7.4**; veja a tabela em “Compatibilidade com Zabbix”.
- **Gráficos Avançados e Customizáveis**: A IA projeta tendências em `xychart-beta` e distribuições em `pie` do Mermaid.js, renderizadas nativamente via *matplotlib* (sem browser). Pontos `N/A`, vazios ou isoladamente inválidos viram lacunas sem eliminar a série; diferenças entre a quantidade de rótulos e valores são ajustadas de forma determinística. A interface permite pré-visualizar Linha, Barra e Pizza, além de personalizar cores, dimensões e fontes.
- **Exportação Profissional e Elegante**:
  - **PDF (.pdf)**: Renderização via *Typst* (compilador nativo, sem dependência de browser/Chromium). Gera automaticamente uma Capa de Rosto com os dados do auditor/empresa, paginação inteligente e não depende de LaTeX nem de instaladores de sistema.
  - **Word (.docx)**: Aplica nativamente a estruturação de um template base customizável.
  - **Outros**: Markdown (.md), Texto Puro (.txt) e OpenDocument (.odt).
  - O pipeline roda fora da thread da interface em um motor independente de Tk. Estilo e metadados são capturados antes do início da worker, progresso/logs retornam pela fila da GUI e imagens/artefatos temporários são removidos tanto em sucesso quanto em falha.
- **Análise de Evidências de SO**: Permite anexar um resumo sanitizado do Sistema Operacional (identificação, uso de disco/memória, processos sem argumentos, status do serviço e uma allowlist de parâmetros operacionais do Zabbix) para que a IA cruze informações da API com gargalos no SO.
- **Interface de Usuário Robusta**: Construída com `ttkbootstrap` (tema Darkly), usa workers sem acesso direto ao Tk e uma fila de eventos para manter a interface responsiva. Contas exigem confirmação antes de conflito ou remoção e nomes antigos são eliminados do keyring após a nova configuração ser persistida. A prévia de gráficos usa debounce e descarta resultados antigos; logs têm cores por severidade e todos os formatos de exportação mostram sucesso ou erro.

---

## 📂 Estrutura do Projeto

```text
auditoria_zabbix/
├── api/
│   ├── ai_api.py          # Integração unificada (Gemini, OpenAI, Anthropic, Ollama)
│   ├── ai_cli_client.py   # Execução sandboxed das CLIs locais (claude/codex/gemini)
│   └── zabbix_api.py      # Comunicação e métodos da Zabbix API
├── core/
│   ├── chart_renderer.py  # Parsing de xychart-beta/pie + renderização matplotlib
│   ├── controller.py      # Lógica de negócio e orquestração de Threads
│   ├── anonymizer.py      # Redação estrutural e pseudonimização de IPs
│   ├── operation.py       # Ciclo de vida e cancelamento por operação
│   ├── pandoc_runtime.py  # Descoberta do Pandoc e fallback com consentimento
│   ├── paths.py           # Recursos empacotados + diretórios nativos do usuário
│   ├── persistence.py     # Settings/cache validados e gravação atômica
│   ├── report_exporter.py # Exportação headless para MD/TXT/DOCX/ODT/PDF
│   └── run_config.py      # Snapshots imutáveis criados na thread do Tk
├── gui/
│   ├── main_view.py             # Janela principal (ttkbootstrap)
│   ├── manage_accounts_view.py  # Modal de contas de IA (API Key / CLI local)
│   ├── manage_attachments_view.py
│   └── style_settings_view.py
├── prompts/
│   └── report_template.txt # Template injetável do contexto enviado para a IA
├── templates/
│   ├── report_template.docx  # Documento de referência do Pandoc (Word)
│   └── report_template.typ   # Template Typst (capa, margens, numeração) para PDF
├── tests/                 # Testes unitários (unittest, stdlib)
├── tools/
│   ├── coleta_zabbix_os.sh # Script de coleta de evidências do SO
│   └── prepare_pandoc.py   # Prepara o Pandoc específico da plataforma para o bundle
├── .github/workflows/
│   ├── tests.yml          # unittest em Python 3.11/3.12 + Ruff crítico
│   └── release.yml        # Gate de qualidade + build PyInstaller Windows/Linux
├── .env.example           # Exemplo de arquivo de credenciais
├── main.py                # Ponto de entrada da aplicação
├── pyinstaller.spec       # Configuração de build do executável standalone
├── requirements-dev.txt   # Ruff fixado para validação local/CI
└── requirements.txt       # Dependências de runtime (versões fixadas)
```

---

## 🚀 Como Instalar e Configurar

### Opção rápida: executável pronto (Windows/Linux)

Cada [Release](../../releases) publicada nesta página traz executáveis prontos para Windows (`.zip`) e Linux (`.tar.gz`), gerados automaticamente pelo GitHub Actions a partir da tag correspondente — não requer Python instalado. Baixe o pacote da sua plataforma, extraia e rode `AuditoriaZabbix.exe` (Windows) ou `./AuditoriaZabbix` (Linux). O Pandoc necessário para DOCX/ODT/PDF já está incorporado ao pacote; o executável não faz download desse componente em runtime.

Para gerar uma nova release: `git tag vX.Y.Z && git push origin vX.Y.Z` — o workflow em `.github/workflows/release.yml` primeiro exige a aprovação integral do mesmo gate de qualidade usado em pushes e pull requests. Somente depois dos testes em Python 3.11/3.12 e do Ruff crítico passarem ele baixa e valida o Pandoc de cada plataforma, cria os executáveis via PyInstaller e roda o próprio bundle com rede bloqueada para gerar DOCX e PDF. A publicação só ocorre se esses smoke tests passarem.

### Instalação a partir do código-fonte

### 1. Pré-requisitos
- Python 3.11+ instalado.
- Acesso à API de um servidor Zabbix (URL, Usuário e Senha).
- Uma credencial de IA: chave de API de **Google Gemini**, **OpenAI** ou **Anthropic** — ou, alternativamente, a CLI oficial do provedor já instalada e autenticada (`claude`/`codex`/`gemini`, veja "Modo CLI local" abaixo) ou um servidor **Ollama** local.

### 2. Instalação
Clone ou baixe este repositório e navegue até a pasta do projeto:

```bash
# Recomenda-se criar um ambiente virtual
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# Instale as dependências (inclui matplotlib, typst e platformdirs)
pip install -r requirements.txt
```

Para executar a verificação usada pela integração contínua:

```bash
pip install -r requirements-dev.txt
MPLBACKEND=Agg python -m unittest discover -s tests -v
ruff check --select E9,F63,F7,F82 .
```

O workflow `.github/workflows/tests.yml` roda esses testes sem servidor gráfico em pushes e pull requests, com uma matriz de Python 3.11 e 3.12. Ele também pode ser chamado por outros workflows; o pipeline de release o reutiliza como dependência obrigatória antes de qualquer build.

### Estado da validação integrada

Em 17/08/2026, a Onda 16 concluiu a auditoria automatizada final do conjunto de melhorias: **215 testes** passaram, assim como o Ruff crítico, `compileall`, `pip check`, a validação sintática dos scripts Fish e `git diff --check`. As buscas de consistência confirmaram `.env` ignorado, Docker sem `COPY . .`, controller sem dependência de Tkinter, fila principal única, ausência de `subprocess.run()` no adaptador CLI, ausência de supressão global dos warnings TLS e rejeição dos placeholders visuais de modelo. Um smoke test real gerou e validou arquivos Markdown, TXT, DOCX, ODT e PDF, incluindo gráfico Mermaid.

Essa validação automatizada não substitui os smoke tests humanos da Onda 17 em Linux/Windows, versões reais do Zabbix, provedores de IA e ambientes gráficos aplicáveis.

`requirements.txt` é a fonte única das dependências de runtime. A instalação por código-fonte precisa acessar o PyPI ou um mirror corporativo que contenha essas dependências e suas transitivas; o repositório não mantém wheelhouse e não promete instalação por fonte totalmente offline. Para uso sem instalação de Python ou pacotes, prefira o executável da Release.

DOCX, ODT e PDF exigem Pandoc 3.1.7 ou superior. Ao executar por código-fonte, se ele estiver ausente ou antigo, a interface explica o motivo e pede confirmação antes de baixá-lo para o diretório de dados do usuário. Recusar o download cancela somente aquela exportação. Markdown e texto puro não dependem de Pandoc.

### Executar a GUI em Docker (Linux X11/Wayland)

Depois de criar localmente a imagem `auditoria-zabbix`, execute:

```bash
fish ./exec_wayland.fish --data-dir "$PWD/auditoria-zabbix-data"
```

O lançador executa o processo do contêiner com o UID/GID do usuário atual, sem `sudo`, sem acesso à rede do host e sem montar o código-fonte sobre `/app`. Apenas o diretório indicado em `--data-dir` é montado com escrita em `/data`; ele armazena configurações, cache, arquivos temporários e relatórios. Como esse diretório pode conter informações sensíveis, mantenha-o privado e não o compartilhe inadvertidamente.

Para usar um serviço acessível somente na máquina anfitriã, a rede do host deve ser solicitada explicitamente:

```bash
fish ./exec_wayland.fish --host-network --data-dir "$PWD/auditoria-zabbix-data"
```

O acesso gráfico usa o cookie de autenticação X11 (`XAUTHORITY`) e o socket correspondente a `DISPLAY`; o script não altera a política do servidor X com `xhost`. Em uma sessão Wayland, ele monta o socket Wayland somente quando `WAYLAND_DISPLAY` e `XDG_RUNTIME_DIR` apontam para um socket existente. A interface Tk ainda precisa de X11/XWayland, portanto `DISPLAY`, o socket X11 e um arquivo `XAUTHORITY` legível devem estar presentes. Verifique também se o usuário pode executar `docker` sem `sudo`.

### 3. Configuração de Credenciais

O caminho recomendado é preencher as credenciais pela interface. Senha/token do Zabbix e chaves dos provedores são guardados no keyring do sistema operacional; `settings.json` contém apenas opções não secretas. Para execução por código-fonte, um `.env` baseado em `.env.example` continua disponível como fallback de inicialização:

```dotenv
ZABBIX_URL="http://seu-zabbix.com/zabbix/api_jsonrpc.php"
ZABBIX_USER="Admin"
ZABBIX_PASS="sua_senha"
GEMINI_API_KEY="SUA_CHAVE_DO_GOOGLE_GEMINI"
```

---

## 💻 Como Usar

1. Execute o arquivo principal para abrir a interface gráfica:
   ```bash
   python main.py
   ```
2. **(Opcional) Evidências de SO**: Se você tiver acesso ao servidor Linux onde o Zabbix está hospedado, execute `tools/coleta_zabbix_os.sh`. Ele gera um arquivo `.txt` com identificação e uptime do SO, uso de memória/disco, até 20 processos (somente PID, nome do executável, CPU e memória), estado resumido do serviço e parâmetros operacionais permitidos do `zabbix_server.conf`. O coletor não inclui argumentos de processos nem copia a configuração completa; chaves relacionadas a senhas, segredos, tokens, communities, PSKs e credenciais são excluídas, e uma redação defensiva é aplicada à saída. O arquivo é criado com permissão `0600`. Para testes ou caminhos não padrão, use `ZABBIX_OS_RELEASE_FILE`, `ZABBIX_SERVER_CONF_FILE` e `ZABBIX_EVIDENCE_OUTPUT_FILE`. Depois, clique em **"📎 Anexar Evidências OS"** na interface para carregar o arquivo.
3. Selecione a conta/provedor de IA e o modelo desejado. A lista é buscada dinamicamente ao validar a conexão; a Anthropic usa `models.list()` e mostra uma lista curta de fallback, acompanhada de aviso, somente se a descoberta falhar. Estados como “carregando” e “falha” são apenas mensagens visuais e nunca podem ser enviados como modelo. No modo CLI local, o modelo opcional da conta ou o padrão da própria CLI é usado.
4. Clique em **"▶ Iniciar Auditoria"**.
5. Acompanhe o progresso na aba "Logs da Execução". Assim que finalizado, o relatório em Markdown estará disponível na aba "Relatório Final"; use **“Salvar / Exportar Relatório”** para escolher o formato e o destino.
6. Para reaproveitar a última coleta e gerar outro relatório sem consultar o Zabbix de novo, use **"🔄 Regerar (Apenas IA)"**. Para apenas coletar os dados do Zabbix e salvá-los em um arquivo `.json` à sua escolha — sem chamar a IA — use **"📥 Apenas Coleta"**. Para gerar um relatório a partir de um arquivo de coleta específico (não necessariamente o último), use **"📂 Iniciar de Coleta"** e selecione o `.json`.

O relatório exibido e os logs **não são salvos automaticamente**: use **“Salvar / Exportar Relatório”** e **“Salvar Logs”**. As configurações são persistidas antes de iniciar/testar operações e ao confirmar alterações de contas, estilo ou diretórios; editar um campo e fechar a janela sem executar uma dessas ações não garante a gravação. Já toda coleta nova tenta atualizar automaticamente o cache versionado, inclusive no fluxo **“Apenas Coleta”**; uma falha ao gravar o cache gera aviso, mas não apaga o resultado já coletado.

### Limites de anexos e coleta importada

Para manter o contexto controlado e impedir exposição acidental de caminhos locais, a auditoria aceita no máximo 10 anexos de texto, até 1 MiB por anexo e 5 MiB no total. O conteúdo além desses limites é truncado com aviso no log; os prompts recebem apenas o nome do arquivo, nunca o caminho absoluto. Arquivos JSON importados ou em cache devem ter um objeto na raiz e ter no máximo 10 MiB. Coletas com `_collection_metadata.schema_version` diferente de `1` são recusadas até que a aplicação passe a suportá-las.

Os dados do Zabbix, anexos e instruções adicionais são delimitados como conteúdo não confiável no prompt. Não inclua segredos nos anexos: a anonimização continua sendo recomendada e as instruções que apareçam dentro de métricas, logs, JSON ou anexos não devem ser tratadas como comandos pelo provedor de IA.

A anonimização percorre objetos e textos, substitui valores de campos com nomes sensíveis (senha, token, secret, community, PSK e equivalentes) e troca IPv4/IPv6 válidos por pseudônimos estáveis dentro da mesma auditoria. Ela preserva OIDs reconhecidos e **não é uma desidentificação completa**: nomes de hosts, empresas, pessoas, e-mails e texto de negócio podem continuar identificáveis. Revise a coleta e os anexos conforme a política da organização antes de usar uma IA externa.

### Compatibilidade com Zabbix

| Versão coberta por teste | Login usuário/senha | Transporte do token/sessão | Super Admins | Proxies |
|---|---|---|---|---|
| 5.0 | campo `user` | `auth` no payload JSON-RPC | `user.get`, `type=3`, campo `alias` | schema legado (`host`/`status`) |
| 5.2 | campo `user` | `auth` no payload JSON-RPC | `role.get` + filtro `roleid`, campo `alias` | schema legado |
| 6.0 | campo `username` | `auth` no payload JSON-RPC | `role.get` + `roleid`, campo `username` | schema legado |
| 6.4 | campo `username` | `Authorization: Bearer` | schema de roles moderno | schema legado |
| 7.0 e 7.4 | campo `username` | `Authorization: Bearer` | schema de roles moderno | schema moderno (`name`/`operating_mode`) |

A aplicação detecta a versão por `apiinfo.version`. Recursos opcionais ainda dependem das permissões do usuário e da API exposta pelo servidor; incompatibilidades são registradas em `_collection_metadata.warnings` sem apagar as outras fases da coleta. Autenticação e MFA só são consultadas em 7.0+ e uma falha não é interpretada como “MFA desativado”.

### Configuração, cache e diretórios de dados

Arquivos graváveis não dependem mais do diretório em que `main.py` foi iniciado. A aplicação usa os locais nativos retornados por `platformdirs` para o aplicativo `auditoria-zabbix`:

- configuração: `settings.json` no diretório de configuração do usuário;
- cache: `last_audit_cache.json` no diretório de cache do usuário;
- dados: diretório de dados do usuário, usado como destino inicial para logs, coletas e relatórios e, quando autorizado em execução por código-fonte, para o Pandoc baixado.

No Linux, esses locais seguem `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` e `XDG_DATA_HOME` (ou seus defaults sob a home). Windows e macOS usam os diretórios equivalentes da plataforma. No contêiner, como `HOME=/data`, tudo permanece dentro do volume passado em `--data-dir`.

Settings são validados por tipo e limite antes do uso. Um arquivo inválido produz aviso no log e os campos afetados voltam aos padrões; API keys, senha e token continuam fora do JSON e no cofre do sistema. Escritas de settings, cache, coletas JSON, logs e relatórios Markdown/TXT usam temporário no mesmo diretório, `flush`/`fsync` e `os.replace`, preservando o arquivo anterior se a troca falhar, com permissão `0600` quando suportada.

Na exportação, `ReportExporter` recebe snapshots imutáveis de estilo e metadados e concentra o processamento de Markdown, gráficos, Pandoc e Typst sem importar Tkinter. DOCX, ODT e PDF usam um diretório de trabalho exclusivo, sempre removido ao final; Markdown e TXT continuam usando a gravação atômica descrita acima. Em executáveis, `core/pandoc_runtime.py` aceita exclusivamente o Pandoc incorporado e orienta reinstalar a release se o bundle estiver incompleto, sem fallback de rede. Ao terminar, MD, TXT, DOCX, ODT e PDF exibem confirmação de sucesso; qualquer falha produz log de severidade e diálogo de erro.

O cache automático usa um envelope versionado com data UTC, nome seguro e fingerprint da origem, versão do Zabbix, estado de anonimização, warnings e os dados coletados. Ao regenerar, a origem e a data aparecem no log; diferença de servidor, anonimização ou origem desconhecida exige confirmação explícita. Arquivos legados `settings.json` e `last_audit_cache.json` encontrados no diretório de execução são migrados somente quando o novo destino ainda não existe, e o original é preservado para recuperação. O cache versionado também pode ser escolhido em **“Iniciar de Coleta”**.

### Segurança do transporte Zabbix

A URL do Zabbix deve usar HTTP ou HTTPS e não pode carregar usuário, senha, token ou `Authorization` na própria URL. HTTPS com validação de certificado é o caminho recomendado. Antes de testar a conexão ou iniciar uma coleta nova, a aplicação exige confirmação explícita quando credenciais seriam enviadas por HTTP para um host fora de localhost ou quando a validação TLS estiver desativada. Senhas, tokens e cabeçalhos de autorização são redigidos das mensagens de erro exibidas no log.

### Retentativas dos provedores via API

Gemini, OpenAI, Anthropic e Ollama usam a mesma política de até três tentativas totais para falhas iniciais de conexão, HTTP `408`, `429` e `5xx`, respeitando `Retry-After`. Os retries internos dos SDKs são desativados para não empilhar tentativas. A repetição automática só ocorre antes do primeiro trecho do relatório: se a conexão cair depois que algum texto chegou, esse texto é preservado como parcial e a interface orienta tentar novamente com **“Regerar (Apenas IA)”** quando houver coleta em cache, sem duplicar o início do relatório.

---

## 🖥️ Modo CLI local (alternativa à API Key)

Em vez de pagar por token via API, cada conta de IA (Anthropic, OpenAI, Google Gemini) pode ser configurada para usar a CLI oficial do provedor, já autenticada na sua máquina com a sua assinatura:

| Provedor | CLI | Autenticar com |
|---|---|---|
| Anthropic | [`claude`](https://docs.claude.com/claude-code) (Claude Code) | `claude login` |
| OpenAI | [`codex`](https://developers.openai.com/codex/cli) | `codex login` |
| Google Gemini | [`gemini`](https://github.com/google-gemini/gemini-cli) | `gemini` (fluxo de login na primeira execução) |

**Como habilitar:** em "⚙️ Gerenciar" (ao lado de "Conta/Provedor"), ative o toggle "Usar CLI local (assinatura) em vez de API Key" na conta desejada. A tela mostra se o binário foi encontrado no `PATH`. Ollama não tem esse modo — já é local.

**Streaming e fallback por provedor:** antes de cada auditoria, a aplicação executa uma sonda curta de `--help` da CLI instalada. Formatos estruturados só são usados quando a própria versão anuncia as flags necessárias; se a sonda falhar, demorar ou não confirmar o formato, o relatório continua pelo caminho não incremental.

| Provedor | Quando há streaming confirmado | Fallback seguro |
|---|---|---|
| Claude (`claude`) | `--help` anuncia `--output-format stream-json`, `--verbose` e `--include-partial-messages`; somente deltas `content_block_delta` testados são exibidos. | Texto final; usa JSON final apenas se `--output-format json` também for anunciado. |
| Codex (`codex exec`) | `codex exec --help` anuncia `--json`; somente o evento JSONL `item.completed`/`agent_message` testado é exibido. | Arquivo final de `-o` (`--output-last-message`), sem depender de JSONL. |
| Gemini (`gemini`) | Não há parser incremental habilitado: não assumimos um schema JSONL estável. | Texto final; usa JSON final apenas se `--output-format json` for anunciado. |

Cancelamento e timeout também encerram a árvore do subprocesso nos caminhos incremental e não incremental. Para não expor dados da auditoria, mensagens de erro não reproduzem o `stdout` ou `stderr` integral da CLI.

A CLI local é apenas o mecanismo de autenticação/execução: Claude, Codex e Gemini continuam podendo enviar o prompt ao serviço em nuvem do respectivo provedor. Ela não transforma o processamento em local. Para manter o conteúdo fora de provedores externos, use um Ollama hospedado em infraestrutura sob seu controle e confirme também a URL configurada.

**Importante:**
- O binário precisa estar instalado e autenticado (`claude login`/`codex login`/login do `gemini`) *antes* de rodar uma auditoria nesse modo — a aplicação não faz login por você e não lê/gera tokens OAuth.
- Esse modo usa o modo headless/scriptável oficial de cada CLI, sempre com ferramentas desabilitadas ou sandbox somente-leitura (a aplicação nunca deixa a CLI executar comandos ou editar arquivos no seu sistema).
- Usar a assinatura fora da CLI/app oficial pode estar sujeito aos Termos de Uso do provedor — este modo usa a CLI oficial diretamente (não reimplementa o login), mas a responsabilidade pelo uso de acordo com a assinatura contratada é do usuário.
- A disponibilidade de streaming depende da versão instalada e da matriz acima. Mesmo no fallback, API e CLI usam o mesmo evento terminal de conclusão; se houver timeout, erro ou limite de tokens, qualquer texto já recebido permanece visível como **parcial** e não é anunciado como auditoria concluída.

---

## ⚠️ Avisos e Segurança

- **Acesso de Leitura**: A aplicação realiza **apenas leituras** no banco do Zabbix (métodos `*.get` e `apiinfo.version`). Nenhuma configuração do Zabbix será alterada pela ferramenta.
- **Privacidade de Dados**: As métricas, instruções customizadas e o conteúdo dos anexos são enviados ao destino de IA selecionado — via API ou CLI local. A anonimização reduz a exposição de segredos rotulados e endereços IP, mas não remove todos os identificadores. Confirme a localização do Ollama, os termos do provedor, retenção, política de segurança e base legal/LGPD antes do envio.

---
*Desenvolvido como uma ferramenta de automação e consultoria inteligente.*
