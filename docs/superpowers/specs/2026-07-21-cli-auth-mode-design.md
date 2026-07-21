# Autenticação via CLI local dos provedores de IA

## Contexto e motivação

Hoje o `AIClient` (`api/ai_api.py`) só sabe autenticar com os provedores de IA via API key/token pago por uso (SDKs `google-genai`, `openai`, `anthropic`, ou a URL local do Ollama). O usuário quer poder usar, em vez disso, a assinatura que já tem em cada provedor (Claude Pro/Max, ChatGPT Plus/Pro, Gemini Advanced), da mesma forma que as CLIs oficiais fazem.

Reimplementar o fluxo OAuth de cada CLI (como o `claude login`/`codex login`/`gemini` fazem internamente) foi descartado: esses fluxos não são APIs públicas para terceiros, usam Client IDs não documentados oficialmente, e reutilizá-los fora do app oficial tende a violar os Termos de Uso de cada provedor (risco de suspensão de conta).

Em vez disso, a aplicação vai **chamar o binário da CLI oficial já instalada e autenticada na máquina do usuário** (`claude`, `codex`, `gemini`) em modo não-interativo/headless — um modo de uso oficialmente suportado por essas ferramentas para automação. Nenhum token é extraído, lido ou manipulado pelo app: a CLI cuida da própria sessão.

Flags reais confirmadas no ambiente do usuário (`claude` e `codex` já instalados; `gemini` instalado durante esta conversa):

- **Anthropic**: `claude -p --system-prompt "<sys>" --model <alias> --allowedTools "" --output-format json` (prompt via stdin)
- **OpenAI**: `codex exec --sandbox read-only -C <scratch-dir> --skip-git-repo-check -o <arquivo> [-m <model>]` (prompt via stdin quando nenhum argumento posicional é passado)
- **Google Gemini**: `gemini -p "<instrução curta>" --approval-mode plan --model <model> --output-format json` (stdin complementa o `-p`)

Achado crítico: `claude --bare` desativa leitura de OAuth/keychain ("Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper... OAuth and keychain are never read") — **não deve ser usado**, pois quebraria exatamente a autenticação que este recurso depende.

## Escopo

Inclui: Anthropic (via `claude`), OpenAI (via `codex`), Google Gemini (via `gemini`).
Não inclui: Ollama (já é local, sem mudança). Não inclui streaming real (ver seção própria). Não inclui suíte de testes automatizados que invoque as CLIs de verdade (consumiria cota real da assinatura do usuário).

## Arquitetura

Cada conta de IA em `ai_accounts` (hoje `{"provider": ..., "api_key": ...}`) ganha um campo `auth_mode`: `"api_key"` (padrão, retrocompatível) ou `"cli"`. Quando `"cli"`:

- O campo `api_key` fica vazio/não utilizado para chamadas.
- Um novo campo opcional `cli_model_override` guarda um alias/nome de modelo a passar via `--model`/`-m` (se vazio, a flag é omitida e a CLI usa o modelo padrão configurado por ela mesma).

O provedor base (`Google Gemini` / `OpenAI` / `Anthropic`) já indica qual binário usar — não é necessário um campo adicional para isso.

## Componentes e mudanças por arquivo

- **`gui/manage_accounts_view.py`**: adiciona um toggle "Autenticação: API Key / CLI local" por conta (mesmo padrão visual do toggle de auth do Zabbix em `main_view.py`). Quando "CLI local":
  - Esconde o campo de token e mostra, em texto informativo, se o binário correspondente foi encontrado no PATH (`shutil.which("claude"/"codex"/"gemini")`) — ex: "Binário detectado: /usr/bin/claude ✅" ou "Binário 'gemini' não encontrado no PATH ❌".
  - Mostra um campo opcional "Modelo (override)".
- **`gui/main_view.py`**: `on_provider_change`/`load_models_async` passam a checar o `auth_mode` da conta selecionada. Se `"cli"`, pula a listagem dinâmica de modelos (não faz chamada de API só para listar) e ajusta o combo de modelo para mostrar o override configurado ou "Padrão da CLI".
- **`api/ai_api.py`**: `AIClient.__init__` ganha `auth_mode="api_key"` e `cli_model_override=None`. `generate_audit_report()` passa a despachar para um novo método privado `_generate_via_cli(...)` quando `auth_mode == "cli"`, com um branch por `self.provider` que monta a lista de argumentos do subprocesso correspondente. `get_available_models()` retorna lista vazia/curta quando `auth_mode == "cli"` (a GUI já não vai chamá-lo nesse modo, mas o método fica consistente).
- **`core/controller.py`**: ao montar o `AIClient`, passa `auth_mode` e `cli_model_override` lidos da conta selecionada (`self.view.get_selected_auth_mode()`, novo método em `MainView`, análogo a `get_selected_base_provider()`).
- **`README.md`** e **`TECHNICAL_REFERENCE.md`**: nova seção explicando a dependência opcional das CLIs (`claude`, `codex`, `gemini`) quando o modo "CLI local" é escolhido — como instalar/autenticar cada uma, e o aviso de que isso está sujeito aos Termos de Uso de cada provedor (uso dentro da CLI oficial, não uma reimplementação de OAuth).

