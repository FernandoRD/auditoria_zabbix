# 📊 Auditoria Inteligente de Zabbix com IA

Uma ferramenta avançada com interface gráfica (GUI) desenvolvida em Python que realiza a extração de métricas vitais de um ambiente Zabbix (Standalone ou Cluster HA) via API e utiliza Inteligência Artificial para gerar um relatório de auditoria técnico, detalhado e priorizado.

Ideal para consultores, arquitetos de monitoramento e equipes de infraestrutura que precisam diagnosticar rapidamente a saúde de um ambiente Zabbix.

## ✨ Funcionalidades

- **Suporte Multi-IA**: Compatível com provedores líderes de mercado (**Google Gemini**, **OpenAI**, **Anthropic Claude**) e suporte a execução de LLMs locais via **Ollama** para ambientes restritos ou isolados.
- **Autenticação via CLI local (assinatura)**: Além de API key, cada conta Anthropic/OpenAI/Google Gemini pode usar a CLI oficial já instalada e autenticada na máquina (`claude`, `codex`, `gemini`) em vez de cobrança por token — útil para quem já tem Claude Pro/Max, ChatGPT Plus/Pro ou Gemini Advanced. A aplicação chama a CLI em modo headless/somente-leitura (sem acesso a arquivos ou shell), nunca lê ou manipula o token OAuth diretamente. Veja "Modo CLI local" abaixo.
- **Extração Automatizada via Zabbix API**: Coleta dados de Hosts, Itens (identificando polling agressivo e scripts externos), Templates e Proxies.
- **Coleta sem IA ("📥 Apenas Coleta")**: Executa somente a extração de dados do Zabbix e salva o JSON coletado onde você escolher, sem enviar nada para a IA — útil para arquivar evidências, revisar a coleta antes de gastar tokens, ou rodar a coleta em um ambiente e gerar o relatório em outro.
- **Inteligência de Cluster (HA Nativo)**: Descobre automaticamente qual é o nó *Active* do servidor em ambientes de Alta Disponibilidade para coletar métricas reais, ignorando nós *Standby*.
- **Análise de Saúde Interna (Zabbix Health)**: Extrai o histórico recente de processos internos críticos (pollers, history syncers, caches, queue).
- **Suporte Multi-Versão**: Identifica automaticamente a versão do Zabbix (suporta métodos de autenticação antigos via Payload e novos `>= 6.4` via Header Bearer).
- **Gráficos Avançados e Customizáveis**: A IA projeta gráficos de tendência na sintaxe `xychart-beta` do Mermaid.js, renderizados nativamente via *matplotlib* (sem dependência de browser). Através da interface, o analista pode personalizar o tipo de gráfico (Linhas ou Barras), cores e fontes, contando com uma **pré-visualização em tempo real**.
- **Exportação Profissional e Elegante**:
  - **PDF (.pdf)**: Renderização via *Typst* (compilador nativo, sem dependência de browser/Chromium). Gera automaticamente uma Capa de Rosto com os dados do auditor/empresa, paginação inteligente e não depende de LaTeX nem de instaladores de sistema.
  - **Word (.docx)**: Aplica nativamente a estruturação de um template base customizável.
  - **Outros**: Markdown (.md), Texto Puro (.txt) e OpenDocument (.odt).
- **Análise de Evidências de SO**: Permite anexar arquivos de log e configurações do Sistema Operacional (ex: `zabbix_server.conf`, uso de disco/memória) para que a IA cruze informações da API com gargalos no SO.
- **Interface de Usuário Robusta**: Construída com `ttkbootstrap` (tema Darkly), é assíncrona (multithread) impedindo congelamentos da interface e possui menu de gerenciamento de chaves de API.

---

## 📂 Estrutura do Projeto

```text
auditoria_zabbix/
├── api/
│   ├── ai_api.py          # Integração unificada (Gemini, OpenAI, Anthropic, Ollama)
│   ├── ai_cli_client.py   # Execução sandboxed das CLIs locais (claude/codex/gemini)
│   └── zabbix_api.py      # Comunicação e métodos da Zabbix API
├── core/
│   ├── chart_renderer.py  # Parsing de xychart-beta + renderização matplotlib
│   └── controller.py      # Lógica de negócio e orquestração de Threads
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
│   └── coleta_zabbix_os.sh # Script de coleta de evidências do SO
├── whl/                   # .whl de anthropic/openai para instalação offline
├── .github/workflows/
│   └── release.yml        # Pipeline de release (build PyInstaller Windows/Linux)
├── .env.example           # Exemplo de arquivo de credenciais
├── main.py                # Ponto de entrada da aplicação
├── pyinstaller.spec       # Configuração de build do executável standalone
└── requirements.txt       # Dependências do projeto (versões fixadas)
```

---

## 🚀 Como Instalar e Configurar

### Opção rápida: executável pronto (Windows/Linux)

Cada [Release](../../releases) publicada nesta página traz executáveis prontos para Windows (`.zip`) e Linux (`.tar.gz`), gerados automaticamente pelo GitHub Actions a partir da tag correspondente — não requer Python instalado. Baixe o pacote da sua plataforma, extraia e rode `AuditoriaZabbix.exe` (Windows) ou `./AuditoriaZabbix` (Linux).

