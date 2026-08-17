"""Validated, atomic persistence for settings and collected-audit cache."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from core.paths import AppPaths


CACHE_SCHEMA_VERSION = 1
MAX_CACHE_BYTES = 12 * 1024 * 1024

_BOOL_DEFAULTS = {
    "zabbix_ignore_ssl": False,
    "only_used_templates": False,
    "anonymize_data": True,
}
_INT_DEFAULTS = {
    "chart_width": (800, 200, 5000),
    "chart_height": (400, 200, 5000),
    "history_limit": (500, 1, 50_000),
    "sample_limit": (15, 1, 1_000),
    "template_limit": (200, 1, 10_000),
}
_STRING_LIMITS = {
    "zabbix_url": 4096,
    "zabbix_user": 512,
    "ai_account": 128,
    "analyst_name": 512,
    "analyst_company": 512,
    "analyst_email": 512,
    "analyst_phone": 128,
    "chart_font": 512,
    "chart_color": 128,
    "chart_bg_color": 128,
    "chart_text_color": 128,
    "custom_instructions": 100_000,
    "last_log_dir": 4096,
    "last_report_dir": 4096,
    "last_collect_dir": 4096,
}
_CHOICE_DEFAULTS = {
    "zabbix_auth_method": ("user_pass", {"user_pass", "token"}),
    "chart_type": ("Linha", {"Linha", "Barra", "Pizza"}),
}
_SENSITIVE_SETTINGS_KEYS = frozenset({"zabbix_pass", "zabbix_token", "api_keys"})


def _warning(field, detail):
    return f"Configuração '{field}' inválida ({detail}); usando o valor padrão."


def _normalize_ai_accounts(value, warnings):
    if not isinstance(value, dict):
        warnings.append(_warning("ai_accounts", "deve ser um objeto"))
        return None

    normalized = {}
    for index, (name, account) in enumerate(value.items()):
        if index >= 50:
            warnings.append("Contas de IA além do limite de 50 foram ignoradas.")
            break
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            warnings.append("Uma conta de IA com nome inválido foi ignorada.")
            continue
        if not isinstance(account, dict):
            warnings.append(f"A conta de IA '{name}' foi ignorada por ter formato inválido.")
            continue
        provider = account.get("provider", name)
        auth_mode = account.get("auth_mode", "api_key")
        override = account.get("cli_model_override", "")
        if not isinstance(provider, str) or not provider.strip() or len(provider) > 128:
            warnings.append(f"A conta de IA '{name}' tem provedor inválido e foi ignorada.")
            continue
        if auth_mode not in {"api_key", "cli"}:
            warnings.append(f"A conta de IA '{name}' tinha modo inválido; usando 'api_key'.")
            auth_mode = "api_key"
        if not isinstance(override, str) or len(override) > 256:
            warnings.append(f"A conta de IA '{name}' tinha modelo CLI inválido; usando vazio.")
            override = ""
        normalized[name.strip()] = {
            "provider": provider.strip(),
            "api_key": "",
            "auth_mode": auth_mode,
            "cli_model_override": override.strip(),
        }
    return normalized


def normalize_settings(payload):
    """Return safe settings and warnings; unknown/sensitive fields are dropped."""
    if not isinstance(payload, dict):
        return {}, ["O arquivo de configurações não contém um objeto JSON; usando padrões."]

    normalized = {}
    warnings = []

    for field, (default, minimum, maximum) in _INT_DEFAULTS.items():
        if field not in payload:
            continue
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            normalized[field] = default
            warnings.append(_warning(field, f"inteiro entre {minimum} e {maximum}"))
        else:
            normalized[field] = value

    for field, default in _BOOL_DEFAULTS.items():
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, bool):
            normalized[field] = default
            warnings.append(_warning(field, "deve ser verdadeiro ou falso"))
        else:
            normalized[field] = value

    for field, limit in _STRING_LIMITS.items():
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, str) or len(value) > limit:
            warnings.append(_warning(field, f"texto de até {limit} caracteres"))
        else:
            normalized[field] = value

    for field, (default, choices) in _CHOICE_DEFAULTS.items():
        if field not in payload:
            continue
        value = payload[field]
        if value not in choices:
            normalized[field] = default
            warnings.append(_warning(field, f"opções: {', '.join(sorted(choices))}"))
        else:
            normalized[field] = value

    if "ai_accounts" in payload:
        accounts = _normalize_ai_accounts(payload["ai_accounts"], warnings)
        if accounts is not None:
            normalized["ai_accounts"] = accounts

    known_fields = (
        set(_INT_DEFAULTS)
        | set(_BOOL_DEFAULTS)
        | set(_STRING_LIMITS)
        | set(_CHOICE_DEFAULTS)
        | {"ai_accounts"}
        | _SENSITIVE_SETTINGS_KEYS
    )
    unknown = sorted(str(key) for key in payload if key not in known_fields)
    if unknown:
        warnings.append(
            "Configurações desconhecidas foram ignoradas: " + ", ".join(unknown[:10])
        )
    if any(key in payload for key in _SENSITIVE_SETTINGS_KEYS):
        warnings.append("Credenciais legadas não foram copiadas para o arquivo de configurações.")
    return normalized, warnings


def extract_legacy_credentials(payload):
    """Extract credentials for keyring migration without persisting them again."""
    if not isinstance(payload, dict):
        return {}
    credentials = {}
    for key in ("zabbix_pass", "zabbix_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            credentials[key] = value
    api_keys = payload.get("api_keys")
    if isinstance(api_keys, dict):
        for account, value in api_keys.items():
            if isinstance(account, str) and isinstance(value, str) and value:
                credentials[f"{account}_api_key"] = value
    accounts = payload.get("ai_accounts")
    if isinstance(accounts, dict):
        for account, info in accounts.items():
            if not isinstance(account, str) or not isinstance(info, dict):
                continue
            value = info.get("api_key")
            if isinstance(value, str) and value:
                credentials[f"{account}_api_key"] = value
    return credentials


def _restrict_file_permissions(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _fsync_directory(directory):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_text(path, text):
    """Atomically replace *path* with UTF-8 text in the same directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            _restrict_file_permissions(temporary_name)
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
        _restrict_file_permissions(target)
        _fsync_directory(target.parent)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def atomic_write_json(path, payload, *, indent=None):
    serialized = json.dumps(payload, ensure_ascii=False, indent=indent)
    atomic_write_text(path, serialized)


