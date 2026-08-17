"""Immutable input snapshots shared by the GUI and the controller.

The GUI builds these objects on Tk's main thread.  Workers can then consume the
plain Python values without touching widgets or mutable view state.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


SUPPORTED_AI_PROVIDERS = frozenset({"Google Gemini", "OpenAI", "Anthropic", "Ollama"})
SUPPORTED_AI_AUTH_MODES = frozenset({"api_key", "cli"})
INVALID_MODEL_LABELS = frozenset({
    "carregando modelos...",
    "aguardando validação",
    "falha na conexão",
    "nenhum modelo",
    "nenhum modelo compatível",
    "insira a api key primeiro...",
    "(modelo padrão da cli)",
})


@dataclass(frozen=True)
class ZabbixConfig:
    url: str
    auth_method: str
    username: str = ""
    password: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    verify_ssl: bool = True

    def validation_error(self) -> Optional[str]:
        if not self.url:
            return "ERRO: Preencha a URL do Zabbix na aba 'Configurações' antes de iniciar."
        if self.auth_method == "token" and not self.token:
            return "ERRO: Informe o API Token do Zabbix."
        if self.auth_method == "user_pass" and not all((self.username, self.password)):
            return "ERRO: Informe Usuário e Senha do Zabbix."
        return None


@dataclass(frozen=True)
class AIConfig:
    provider: str
    api_key: str = field(default="", repr=False)
    model: str = ""
    auth_mode: str = "api_key"
    cli_model_override: str = ""

    def validation_error(self) -> Optional[str]:
        if self.provider not in SUPPORTED_AI_PROVIDERS:
            return "ERRO: Selecione um provedor de IA válido."
        if self.auth_mode not in SUPPORTED_AI_AUTH_MODES:
            return "ERRO: Selecione um modo de autenticação de IA válido."
        if self.auth_mode == "cli":
            return None
        if not self.api_key:
            return "ERRO: Informe a API Key ou URL do provedor de IA."
        normalized_model = self.model.strip().casefold()
        if (
            not normalized_model
            or normalized_model in INVALID_MODEL_LABELS
            or normalized_model.startswith("conectando à ")
        ):
            return "ERRO: Aguarde e selecione um modelo de IA válido."
        return None


@dataclass(frozen=True)
class AnalystData:
    name: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""

    def as_dict(self):
        return {
            "name": self.name,
            "company": self.company,
            "email": self.email,
            "phone": self.phone,
        }


@dataclass(frozen=True)
class CollectionLimits:
    history_limit: int
    sample_limit: int
    template_limit: int
    only_used_templates: bool


@dataclass(frozen=True)
class ReportStyle:
    chart_type: str
    chart_color: str
    chart_bg_color: str
    chart_text_color: str
    chart_width: int
    chart_height: int
    chart_font: str


@dataclass(frozen=True)
class AuditRequest:
    zabbix: ZabbixConfig
    ai: AIConfig
    analyst: AnalystData
    limits: CollectionLimits
    style: ReportStyle
    custom_instructions: str = ""
    attached_files: Tuple[str, ...] = ()
    anonymize: bool = True
    use_cache: bool = False
    data_file: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "attached_files", tuple(self.attached_files))

    def validation_error(self) -> Optional[str]:
        ai_error = self.ai.validation_error()
        if ai_error:
            return ai_error
        if self.data_file is None and not self.use_cache:
            return self.zabbix.validation_error()
        return None


@dataclass(frozen=True)
class CollectionRequest:
    zabbix: ZabbixConfig
    limits: CollectionLimits
    output_file: str
    anonymize: bool = True

    def validation_error(self) -> Optional[str]:
        return self.zabbix.validation_error()
