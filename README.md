# 📊 Auditoria Inteligente de Zabbix com IA (Google Gemini)

Uma ferramenta avançada com interface gráfica (GUI) desenvolvida em Python que realiza a extração de métricas vitais de um ambiente Zabbix via API e utiliza a Inteligência Artificial do Google Gemini para gerar um relatório de auditoria técnico, detalhado e priorizado.

Ideal para consultores, arquitetos de monitoramento e equipes de infraestrutura que precisam diagnosticar rapidamente a saúde de um ambiente Zabbix.

## ✨ Funcionalidades

- **Extração Automatizada via Zabbix API**: Coleta dados de Hosts, Itens (identificando polling agressivo e scripts externos), Templates e Proxies.
- **Análise de Saúde Interna (Zabbix Health)**: Extrai o histórico recente de processos internos críticos (pollers, history syncers, caches, queue).
- **Suporte Multi-Versão**: Identifica automaticamente a versão do Zabbix (suporta métodos de autenticação antigos via Payload e novos `>= 6.4` via Header Bearer).
- **Integração com Google Gemini**: Envia o JSON extraído para a IA, que atua como um Arquiteto Zabbix, gerando um plano de ação em Markdown.
- **Gráficos ASCII**: A IA gera automaticamente mini-gráficos em texto demonstrando tendências de degradação ou estabilidade dos processos do Zabbix.
- **Análise de Evidências de SO**: Permite anexar arquivos de log e configurações do Sistema Operacional (ex: `zabbix_server.conf`, uso de disco/memória) para que a IA cruze informações da API com gargalos no SO.
- **Interface Gráfica Amigável**: Construída com `ttkbootstrap` (tema Darkly), operando de forma assíncrona (multithreading) para não travar durante as requisições.

---

## 📂 Estrutura do Projeto

```text
auditoria_zabbix/
├── api/
│   ├── gemini_api.py      # Integração e prompts do Google Gemini
│   └── zabbix_api.py      # Comunicação e métodos da Zabbix API
├── core/
│   └── controller.py      # Lógica de negócio e orquestração de Threads
├── gui/
│   └── main_view.py       # Interface de usuário (ttkbootstrap)
├── scripts/ (ou tools/)
│   └── coleta_zabbix_os.sh # Script bash para extração de evidências do SO
├── .env.example           # Exemplo de arquivo de credenciais
├── config.py              # Carregamento de variáveis de ambiente
├── main.py                # Ponto de entrada da aplicação
└── requirements.txt       # Dependências do projeto
```

---

## 🚀 Como Instalar e Configurar

### 1. Pré-requisitos
- Python 3.8+ instalado.
- Acesso à API de um servidor Zabbix (URL, Usuário e Senha).
- Chave de API do Google Gemini (obtenha no Google AI Studio).

### 2. Instalação
Clone ou baixe este repositório e navegue até a pasta do projeto:

```bash
# Recomenda-se criar um ambiente virtual
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
```

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
3. Selecione o modelo de IA desejado (padrão: `gemini-1.5-pro-latest`).
4. Clique em **"Iniciar Auditoria"**.
5. Acompanhe o progresso na aba "Logs da Execução". Assim que finalizado, o relatório em Markdown estará disponível na aba "Relatório Final" e será salvo automaticamente na pasta do projeto como `relatorio_auditoria_zabbix.md`.

---

## ⚠️ Avisos e Segurança

- **Acesso de Leitura**: A aplicação realiza **apenas leituras** no banco do Zabbix (métodos `*.get` e `apiinfo.version`). Nenhuma configuração do Zabbix será alterada pela ferramenta.
- **Privacidade de Dados**: As métricas extraídas (nomes de hosts, chaves de itens e templates) são enviadas para a API do Google Gemini. Certifique-se de que isso não viola as políticas de segurança e LGPD da sua empresa ou do seu cliente.

---
*Desenvolvido como uma ferramenta de automação e consultoria inteligente.*