## Fluxo de execução do subprocesso (`_generate_via_cli`)

1. Verifica `shutil.which(binário)`; se `None`, levanta erro imediato e claro (ex.: "CLI 'claude' não encontrada no PATH. Instale-a e rode `claude login` antes de usar este modo.").
2. Cria um diretório temporário isolado (`tempfile.mkdtemp(prefix="zabbix_audit_cli_")`) e roda o subprocesso com `cwd` nesse diretório — evita que a CLI descubra/injete `CLAUDE.md`, config de projeto, git status etc. do projeto real, e garante que qualquer tentativa de escrita (mesmo com ferramentas desabilitadas) fique isolada.
3. Monta o comando com ferramentas desabilitadas / sandbox somente-leitura, por CLI:
   - `claude`: `--allowedTools ""` (nenhuma ferramenta liberada).
   - `codex`: `--sandbox read-only --skip-git-repo-check`.
   - `gemini`: `--approval-mode plan` (modo somente-leitura).
4. Envia o prompt completo (o mesmo montado hoje a partir de `prompts/report_template.txt`) via **stdin** do subprocesso, não como argumento de linha de comando — evita estourar limites de tamanho de argumento do SO com JSONs grandes de auditoria.
5. Roda com timeout de 600s (`subprocess.run(..., timeout=600)`), captura stdout/stderr.
6. Extrai o texto final da resposta: `claude`/`gemini` com `--output-format json` retornam um JSON com o resultado — parseia e extrai o campo de texto final; se o parse falhar (schema mudou entre versões), cai para o stdout bruto como texto (defensivo). `codex` grava a última mensagem diretamente em arquivo via `-o`, então basta ler o arquivo.
7. `yield` do texto completo de uma vez (compatível com o gerador existente que a GUI já consome via `append_report_chunk` em loop — só não haverá efeito de "digitação" incremental para contas em modo CLI, que é a troca aceita pela v1 não-streaming).
8. `finally`: remove o diretório temporário.

## Tratamento de erros

- Binário ausente → erro antes de tentar rodar, com instrução de instalação.
- Exit code ≠ 0 → exceção com o `stderr` capturado (ex.: sessão expirada aparece aí, com instrução "rode `claude login` novamente").
- Timeout (600s) → exceção clara de timeout.
- JSON de saída em formato inesperado → fallback para texto bruto do stdout, sem quebrar a geração do relatório.

Esses erros já se propagam pelo caminho existente em `core/controller.py::run_audit_flow` (captura genérica `except Exception as e` → log + fim da auditoria), sem necessidade de tratamento novo lá.

## Streaming (decisão para v1)

Não implementado nesta primeira versão. Os schemas de evento `stream-json` de `codex`/`gemini` não foram validados ao vivo (para não consumir cota real de teste sem necessidade), então a v1 usa saída completa não-streaming por CLI, entregue como um único chunk. Pode evoluir para streaming real depois, quando os schemas forem confirmados em uso real.

## Documentação

- `README.md`: nova subseção em "Como Instalar e Configurar" ou "Funcionalidades" explicando o modo "CLI local" — o que é, quais CLIs instalar (`claude`, `codex`, `gemini`) e como autenticá-las (`claude login`, `codex login`, `gemini` login), e o aviso de que esse modo depende do binário estar no PATH e autenticado, sujeito aos Termos de Uso de cada provedor para uso dentro da CLI oficial.
- `TECHNICAL_REFERENCE.md`: nova entrada em "Fluxos de Funcionamento Interno" descrevendo o mecanismo de `_generate_via_cli` (subprocesso, sandbox, stdin, timeout) para quem for manter o código, e um "Gotcha" novo alertando para nunca usar `claude --bare` (quebra a leitura de OAuth) e para manter o `cwd` isolado.

## Fora de escopo / Futuro

- Streaming real via `stream-json`.
- Suporte a CLI local para Ollama (não se aplica, já é local).
- Testes automatizados que invocam as CLIs de verdade.