def _read_json(path, max_bytes):
    source = Path(path)
    if source.stat().st_size > max_bytes:
        raise ValueError(f"O arquivo {source.name} excede o limite permitido.")
    with source.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: dict
    warnings: tuple[str, ...]
    legacy_credentials: dict


class SettingsStore:
    def __init__(self, paths: AppPaths, legacy_file=None):
        self.paths = paths
        self.path = paths.settings_file
        self.legacy_file = Path(legacy_file) if legacy_file is not None else None

    def load(self):
        warnings = []
        legacy_payload = None
        legacy_credentials = {}
        if self.legacy_file is not None and self.legacy_file.exists():
            try:
                legacy_payload = _read_json(self.legacy_file, 2 * 1024 * 1024)
                legacy_credentials = extract_legacy_credentials(legacy_payload)
            except (OSError, ValueError, UnicodeError) as exc:
                warnings.append(f"Configuração legada não pôde ser lida: {exc}")

        source_payload = None
        if self.path.exists():
            try:
                source_payload = _read_json(self.path, 2 * 1024 * 1024)
            except (OSError, ValueError, UnicodeError) as exc:
                warnings.append(f"Configurações não puderam ser lidas: {exc}; usando padrões.")
        elif legacy_payload is not None:
            source_payload = legacy_payload

        settings, validation_warnings = normalize_settings(
            source_payload if source_payload is not None else {}
        )
        warnings.extend(validation_warnings)

        if not self.path.exists() and legacy_payload is not None:
            try:
                self.paths.ensure_config_dir()
                atomic_write_json(self.path, settings, indent=4)
                warnings.append(
                    f"Configurações legadas migradas para {self.path}; o original foi preservado."
                )
            except OSError as exc:
                warnings.append(f"Não foi possível migrar as configurações legadas: {exc}")

        return SettingsLoadResult(settings, tuple(warnings), legacy_credentials)

    def save(self, settings):
        normalized, warnings = normalize_settings(settings)
        self.paths.ensure_config_dir()
        atomic_write_json(self.path, normalized, indent=4)
        return normalized, tuple(warnings)


def _canonical_server_url(url):
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if not hostname:
        return ""
    scheme = parsed.scheme.casefold()
    if port is None or (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        authority = hostname
    else:
        authority = f"{hostname}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{authority}{path}"


def safe_server_name(url):
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except (TypeError, ValueError):
        return "servidor-desconhecido"
    if not hostname:
        return "servidor-desconhecido"
    if port is not None:
        return f"{hostname}:{port}"[:255]
    return hostname[:255]


def server_fingerprint(url):
    canonical = _canonical_server_url(url)
    if not canonical:
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class CacheRecord:
    data: dict
    created_at_utc: str
    server_name: str
    server_fingerprint: str | None
    zabbix_version: str | None
    anonymized: bool
    warnings: tuple
    migrated_from: str | None = None

    def summary(self):
        return {
            "created_at_utc": self.created_at_utc,
            "server_name": self.server_name,
            "server_fingerprint": self.server_fingerprint,
            "zabbix_version": self.zabbix_version,
            "anonymized": self.anonymized,
            "warnings_count": len(self.warnings),
        }


def build_cache_envelope(data, source_url, anonymized):
    if not isinstance(data, dict):
        raise ValueError("Os dados do cache devem ser um objeto JSON.")
    collection_metadata = data.get("_collection_metadata")
    if not isinstance(collection_metadata, dict):
        collection_metadata = {}
    warnings = collection_metadata.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "server": {
            "name": safe_server_name(source_url),
            "fingerprint": server_fingerprint(source_url),
        },
        "zabbix_version": collection_metadata.get("zabbix_version"),
        "anonymized": bool(anonymized),
        "warnings": warnings,
        "data": data,
    }


