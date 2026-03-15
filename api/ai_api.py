import json
import google.generativeai as genai
import openai

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
Um novo cliente nos contratou e realizamos uma extração inicial de dados via API do Zabbix existente deles.

Aqui estão os dados brutos coletados do ambiente:
{data_str}
{evidence_section}

Com base EXCLUSIVAMENTE nestes dados e no seu conhecimento sobre as melhores práticas oficiais da Zabbix, elabore um relatório técnico detalhado e profissional.
Tópicos obrigatórios:
1. **Visão Geral e Situação Atual:** Analise versão e defasagem. Cite hosts desativados.
2. **Banco de Dados, Frontend e Proxies:** Verifique monitoramento base e proxies.
3. **Análise de Tendência de Performance (COM GRÁFICOS ASCII):** Avalie Zabbix Server Health com gráficos em texto obrigatórios ilustrando flutuação e gargalos.
4. **Análise de Coletas Desequilibradas:** Liste itens com delay < 30s.
5. **Dependência de Scripts Externos:** Explique impacto e liste exemplos de External checks.
6. **Avaliação de Templates:** Aponte templates experimentais ou duplicados.
7. **Plano de Ação e Melhorias (Por Prioridade):** Alta, Média e Baixa.
8. **Guia de Implementação:** Passos práticos para a prioridade alta.
9. **Análise de SO:** (Se existirem logs de SO acima).
"""
        if self.provider == "Google Gemini":
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(model_name, system_instruction="Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Nunca seja genérico e use dados do JSON.")
            return model.generate_content(prompt).text
            
        elif self.provider == "OpenAI":
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(model=model_name, messages=[{"role": "system", "content": "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown com gráficos ASCII onde solicitado e cite dados exatos."}, {"role": "user", "content": prompt}])
            return response.choices[0].message.content