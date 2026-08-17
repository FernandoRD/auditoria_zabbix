import threading
import ipaddress
import re
from functools import partial
from api import zabbix_api, ai_api
from api.ai_prompts import AIStreamEvent
import json
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlsplit

from core.anonymizer import Anonymizer
from core.operation import OperationCancelled, OperationContext
from core.paths import get_app_paths
from core.persistence import (
    CacheStore,
    atomic_write_json,
    cache_mismatch_reasons,
    parse_cache_envelope,
)
from core.run_config import AIConfig, AuditRequest, CollectionLimits, CollectionRequest, ZabbixConfig


_SENSITIVE_URL_PARAMETERS = frozenset({
    "password", "passwd", "senha", "pwd", "token", "authorization",
    "api_token", "api_key",
})
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?(?:\"[^\"]*\"|'[^']*'|\S+)"
)
_SENSITIVE_FIELD_VALUE = re.compile(
    r"(?i)(\b(?:password|passwd|senha|pwd|token|api[_-]?key)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|\S+)"
)


def validate_zabbix_url(url: str) -> Optional[str]:
    """Return a user-safe validation error for a Zabbix endpoint, if any.

    This deliberately performs no I/O.  Credentials in a URL are refused so
    they cannot accidentally be copied into connection logs.
    """
    if not isinstance(url, str) or not url.strip():
        return "ERRO: Preencha a URL do Zabbix na aba 'Configurações' antes de iniciar."
    if url != url.strip():
        return "ERRO: A URL do Zabbix não pode começar ou terminar com espaços."

    try:
        parsed = urlsplit(url)
        # Accessing ``port`` makes urllib reject malformed port values too.
        parsed.port
    except ValueError:
        return "ERRO: A URL do Zabbix é inválida."

    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return "ERRO: Use uma URL HTTP ou HTTPS válida para o Zabbix."
    if parsed.username is not None or parsed.password is not None:
        return "ERRO: Informe usuário, senha ou token nos campos próprios, nunca na URL."
    if parsed.fragment:
        return "ERRO: A URL do Zabbix não deve conter fragmentos (#...)."
    if any(
        name.casefold() in _SENSITIVE_URL_PARAMETERS
        for name, _value in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        return "ERRO: Informe credenciais nos campos próprios, nunca nos parâmetros da URL."
    return None


def _is_local_zabbix_host(hostname: str) -> bool:
    """Return whether a parsed Zabbix hostname refers to the local machine."""
    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def insecure_zabbix_transport_warnings(config: ZabbixConfig) -> tuple[str, ...]:
    """Return consent reasons for an already-valid endpoint without side effects."""
    parsed = urlsplit(config.url)
    warnings = []
    if parsed.scheme.casefold() == "http" and not _is_local_zabbix_host(parsed.hostname):
        warnings.append("remote_http")
    if parsed.scheme.casefold() == "https" and not config.verify_ssl:
        warnings.append("unverified_tls")
    return tuple(warnings)


def redact_zabbix_log_message(message, config: ZabbixConfig) -> str:
    """Remove Zabbix credentials from a message before it reaches the GUI log."""
    sanitized = str(message)
    for secret in (config.password, config.token):
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = _AUTHORIZATION_VALUE.sub("[REDACTED CREDENTIAL]", sanitized)
    return _SENSITIVE_FIELD_VALUE.sub(r"\1[REDACTED]", sanitized)

class Controller:
    MAX_AUDIT_JSON_BYTES = 10 * 1024 * 1024
    MAX_ATTACHMENTS = 10
    MAX_ATTACHMENT_BYTES = 1 * 1024 * 1024
    MAX_TOTAL_ATTACHMENT_BYTES = 5 * 1024 * 1024

    def __init__(self, view, cache_store=None):
        self.view = view
        self.cache_store = cache_store or CacheStore(
            get_app_paths(), legacy_file=Path.cwd() / "last_audit_cache.json"
        )
        self._operation_lock = threading.Lock()
        self._active_operation: Optional[OperationContext] = None
        self._model_load_lock = threading.Lock()
        self._model_load_id = 0
        self.load_models_async(self.view.build_ai_config())

    @property
    def active_operation(self):
        """Expose the current immutable identity for diagnostics and tests."""
        with self._operation_lock:
            return self._active_operation

    def _start_operation(self, worker: Callable, request, starting_log: str) -> bool:
        """Atomically reserve the single operation slot and launch its worker."""
        with self._operation_lock:
            if self._active_operation is not None:
                self.view.log("Já existe uma operação em andamento. Aguarde seu término.", "warning")
                return False
            context = OperationContext()
            thread = threading.Thread(target=worker, args=(request, context), daemon=True)
            context.attach_thread(thread)
            self._active_operation = context
            context.mark_running()
            # Queue this before cancellation can observe the active context, so
            # a concurrent cancellation cannot be overwritten by "running".
            self.view.set_operation_state("running")

        self.view.select_logs_tab()
        self.view.log(starting_log)
        try:
            thread.start()
        except Exception as exc:
            self.view.log(f"Não foi possível iniciar a operação: {exc}", "danger")
            self._finish_operation(context)
            return False
        return True

    def _finish_operation(self, context: OperationContext) -> None:
        """Release UI ownership only if this exact operation still owns it."""
        should_enable_ui = False
        with self._operation_lock:
            if (
                self._active_operation is not None
                and self._active_operation.id == context.id
            ):
                context.mark_finished()
                self._active_operation = None
                should_enable_ui = True
        if should_enable_ui:
            self.view.set_operation_state("idle")

    @staticmethod
    def _standalone_context() -> OperationContext:
        """Support focused synchronous worker tests without claiming UI ownership."""
        context = OperationContext()
        context.mark_running()
        return context

    @staticmethod
    def _zabbix_validation_error(config: ZabbixConfig) -> Optional[str]:
        """Validate credentials and endpoint before a transport operation starts."""
        return config.validation_error() or validate_zabbix_url(config.url)

    def _confirm_insecure_zabbix_transport(self, config: ZabbixConfig) -> bool:
        """Ask for consent on the GUI thread before sending Zabbix credentials."""
        warnings = insecure_zabbix_transport_warnings(config)
        if not warnings:
            return True
        if self.view.confirm_insecure_zabbix_transport(warnings):
            return True
        self.view.log(
            "Conexão com Zabbix cancelada: transporte inseguro sem confirmação.",
            "warning",
        )
        return False

    def load_models_async(self, ai_config: AIConfig):
        """Inicia a busca pelos modelos na IA escolhida."""
        with self._model_load_lock:
            self._model_load_id += 1
            load_id = self._model_load_id

        validation_error = None
        if not ai_config.provider:
            validation_error = "Selecione uma conta/provedor de IA."
        elif ai_config.auth_mode not in {"api_key", "cli"}:
            validation_error = "Modo de autenticação de IA inválido."
        if validation_error:
            self.view.set_model_state("error", (), None, validation_error, load_id)
            return

        if ai_config.auth_mode == "cli":
            override = ai_config.cli_model_override
            models = (override,) if override else ()
            message = override or "Modelo padrão da CLI"
            self.view.set_model_state("ready", models, override or None, message, load_id)
            return

        if not ai_config.api_key:
            self.view.set_model_state(
                "idle", (), None, "Informe a API Key ou URL do provedor", load_id
            )
            return

        self.view.set_model_state(
            "loading", (), None, f"Conectando à {ai_config.provider}...", load_id
        )
        thread = threading.Thread(
            target=self._fetch_and_update_models, args=(ai_config, load_id)
        )
        thread.daemon = True
        thread.start()

    def _model_load_is_current(self, load_id):
        with self._model_load_lock:
            return load_id == self._model_load_id

    def _fetch_and_update_models(self, ai_config: AIConfig, load_id: int):
        try:
            client = ai_api.AIClient(ai_config.provider, ai_config.api_key)
            models = client.get_available_models()
            if not self._model_load_is_current(load_id):
                return
            warning = getattr(client, "model_discovery_warning", None)
            if warning:
                self.view.log(warning, "warning")
            if not models:
                self.view.set_model_state(
                    "error", (), None, "Nenhum modelo compatível encontrado", load_id
                )
                return
            default = next(
                (
                    model
                    for model in models
                    if "pro" in model.lower()
                    or "gpt-4" in model.lower()
                    or "o1" in model.lower()
                    or "sonnet" in model.lower()
                ),
                models[0],
            )
            self.view.set_model_state("ready", tuple(models), default, "", load_id)
        except Exception as e:
            if not self._model_load_is_current(load_id):
                return
            self.view.log(f"Aviso: Não foi possível carregar modelos online: {e}", "warning")
            self.view.set_model_state("error", (), None, "Falha na conexão", load_id)

    def test_zabbix_connection(self, zabbix_config: ZabbixConfig):
        validation_error = self._zabbix_validation_error(zabbix_config)
        if validation_error:
            self.view.log(validation_error, "danger")
            return
        if not self._confirm_insecure_zabbix_transport(zabbix_config):
            return
        self.view.update_progress(0, "Testando conexão...")
        self._start_operation(
            self._test_zabbix_flow,
            zabbix_config,
            f"Testando conexão com o Zabbix em {zabbix_config.url}...",
        )

    def _test_zabbix_flow(self, config: ZabbixConfig, operation: Optional[OperationContext] = None):
        managed_operation = operation is not None
        operation = operation or self._standalone_context()
        zabbix = None
        try:
            logger = lambda msg: self.view.log(
                redact_zabbix_log_message(msg, config), "warning"
            )
            if config.auth_method == "token":
                zabbix = zabbix_api.ZabbixClient(config.url, token=config.token, verify_ssl=config.verify_ssl, logger=logger)
            else:
                zabbix = zabbix_api.ZabbixClient(
                    config.url,
                    user=config.username,
                    password=config.password,
                    verify_ssl=config.verify_ssl,
                    logger=logger,
                )
                
            operation.raise_if_cancelled()
            version = zabbix.discover_version()
            if not version:
                raise Exception("Não foi possível detectar a versão via API.")
            operation.raise_if_cancelled()
            zabbix.authenticate()
            operation.raise_if_cancelled()
            if not operation.begin_completion():
                raise OperationCancelled("Operação cancelada ao concluir o teste.")
            self.view.log(f"✅ Conexão bem-sucedida! Versão do Zabbix: {version}")
            self.view.update_progress(100, "Conexão Zabbix OK!")
            self.view.show_dialog("Teste de Conexão", f"Conexão com Zabbix bem-sucedida!\nVersão detectada: {version}")
        except OperationCancelled:
            self.view.log("Operação cancelada pelo usuário.", "warning")
            self.view.update_progress(0, "Operação Cancelada.")
        except Exception as e:
            safe_error = redact_zabbix_log_message(e, config)
            self.view.log(f"❌ Falha na conexão com Zabbix: {safe_error}", "danger")
            self.view.update_progress(0, "Falha na conexão Zabbix.")
            self.view.show_dialog(
                "Falha de Conexão",
                f"Não foi possível conectar ao Zabbix:\n{safe_error}",
                is_error=True,
            )
        finally:
            try:
                if zabbix is not None:
                    zabbix.close()
            finally:
                if managed_operation:
                    self._finish_operation(operation)

    def cancel_audit(self):
        """Signal only the currently active operation; its finally owns cleanup."""
        with self._operation_lock:
            operation = self._active_operation
        if operation is None or not operation.request_cancel():
            return False
        self.view.log("Aviso: Cancelamento solicitado pelo usuário.", "warning")
        self.view.update_progress(0, "Cancelando...")
        self.view.set_operation_state("cancelling")
        return True

    def _anonymize_text(self, text):
        """Compatibility wrapper for callers that redact one standalone text."""
        return Anonymizer().redact_text(text)

    @classmethod
    def _load_audit_json(cls, filepath):
        """Load only a bounded, supported audit JSON document from disk."""
        path = Path(filepath)
        if path.stat().st_size > cls.MAX_AUDIT_JSON_BYTES:
            raise ValueError(
                "O arquivo JSON excede o limite de 10 MiB aceito para auditoria."
            )
        with path.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
        if isinstance(payload, dict) and "cache_schema_version" in payload:
            payload = parse_cache_envelope(payload).data
        return cls._validate_audit_payload(payload)

    @staticmethod
    def _validate_audit_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("O JSON de auditoria deve ter um objeto na raiz.")
        metadata = payload.get("_collection_metadata")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValueError("Os metadados da coleta devem ser um objeto JSON.")
            schema_version = metadata.get("schema_version")
            if schema_version is not None and schema_version != 1:
                raise ValueError(
                    f"Versão de schema de coleta não suportada: {schema_version!r}."
                )
        return payload

    def _read_attached_evidence(self, filepaths, operation, anonymizer=None):
        """Read bounded text attachments without exposing their local paths.

        The delimiters are part of the prompt's data boundary.  Names are kept
        solely for traceability; absolute paths never leave this process.
        """
        evidence_parts = []
        total_read = 0
        for index, filepath in enumerate(filepaths):
            operation.raise_if_cancelled()
            display_name = Path(filepath).name or "anexo"
            if index >= self.MAX_ATTACHMENTS:
                self.view.log(
                    f"Aviso: anexos além do limite de {self.MAX_ATTACHMENTS} foram ignorados.",
                    "warning",
                )
                break
            remaining = self.MAX_TOTAL_ATTACHMENT_BYTES - total_read
            if remaining <= 0:
                self.view.log(
                    "Aviso: limite total de anexos atingido; os demais foram ignorados.",
                    "warning",
                )
                break
            allowed = min(self.MAX_ATTACHMENT_BYTES, remaining)
            try:
                with Path(filepath).open("rb") as file_handle:
                    content_bytes = file_handle.read(allowed + 1)
            except OSError:
                self.view.log(
                    f"Aviso: não foi possível ler o anexo {display_name}.", "warning"
                )
                continue

            truncated = len(content_bytes) > allowed
            content_bytes = content_bytes[:allowed]
            total_read += len(content_bytes)
            content = content_bytes.decode("utf-8", errors="replace")
            if anonymizer is not None:
                content = anonymizer.redact_text(content)
            if truncated:
                self.view.log(
                    f"Aviso: o anexo {display_name} foi truncado em {allowed} bytes.",
                    "warning",
                )
            evidence_parts.extend(
                (
                    f"\n--- INÍCIO DO ANEXO: {display_name} ---\n",
                    content,
                    f"\n--- FIM DO ANEXO: {display_name} ---\n",
                )
            )
            operation.raise_if_cancelled()
        return "".join(evidence_parts)

    def start_audit(self, request: AuditRequest):
        """Inicia o processo de auditoria em uma nova thread para não travar a GUI."""
        validation_error = request.validation_error()
        if validation_error:
            self.view.log(validation_error, "danger")
            return
        if request.data_file is None and not request.use_cache:
            validation_error = self._zabbix_validation_error(request.zabbix)
            if validation_error:
                self.view.log(validation_error, "danger")
                return
            if not self._confirm_insecure_zabbix_transport(request.zabbix):
                return
        cache_record = None
        worker = self.run_audit_flow
        if request.use_cache:
            try:
                cache_record = self.cache_store.load(request.zabbix.url)
                self._validate_audit_payload(cache_record.data)
            except Exception as exc:
                self.view.log(f"Erro: Não foi possível carregar o cache local: {exc}", "danger")
                return

            summary = cache_record.summary()
            self.view.log(
                "Cache selecionado: origem "
                f"{summary['server_name']}, criado em {summary['created_at_utc']}, "
                f"Zabbix {summary['zabbix_version'] or 'desconhecido'}, "
                f"anonimizado={'sim' if summary['anonymized'] else 'não'}.",
                "info",
            )
            if cache_record.migrated_from:
                self.view.log(
                    "Cache legado migrado para o diretório de cache do usuário; "
                    "o arquivo original foi preservado.",
                    "warning",
                )
            mismatch_reasons = cache_mismatch_reasons(
                cache_record, request.zabbix.url, request.anonymize
            )
            if mismatch_reasons and not self.view.confirm_cache_mismatch(
                summary, mismatch_reasons
            ):
                self.view.log(
                    "Regeneração cancelada: divergência do cache sem confirmação.",
                    "warning",
                )
                return
            worker = partial(self.run_audit_flow, cache_record=cache_record)
        if request.data_file:
            starting_log = f"Iniciando auditoria a partir do arquivo de coleta: {request.data_file}..."
        else:
            starting_log = "Iniciando auditoria (Usando Cache)..." if request.use_cache else "Iniciando auditoria (Nova Coleta)..."
        return self._start_operation(worker, request, starting_log)

    def start_collection_only(self, request: CollectionRequest):
        """Inicia apenas a coleta de dados do Zabbix (sem IA) em uma nova thread, salvando o resultado em file_path."""
        validation_error = request.validation_error() or self._zabbix_validation_error(request.zabbix)
        if validation_error:
            self.view.log(validation_error, "danger")
            return
        if not self._confirm_insecure_zabbix_transport(request.zabbix):
            return
        return self._start_operation(
            self.run_collection_only_flow,
            request,
            "Iniciando coleta de dados do Zabbix (sem IA)...",
        )

    def _collect_zabbix_data(
        self,
        config: ZabbixConfig,
        limits: CollectionLimits,
        anonymize: bool,
        operation: OperationContext,
        anonymizer: Optional[Anonymizer] = None,
    ):
        """Conecta ao Zabbix, coleta os dados, anonimiza se necessário e salva o cache local. Retorna os dados coletados."""
        operation.raise_if_cancelled()
        self.view.update_progress(10, "Conectando ao Zabbix...")
        logger = lambda msg: self.view.log(
            redact_zabbix_log_message(msg, config), "warning"
        )
        if config.auth_method == "token":
            zabbix = zabbix_api.ZabbixClient(config.url, token=config.token, verify_ssl=config.verify_ssl, logger=logger)
        else:
            zabbix = zabbix_api.ZabbixClient(
                config.url,
                user=config.username,
                password=config.password,
                verify_ssl=config.verify_ssl,
                logger=logger,
            )

        try:
            self.view.log(f"Conectando ao Zabbix em {config.url}...")
            version = zabbix.discover_version()
            if version:
                self.view.log(f"Versão do Zabbix detectada: {version}")

            operation.raise_if_cancelled()
            self.view.update_progress(20, "Autenticando no Zabbix...")
            zabbix.authenticate()

            operation.raise_if_cancelled()
            self.view.update_progress(30, "Coletando dados da API (Pode demorar)...")
            self.view.log("Iniciando varredura profunda no Zabbix...")
            zabbix_data = zabbix.collect_data(
                history_limit=limits.history_limit,
                sample_limit=limits.sample_limit,
                template_limit=limits.template_limit,
                only_used_templates=limits.only_used_templates,
                is_cancelled=operation.is_cancelled,
                progress_callback=self.view.update_progress,
            )
        finally:
            zabbix.close()

        operation.raise_if_cancelled()
        if anonymize:
            self.view.log("Anonimizando dados sensíveis (IPs e Senhas) da coleta...")
            anonymizer = anonymizer or Anonymizer()
            zabbix_data = anonymizer.anonymize(zabbix_data)
            if "_collection_metadata" in zabbix_data:
                metadata = dict(zabbix_data["_collection_metadata"])
                metadata["anonymized"] = True
                zabbix_data["_collection_metadata"] = metadata

        operation.raise_if_cancelled()
        self.view.log("Coleta de dados concluída com sucesso.")

        try:
            self.cache_store.save(zabbix_data, config.url, anonymize)
        except Exception as e:
            self.view.log(f"Aviso: Não foi possível salvar o cache local da auditoria: {e}", "warning")

        return zabbix_data

    def run_collection_only_flow(self, request: CollectionRequest, operation: Optional[OperationContext] = None):
        managed_operation = operation is not None
        operation = operation or self._standalone_context()
        try:
            anonymizer = Anonymizer() if request.anonymize else None
            zabbix_data = self._collect_zabbix_data(
                request.zabbix,
                request.limits,
                request.anonymize,
                operation,
                anonymizer,
            )
            operation.raise_if_cancelled()
            if not operation.begin_completion():
                raise OperationCancelled("Operação cancelada ao concluir a coleta.")

            atomic_write_json(request.output_file, zabbix_data, indent=2)
            self.view.log(f"Dados da coleta salvos com sucesso em: {request.output_file}")
            self.view.update_progress(100, "Coleta Concluída!")
        except OperationCancelled:
            self.view.log("Operação cancelada pelo usuário.", "warning")
            self.view.update_progress(0, "Operação Cancelada.")
        except Exception as e:
            safe_error = redact_zabbix_log_message(e, request.zabbix)
            self.view.log(f"Erro durante a coleta de dados: {safe_error}", "danger")
            self.view.update_progress(0, "Falha na Coleta")
        finally:
            if managed_operation:
                self._finish_operation(operation)

    def run_audit_flow(
        self,
        request: AuditRequest,
        operation: Optional[OperationContext] = None,
        cache_record=None,
    ):
        managed_operation = operation is not None
        operation = operation or self._standalone_context()
        try:
            operation.raise_if_cancelled()
            anonymizer = Anonymizer() if request.anonymize else None
            zabbix_data = {}
            if request.data_file:
                self.view.update_progress(30, "Carregando dados do arquivo selecionado...")
                try:
                    zabbix_data = self._load_audit_json(request.data_file)
                    self.view.log("Dados da coleta selecionada foram carregados com sucesso.")
                except Exception as e:
                    self.view.log(f"Erro: Não foi possível carregar o arquivo selecionado: {e}", "danger")
                    self.view.update_progress(0, "Erro ao carregar arquivo.")
                    return
            elif not request.use_cache:
                zabbix_data = self._collect_zabbix_data(
                    request.zabbix,
                    request.limits,
                    request.anonymize,
                    operation,
                    anonymizer,
                )
                operation.raise_if_cancelled()
            else:
                self.view.update_progress(30, "Carregando dados do cache local...")
                try:
                    if cache_record is None:
                        cache_record = self.cache_store.load(request.zabbix.url)
                    zabbix_data = self._validate_audit_payload(cache_record.data)
                    self.view.log("Dados do cache versionado carregados com sucesso.")
                except Exception:
                    self.view.log(
                        "Erro: Não há cache válido. Execute a Auditoria normal primeiro.",
                        "danger",
                    )
                    self.view.update_progress(0, "Erro de Cache.")
                    return

            operation.raise_if_cancelled()
            if anonymizer is not None:
                # Imported and cached collections may have been produced with
                # anonymization disabled, so enforce the current request here.
                zabbix_data = anonymizer.anonymize(zabbix_data)
                if "_collection_metadata" in zabbix_data:
                    metadata = dict(zabbix_data["_collection_metadata"])
                    metadata["anonymized"] = True
                    zabbix_data["_collection_metadata"] = metadata

            # 3. Gera o relatório com a IA
            self.view.update_progress(50, "Processando evidências e sistema...")
            os_evidence_text = ""
            if request.attached_files:
                self.view.log(f"Lendo e processando {len(request.attached_files)} arquivo(s) de evidência do SO...")
                os_evidence_text = self._read_attached_evidence(
                    request.attached_files, operation, anonymizer
                )

            analyst_data = request.analyst.as_dict()

            operation.raise_if_cancelled()
            self.view.update_progress(60, "Conectando à Inteligência Artificial...")
            self.view.log(f"Enviando dados para {request.ai.provider} (Modelo: {request.ai.model}). Aguarde...")
            ai_client = ai_api.AIClient(
                request.ai.provider,
                request.ai.api_key,
                auth_mode=request.ai.auth_mode,
                cli_model_override=request.ai.cli_model_override,
            )
            
            self.view.clear_report()
            self.view.select_report_tab()
            
            self.view.update_progress(80, "Recebendo Stream da Inteligência Artificial...")
            report_stream = ai_client.generate_audit_report(
                zabbix_data,
                request.ai.model,
                os_evidence_text,
                analyst_data,
                request.custom_instructions,
                is_cancelled=operation.is_cancelled,
            )
            
            final_event = None
            for event in report_stream:
                operation.raise_if_cancelled()
                if isinstance(event, AIStreamEvent):
                    if event.event_type == "final":
                        final_event = event
                        continue
                    if event.event_type != "text" or not event.text:
                        continue
                    chunk = event.text
                else:
                    # Compatibility with third-party integrations that still yield text.
                    chunk = event
                if not operation.run_if_active(lambda: self.view.append_report_chunk(chunk)):
                    raise OperationCancelled("Operação cancelada durante o streaming.")

            if final_event is None:
                self.view.log(
                    "A IA encerrou sem confirmação de conclusão; o relatório foi preservado como parcial.",
                    "warning",
                )
                self.view.update_progress(0, "Relatório incompleto")
                return
            if not final_event.completed_successfully:
                reason = final_event.reason or "desconhecido"
                detail = f": {final_event.error}" if final_event.error else ""
                self.view.log(
                    f"A IA não concluiu o relatório ({reason}){detail}. O texto recebido "
                    "foi preservado como parcial. Tente novamente com “Regerar (Apenas IA)” "
                    "quando houver uma coleta em cache.",
                    "warning",
                )
                self.view.update_progress(0, "Relatório incompleto")
                return

            if not operation.begin_completion():
                raise OperationCancelled("Operação cancelada ao concluir a auditoria.")
            self.view.log("Relatório gerado com sucesso!")
            self.view.update_progress(100, "Auditoria Concluída!")
                
        except OperationCancelled:
            self.view.log("Operação cancelada pelo usuário.", "warning")
            self.view.update_progress(0, "Operação Cancelada.")
        except Exception as e:
            safe_error = redact_zabbix_log_message(e, request.zabbix)
            self.view.log(f"Erro durante a execução da auditoria: {safe_error}", "danger")
            self.view.update_progress(0, "Falha na Auditoria")
        finally:
            if managed_operation:
                self._finish_operation(operation)
