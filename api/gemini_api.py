import json
import google.generativeai as genai
import config

def setup_gemini():
    """Configura a API do Gemini com a chave."""
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
    except Exception as e:
        raise ConnectionError(f"Falha ao configurar a API do Gemini. Verifique sua API Key. Erro: {e}")

def get_available_models():
    """Busca os modelos disponíveis na API do Gemini online."""
    models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            models.append(m.name)
    return models

def generate_audit_report(audit_data, model_name="gemini-1.5-pro-latest", os_evidence=""):
    """
    Envia os dados coletados para o Google Gemini e solicita a geração
    de um relatório de auditoria detalhado, priorizado e explicativo.
    """
    model = genai.GenerativeModel(model_name)
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

Utilize formatação em Markdown para facilitar a leitura, com títulos, listas e negrito onde necessário.
"""
    response = model.generate_content(prompt)
    return response.text