import json
from google import genai
from google.genai import types
import os
import openai
import anthropic
import httpx
import requests
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from api import ai_cli_client
from api.ai_prompts import AIStreamEvent, SYSTEM_PROMPT
from core.operation import OperationCancelled
from core.paths import resource_path


class AIClient:
    GEMINI_TIMEOUT_MS = 300_000
    OPENAI_TIMEOUT_SECONDS = 300
    ANTHROPIC_TIMEOUT_SECONDS = 300
    OLLAMA_TIMEOUT_SECONDS = 300
    DEFAULT_ANTHROPIC_MAX_TOKENS = 8_192
    MAX_RETRIES = 2
    RETRY_BACKOFF_SECONDS = 1.0
    TRANSIENT_STATUS_CODES = frozenset({408, 429})
    ANTHROPIC_FALLBACK_MODELS = (
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    )

    def __init__(
        self,
        provider,
        api_key,
        auth_mode="api_key",
        cli_model_override=None,
        anthropic_max_tokens=DEFAULT_ANTHROPIC_MAX_TOKENS,
    ):
        self.provider = provider
        self.api_key = api_key
        self.auth_mode = auth_mode
        self.cli_model_override = cli_model_override
        self.anthropic_max_tokens = max(1, int(anthropic_max_tokens))
        self.model_discovery_warning = None

    @staticmethod
    def _event_reason(value, default="stop"):
        if value is None:
            return default
        return str(getattr(value, "value", value)).lower()

    @staticmethod
    def _is_partial_reason(reason):
        return reason in {"length", "max_tokens", "max_token", "error"}

    @classmethod
    def _response_status_code(cls, error):
        response = getattr(error, "response", None)
        for candidate in (response, error):
            status_code = getattr(candidate, "status_code", None)
            if status_code is None:
                status_code = getattr(candidate, "status", None)
            if status_code is None:
                status_code = getattr(candidate, "code", None)
            try:
                return int(status_code)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _retry_after_seconds(cls, error):
        """Return a server-requested delay, if a usable Retry-After exists."""
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None

        retry_after = None
        try:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
        except AttributeError:
            return None
        if retry_after is None:
            return None

        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass

        try:
            retry_at = parsedate_to_datetime(str(retry_after))
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    @classmethod
    def _is_retryable_error(cls, error):
        """Identify the transport failures safe to repeat before streaming starts."""
        status_code = cls._response_status_code(error)
        if status_code in cls.TRANSIENT_STATUS_CODES or 500 <= (status_code or 0) <= 599:
            return True

        connection_errors = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            httpx.TimeoutException,
            httpx.ConnectError,
            TimeoutError,
            ConnectionError,
        )
        if isinstance(error, connection_errors):
            return True

        # google-genai, OpenAI and Anthropic wrap their HTTP client exceptions
        # differently across SDK versions.  Their connection/timeout classes
        # consistently retain these names, so this keeps the policy uniform
        # without depending on a private SDK implementation detail.
        return error.__class__.__name__ in {"APIConnectionError", "APITimeoutError"}

    @staticmethod
    def _close_stream(stream):
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # A cleanup error must not replace the terminal event that
                # describes the provider's actual streaming result.
                pass

    @staticmethod
    def _raise_if_cancelled(is_cancelled):
        if is_cancelled and is_cancelled():
            raise OperationCancelled("Operação cancelada pelo usuário.")

    def _retry_delay(self, attempt, error):
        retry_after = self._retry_after_seconds(error)
        if retry_after is not None:
            return retry_after
        return self.RETRY_BACKOFF_SECONDS * (2 ** attempt)

    def _wait_before_retry(self, delay, is_cancelled):
        """Wait for the retry deadline without making cancellation unresponsive."""
        if is_cancelled is None:
            time.sleep(delay)
            return

        remaining = max(0.0, delay)
        while remaining > 0:
            self._raise_if_cancelled(is_cancelled)
            interval = min(0.1, remaining)
            time.sleep(interval)
            remaining -= interval
        self._raise_if_cancelled(is_cancelled)

    def _stream_provider_events(self, stream_factory, event_parser, is_cancelled=None):
        """Emit one provider stream, retrying only if no text has been emitted.

        A restarted streamed generation cannot be merged safely after text has
        reached the report: the provider may begin the answer again.  Therefore
        all automatic retries happen before the first text chunk only.
        """
        terminal_reason = None
        text_emitted = False
        for attempt in range(self.MAX_RETRIES + 1):
            stream = None
            try:
                self._raise_if_cancelled(is_cancelled)
                stream = stream_factory()
                for payload in stream:
                    self._raise_if_cancelled(is_cancelled)
                    text, reason = event_parser(payload)
                    if text:
                        text_emitted = True
                        yield AIStreamEvent.text_chunk(text)
                    if reason:
                        terminal_reason = self._event_reason(reason)
                break
            except OperationCancelled:
                raise
            except Exception as exc:
                can_retry = (
                    not text_emitted
                    and attempt < self.MAX_RETRIES
                    and self._is_retryable_error(exc)
                )
                if not can_retry:
                    yield AIStreamEvent.final("error", partial=True, error=str(exc))
                    return
                self._wait_before_retry(self._retry_delay(attempt, exc), is_cancelled)
            finally:
                if stream is not None:
                    self._close_stream(stream)

        terminal_reason = terminal_reason or "stop"
        yield AIStreamEvent.final(
            terminal_reason,
            partial=self._is_partial_reason(terminal_reason),
        )

    def get_available_models(self):
        """Busca os modelos disponíveis baseados no provedor escolhido."""
        self.model_discovery_warning = None
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
                try:
                    client = anthropic.Anthropic(
                        api_key=self.api_key,
                        timeout=self.ANTHROPIC_TIMEOUT_SECONDS,
                        max_retries=0,
                    )
                    response = client.models.list()
                    models = sorted(
                        {
                            model.id
                            for model in getattr(response, "data", response)
                            if getattr(model, "id", None)
                        }
                    )
                    if models:
                        return models
                    raise ValueError("a API retornou uma lista vazia")
                except Exception as error:
                    self.model_discovery_warning = (
                        "A listagem online da Anthropic falhou; exibindo uma "
                        f"lista de fallback limitada ({error})."
                    )
                    return list(self.ANTHROPIC_FALLBACK_MODELS)
                
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

    def generate_audit_report(
        self,
        audit_data,
        model_name,
        os_evidence="",
        analyst_info=None,
        custom_instructions="",
        is_cancelled=None,
    ):
        """
        Gera o relatório com o provedor dinâmico.
        """
        data_str = json.dumps(audit_data, indent=2, ensure_ascii=False)
        evidence_section = (
            "\n<evidencias_nao_confiaveis>\n"
            f"{os_evidence}\n"
            "</evidencias_nao_confiaveis>\n"
            if os_evidence else ""
        )
        current_date = datetime.now().strftime("%d/%m/%Y")

        analyst_section = ""
        if analyst_info and any(analyst_info.values()):
            analyst_section = "\nInformações do Analista/Empresa responsável:\n"
            if analyst_info.get('name'): analyst_section += f"- Nome do Analista: {analyst_info['name']}\n"
            if analyst_info.get('company'): analyst_section += f"- Empresa: {analyst_info['company']}\n"
            if analyst_info.get('email'): analyst_section += f"- E-mail: {analyst_info['email']}\n"
            if analyst_info.get('phone'): analyst_section += f"- Telefone: {analyst_info['phone']}\n"
            analyst_section += "\nIMPORTANTE: Adicione estes dados de autoria no cabeçalho principal do relatório Markdown.\n"

        custom_instructions_section = (
            "\n<instrucoes_adicionais_do_analista>\n"
            f"{custom_instructions}\n"
            "</instrucoes_adicionais_do_analista>\n"
            if custom_instructions else ""
        )

        try:
            prompt_template_path = resource_path(os.path.join('prompts', 'report_template.txt'))
            with open(prompt_template_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            prompt = prompt_template.format(data_str=data_str, evidence_section=evidence_section, current_date=current_date, analyst_section=analyst_section, custom_instructions_section=custom_instructions_section)
        except FileNotFoundError:
            raise FileNotFoundError("Arquivo de template de prompt 'prompts/report_template.txt' não encontrado.")

        if self.auth_mode == "cli":
            yield from ai_cli_client.generate_via_cli(
                self.provider,
                prompt,
                self.cli_model_override,
                is_cancelled=is_cancelled,
            )
            return

        if self.provider == "Google Gemini":
            def create_stream():
                client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(
                        timeout=self.GEMINI_TIMEOUT_MS,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
                return client.models.generate_content_stream(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
                )

            def parse_chunk(chunk):
                candidates = getattr(chunk, "candidates", None) or []
                reason = getattr(candidates[0], "finish_reason", None) if candidates else None
                return getattr(chunk, "text", None), reason

            yield from self._stream_provider_events(create_stream, parse_chunk, is_cancelled)
            
        elif self.provider == "OpenAI":
            def create_stream():
                client = openai.OpenAI(
                    api_key=self.api_key,
                    timeout=self.OPENAI_TIMEOUT_SECONDS,
                    max_retries=0,
                )
                return client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    stream=True,
                )

            def parse_chunk(chunk):
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    return None, None
                choice = choices[0]
                return (
                    getattr(getattr(choice, "delta", None), "content", None),
                    getattr(choice, "finish_reason", None),
                )

            yield from self._stream_provider_events(create_stream, parse_chunk, is_cancelled)
            
        elif self.provider == "Anthropic":
            def create_stream():
                client = anthropic.Anthropic(
                    api_key=self.api_key,
                    timeout=self.ANTHROPIC_TIMEOUT_SECONDS,
                    max_retries=0,
                )
                return client.messages.create(
                    model=model_name,
                    max_tokens=self.anthropic_max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                )

            def parse_event(event):
                if getattr(event, "type", None) == "content_block_delta":
                    return getattr(getattr(event, "delta", None), "text", None), None
                if getattr(event, "type", None) == "message_delta":
                    return None, getattr(getattr(event, "delta", None), "stop_reason", None)
                return None, getattr(event, "stop_reason", None)

            yield from self._stream_provider_events(create_stream, parse_event, is_cancelled)
            
        elif self.provider == "Ollama":
            base_url = self.api_key.rstrip('/')
            if not base_url: base_url = "http://localhost:11434"
            payload = {
                "model": model_name,
                "system": SYSTEM_PROMPT,
                "prompt": prompt,
                "stream": True
            }
            def create_stream():
                response = requests.post(
                    f"{base_url}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=self.OLLAMA_TIMEOUT_SECONDS,
                )
                response.raise_for_status()

                def lines():
                    try:
                        yield from response.iter_lines()
                    finally:
                        response.close()

                return lines()

            def parse_line(line):
                if not line:
                    return None, None
                data = json.loads(line.decode("utf-8"))
                reason = data.get("done_reason") if data.get("done") else None
                return data.get("response"), reason

            yield from self._stream_provider_events(create_stream, parse_line, is_cancelled)
        else:
            yield AIStreamEvent.final(
                "error", partial=True, error=f"Provedor desconhecido: {self.provider}."
            )