Para gerar uma nova release: `git tag vX.Y.Z && git push origin vX.Y.Z` — o workflow em `.github/workflows/release.yml` builda os dois executáveis via PyInstaller e publica a Release automaticamente.

### Instalação a partir do código-fonte

### 1. Pré-requisitos
- Python 3.8+ instalado.
- Acesso à API de um servidor Zabbix (URL, Usuário e Senha).
- Uma credencial de IA: chave de API de **Google Gemini**, **OpenAI** ou **Anthropic** — ou, alternativamente, a CLI oficial do provedor já instalada e autenticada (`claude`/`codex`/`gemini`, veja "Modo CLI local" abaixo) ou um servidor **Ollama** local.

### 2. Instalação
Clone ou baixe este repositório e navegue até a pasta do projeto:

```bash
# Recomenda-se criar um ambiente virtual
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# Instale as dependências (inclui matplotlib e typst, sem passos extras de instalação)
pip install -r requirements.txt
```

> **Rede corporativa bloqueando o PyPI?** A pasta `whl/` traz os `.whl` de `anthropic` e `openai` prontos para instalação offline (`pip install whl/anthropic-*.whl whl/openai-*.whl`), para ambientes onde o índice público está bloqueado.

### 3. Configuração de Credenciais
Crie um arquivo chamado `.env` na raiz do projeto (use o `.env.example` como base) e preencha suas informações:

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
2. **(Opcional) Evidências de SO**: Se você tiver acesso ao servidor Linux onde o Zabbix está hospedado, execute o script `coleta_zabbix_os.sh` fornecido junto com a ferramenta. Ele gerará um arquivo `.txt`. Clique no botão **"📎 Anexar Evidências OS"** na interface para carregar este arquivo.
3. Selecione a conta/provedor de IA e o modelo desejado (a lista de modelos é buscada dinamicamente ao validar a conexão, exceto em modo CLI local).
4. Clique em **"▶ Iniciar Auditoria"**.
5. Acompanhe o progresso na aba "Logs da Execução". Assim que finalizado, o relatório em Markdown estará disponível na aba "Relatório Final" e será salvo automaticamente na pasta do projeto como `relatorio_auditoria_zabbix.md`.
6. Para reaproveitar a última coleta e gerar outro relatório sem consultar o Zabbix de novo, use **"🔄 Regerar (Apenas IA)"**. Para apenas coletar os dados do Zabbix e salvá-los em um arquivo `.json` à sua escolha — sem chamar a IA — use **"📥 Apenas Coleta"**.

---

## 🖥️ Modo CLI local (alternativa à API Key)

Em vez de pagar por token via API, cada conta de IA (Anthropic, OpenAI, Google Gemini) pode ser configurada para usar a CLI oficial do provedor, já autenticada na sua máquina com a sua assinatura:

| Provedor | CLI | Autenticar com |
|---|---|---|
| Anthropic | [`claude`](https://docs.claude.com/claude-code) (Claude Code) | `claude login` |
| OpenAI | [`codex`](https://developers.openai.com/codex/cli) | `codex login` |
| Google Gemini | [`gemini`](https://github.com/google-gemini/gemini-cli) | `gemini` (fluxo de login na primeira execução) |

**Como habilitar:** em "⚙️ Gerenciar" (ao lado de "Conta/Provedor"), ative o toggle "Usar CLI local (assinatura) em vez de API Key" na conta desejada. A tela mostra se o binário foi encontrado no `PATH`. Ollama não tem esse modo — já é local.

**Importante:**
- O binário precisa estar instalado e autenticado (`claude login`/`codex login`/login do `gemini`) *antes* de rodar uma auditoria nesse modo — a aplicação não faz login por você e não lê/gera tokens OAuth.
- Esse modo usa o modo headless/scriptável oficial de cada CLI, sempre com ferramentas desabilitadas ou sandbox somente-leitura (a aplicação nunca deixa a CLI executar comandos ou editar arquivos no seu sistema).
- Usar a assinatura fora da CLI/app oficial pode estar sujeito aos Termos de Uso do provedor — este modo usa a CLI oficial diretamente (não reimplementa o login), mas a responsabilidade pelo uso de acordo com a assinatura contratada é do usuário.
- A v1 não tem streaming incremental no modo CLI: o relatório aparece de uma vez quando a CLI termina, em vez de "digitando" aos poucos como no modo API key.

---

## ⚠️ Avisos e Segurança

- **Acesso de Leitura**: A aplicação realiza **apenas leituras** no banco do Zabbix (métodos `*.get` e `apiinfo.version`). Nenhuma configuração do Zabbix será alterada pela ferramenta.
- **Privacidade de Dados**: As métricas extraídas (nomes de hosts, chaves de itens e templates) são enviadas ao provedor de IA selecionado (Google Gemini, OpenAI, Anthropic ou Ollama local) — via API paga ou via CLI local, conforme o modo escolhido. Use a opção "Anonimizar Dados Sensíveis" quando aplicável, e certifique-se de que o envio não viola as políticas de segurança e LGPD da sua empresa ou do seu cliente.

---
*Desenvolvido como uma ferramenta de automação e consultoria inteligente.*