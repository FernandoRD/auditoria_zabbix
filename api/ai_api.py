import json
from google import genai
from google.genai import types
import os
import openai
import anthropic
import requests
from datetime import datetime

from api import ai_cli_client

class AIClient:
    def __init__(self, provider, api_key, auth_mode="api_key", cli_model_override=None):
        self.provider = provider
        self.api_key = api_key
        self.auth_mode = auth_mode
        self.cli_model_override = cli_model_override

    def get_available_models(self):
        """Busca os modelos disponíveis baseados no provedor escolhido."""
        if self.auth_mode == "cli":
            return []

        if not self.api_key:
            return []
            
        try:
            if self.provider == "Google Gemini":
                client = genai.Client(api_key=self.api_key)
                return [m.name for m in client.models.list() if m.name and "gemini" in m.name.lower()]
                
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

    def generate_audit_report(self, audit_data, model_name, os_evidence="", analyst_info=None, custom_instructions=""):
        """
        Gera o relatório com o provedor dinâmico.
        """
        data_str = json.dumps(audit_data, indent=2, ensure_ascii=False)
        evidence_section = f"\n\nAlém dos dados via API, o analista extraiu e anexou as seguintes evidências do Sistema Operacional e arquivos de configuração:\n{os_evidence}\n" if os_evidence else ""
        current_date = datetime.now().strftime("%d/%m/%Y")

        analyst_section = ""
        if analyst_info and any(analyst_info.values()):
            analyst_section = "\nInformações do Analista/Empresa responsável:\n"
            if analyst_info.get('name'): analyst_section += f"- Nome do Analista: {analyst_info['name']}\n"
            if analyst_info.get('company'): analyst_section += f"- Empresa: {analyst_info['company']}\n"
            if analyst_info.get('email'): analyst_section += f"- E-mail: {analyst_info['email']}\n"
            if analyst_info.get('phone'): analyst_section += f"- Telefone: {analyst_info['phone']}\n"
            analyst_section += "\nIMPORTANTE: Adicione estes dados de autoria no cabeçalho principal do relatório Markdown.\n"

        custom_instructions_section = f"\n\nInstruções Adicionais do Analista:\n{custom_instructions}\n" if custom_instructions else ""

        try:
            prompt_template_path = os.path.join('prompts', 'report_template.txt')
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            prompt = prompt_template.format(data_str=data_str, evidence_section=evidence_section, current_date=current_date, analyst_section=analyst_section, custom_instructions_section=custom_instructions_section)
        except FileNotFoundError:
            raise FileNotFoundError("Arquivo de template de prompt 'prompts/report_template.txt' não encontrado.")

        if self.auth_mode == "cli":
            yield from ai_cli_client.generate_via_cli(self.provider, prompt, self.cli_model_override)
            return

        if self.provider == "Google Gemini":
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown e cite dados exatos do JSON fornecido."
                )
            )
            for chunk in response:
                yield chunk.text
            
        elif self.provider == "OpenAI":
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(model=model_name, messages=[{"role": "system", "content": "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown e cite dados exatos do JSON fornecido."}, {"role": "user", "content": prompt}], stream=True)
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content
            
        elif self.provider == "Anthropic":
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system="Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown e cite dados exatos do JSON fornecido.",
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            for event in response:
                if event.type == "content_block_delta":
                    yield event.delta.text
            
        elif self.provider == "Ollama":
            base_url = self.api_key.rstrip('/')
            if not base_url: base_url = "http://localhost:11434"
            payload = {
                "model": model_name,
                "system": "Você atua como um Arquiteto e Analista Sênior de Monitoramento focado em Zabbix. Formate a saída em Markdown e cite dados exatos do JSON fornecido.",
                "prompt": prompt,
                "stream": True
            }
            resp = requests.post(f"{base_url}/api/generate", json=payload, stream=True, timeout=300)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line.decode('utf-8'))
                    yield data.get("response", "")