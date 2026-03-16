import json
import google.generativeai as genai
import openai
import anthropic
import requests

class AIClient:
    def __init__(self, provider, api_key):
        self.provider = provider
        self.api_key = api_key

    def get_available_models(self):
        """Busca os modelos disponíveis baseados no provedor escolhido."""
        if not self.api_key:
            return []
            
        try:
            if self.provider == "Google Gemini":
                genai.configure(api_key=self.api_key)
                return [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                
            elif self.provider == "OpenAI":
                client = openai.OpenAI(api_key=self.api_key)
                models = client.models.list()
                return sorted([m.id for m in models.data if "gpt" in m.id or "o1" in m.id or "o3" in m.id])
                
            elif self.provider == "Anthropic":
                # A API da Anthropic não possui listagem dinâmica, então retornamos os principais hardcoded
                return ["claude-3-5-sonnet-latest", "claude-3-opus-latest", "claude-3-haiku-20240307"]
                
            elif self.provider == "Ollama":
                # Para Ollama, api_key será tratada como a URL do servidor local
                base_url = self.api_key.rstrip('/')
                if not base_url: base_url = "http://localhost:11434"
                resp = requests.get(f"{base_url}/api/tags", timeout=5)
                resp.raise_for_status()
                return [m["name"] for m in resp.json().get("models", [])]
                
        except Exception as e:
            raise ConnectionError(f"Falha ao comunicar com a API ({self.provider}): {e}")
            
        return []

    def generate_audit_report(self, audit_data, model_name, os_evidence=""):
        """
        Gera o relatório com o provedor dinâmico.
        """
        data_str = json.dumps(audit_data, indent=2, ensure_ascii=False)
        evidence_section = f"\n\nAlém dos dados via API, o analista extraiu e anexou as seguintes evidências do Sistema Operacional e arquivos de configuração:\n{os_evidence}\n" if os_evidence else ""

        prompt = f"""
Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix.
Um novo cliente nos contratou e realizamos uma extração inicial de dados via API do Zabbix existente deles.

Aqui estão os dados brutos coletados do ambiente, incluindo a saúde atual dos processos internos do Zabbix, em formato JSON:
{data_str}
{evidence_section}

Com base EXCLUSIVAMENTE nestes dados e no seu conhecimento sobre as melhores práticas oficiais da Zabbix, elabore um relatório técnico detalhado e profissional direcionado à equipe de infraestrutura do cliente. O relatório DEVE conter os seguintes tópicos estruturados:

1. **Visão Geral e Situação Atual:** Um resumo do tamanho e estado do ambiente. Cite expressamente os nomes dos hosts desativados (baseado na lista `disabled_hosts_samples`) para indicar por onde começar a limpeza. Analise se a versão do Zabbix está defasada.
2. **Banco de Dados, Frontend e Proxies:** Verifique a lista `db_web_templates_in_use`. Analise se a infraestrutura que suporta o Zabbix (Banco e Web) está sendo devidamente monitorada. Avalie também os dados de `proxies_details` (se existirem), reportando se há proxies desconectados ou com atraso de comunicação.
3. **Análise de Tendência de Performance (COM GRÁFICOS ASCII):** Analise os arrays de valores históricos em `recent_trend_values`. Para as métricas com dados, **gere obrigatoriamente um gráfico visual em arte ASCII** (text-based bar chart ou line chart simples) demonstrando a evolução cronológica recente, seguido de uma interpretação se a tendência é de estabilidade, degradação ou melhoria.
4. **Análise de Coletas Desequilibradas:** Avalie a quantidade de itens com delay menor que 30s. Liste nominalmente os exemplos (com nome e chave encontrados em `aggressive_polling_samples`) para que o cliente saiba exatamente quais itens ajustar primeiro.
5. **Dependência de Scripts Externos:** Explique o impacto no SO (forks) e liste explicitamente as chaves e scripts listados em `external_checks_samples` que devem ser investigados e migrados para coletas nativas.
6. **Avaliação de Templates:** Liste os nomes reais dos templates suspeitos, experimentais, duplicados ou antiquados contidos na lista `templates_list`.
7. **Plano de Ação e Melhorias (Por Prioridade):** Uma lista clara do que deve ser feito, classificada como Prioridade Alta, Média e Baixa.
8. **Guia de Implementação Passo a Passo:** Para cada sugestão de melhoria da prioridade alta, forneça instruções técnicas e detalhadas de como realizar as alterações de forma segura no Zabbix.
9. **Análise do Sistema Operacional (Se aplicável):** Se arquivos de log, uso de disco/memória ou configurações do Zabbix Server (ex: StartPollers, CacheSize) foram fornecidos, cruze essas informações com os gargalos identificados na API e recomende ajustes exatos nos parâmetros do arquivo `zabbix_server.conf`.

REGRA DE OURO: Os clientes precisam de evidências. SEMPRE que mencionar um problema (hosts desativados, coletas agressivas, scripts externos), liste com "bullet points" os nomes, chaves e dados exatos fornecidos nas amostras (*samples*) do JSON. Nunca seja genérico.

REGRA DE OURO 2: O relatório deve ser visualmente rico no terminal/texto. No item 3, o uso de gráficos baseados em caracteres (ASCII Art) para ilustrar a flutuação dos valores de processos/filas é mandatório.

REGRA DE OURO 3: O relatório deverá possuir um sumário.

Utilize formatação em Markdown para salvamento, este relatório será compartilhado com várias pessoas então dê uma atenção especial a aparência e estilo mais elegante.
"""
        if self.provider == "Google Gemini":
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(model_name, system_instruction="Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Nunca seja genérico e use dados do JSON.")
            return model.generate_content(prompt).text
            
        elif self.provider == "OpenAI":
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(model=model_name, messages=[{"role": "system", "content": "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown com gráficos ASCII onde solicitado e cite dados exatos."}, {"role": "user", "content": prompt}])
            return response.choices[0].message.content
            
        elif self.provider == "Anthropic":
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system="Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown com gráficos ASCII onde solicitado e cite dados exatos.",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
            
        elif self.provider == "Ollama":
            base_url = self.api_key.rstrip('/')
            if not base_url: base_url = "http://localhost:11434"
            payload = {
                "model": model_name,
                "system": "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown com gráficos ASCII onde solicitado e cite dados exatos.",
                "prompt": prompt,
                "stream": False
            }
            resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=300) # Timeout alto pois IA local pode demorar
            resp.raise_for_status()
            return resp.json().get("response", "")