def parse_cache_envelope(payload, migrated_from=None):
    if not isinstance(payload, dict):
        raise ValueError("O cache deve conter um objeto JSON.")
    if payload.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
        raise ValueError(
            f"Versão de cache não suportada: {payload.get('cache_schema_version')!r}."
        )
    data = payload.get("data")
    server = payload.get("server")
    if not isinstance(data, dict) or not isinstance(server, dict):
        raise ValueError("O envelope do cache está incompleto.")
    created_at = payload.get("created_at_utc")
    name = server.get("name")
    fingerprint = server.get("fingerprint")
    anonymized = payload.get("anonymized")
    warnings = payload.get("warnings", [])
    if not isinstance(created_at, str) or not isinstance(name, str):
        raise ValueError("Os metadados de origem/data do cache são inválidos.")
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
    except ValueError:
        raise ValueError("A data UTC do cache é inválida.") from None
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() != timedelta(0):
        raise ValueError("A data do cache deve incluir timezone UTC.")
    if not name or len(name) > 255 or any(ord(character) < 32 for character in name):
        raise ValueError("O nome seguro do servidor no cache é inválido.")
    if fingerprint is not None and (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 24
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("O fingerprint do cache é inválido.")
    if not isinstance(anonymized, bool) or not isinstance(warnings, list):
        raise ValueError("Os metadados de anonimização/warnings do cache são inválidos.")
    version = payload.get("zabbix_version")
    if version is not None and (not isinstance(version, str) or len(version) > 64):
        raise ValueError("A versão Zabbix do cache é inválida.")
    return CacheRecord(
        data=data,
        created_at_utc=created_at,
        server_name=name,
        server_fingerprint=fingerprint,
        zabbix_version=version,
        anonymized=anonymized,
        warnings=tuple(warnings),
        migrated_from=migrated_from,
    )


class CacheStore:
    def __init__(self, paths: AppPaths, legacy_file=None):
        self.paths = paths
        self.path = paths.audit_cache_file
        self.legacy_file = Path(legacy_file) if legacy_file is not None else None

    def save(self, data, source_url, anonymized):
        envelope = build_cache_envelope(data, source_url, anonymized)
        self.paths.ensure_cache_dir()
        atomic_write_json(self.path, envelope)
        return parse_cache_envelope(envelope)

    def load(self, source_url_for_legacy=""):
        if self.path.exists():
            payload = _read_json(self.path, MAX_CACHE_BYTES)
            return parse_cache_envelope(payload)

        if self.legacy_file is None or not self.legacy_file.exists():
            raise FileNotFoundError("Nenhum cache de auditoria foi encontrado.")

        legacy_payload = _read_json(self.legacy_file, MAX_CACHE_BYTES)
        if not isinstance(legacy_payload, dict):
            raise ValueError("O cache legado deve conter um objeto JSON.")
        metadata = legacy_payload.get("_collection_metadata")
        anonymized = bool(metadata.get("anonymized")) if isinstance(metadata, dict) else False
        # A raw legacy cache never recorded a trustworthy origin.  Do not assign
        # the currently configured URL to historical data: an unknown fingerprint
        # deliberately forces consent on its first reuse.
        envelope = build_cache_envelope(legacy_payload, "", anonymized)
        self.paths.ensure_cache_dir()
        atomic_write_json(self.path, envelope)
        return parse_cache_envelope(envelope, migrated_from=str(self.legacy_file))


def cache_mismatch_reasons(record, current_url, requested_anonymization):
    reasons = []
    current_fingerprint = server_fingerprint(current_url)
    if current_fingerprint is None:
        reasons.append("o servidor atual não está informado e a origem não pode ser comparada")
    elif record.server_fingerprint is None:
        reasons.append("a origem do cache legado não pôde ser confirmada")
    elif current_fingerprint != record.server_fingerprint:
        reasons.append("o servidor configurado é diferente da origem do cache")
    if bool(requested_anonymization) != record.anonymized:
        reasons.append("a opção atual de anonimização difere da usada na coleta em cache")
    return tuple(reasons)
