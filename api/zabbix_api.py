import json
import re
import threading
import time
import warnings
from datetime import datetime, timezone

import requests
import urllib3

from core.operation import OperationCancelled


class ZabbixClientError(Exception):
    """Base para falhas produzidas pelo cliente Zabbix."""


class ZabbixInvalidResponseError(ZabbixClientError):
    """A resposta HTTP do Zabbix não contém um documento JSON válido."""


class ZabbixAPIError(ZabbixClientError):
    """O Zabbix retornou um erro JSON-RPC."""

    def __init__(self, method, error):
        self.method = method
        self.error = error
        if isinstance(error, dict):
            detail = error.get("data") or error.get("message") or str(error)
        else:
            detail = str(error)
        super().__init__(f"Erro na API do Zabbix ({method}): {detail}")


class ZabbixVersionError(ZabbixClientError):
    """A versão informada pelo Zabbix não pode ser usada para compatibilidade."""


def parse_zabbix_version(version):
    """Converte versões numéricas ou pré-releases conhecidas em tupla numérica."""
    if not isinstance(version, str):
        raise ZabbixVersionError(f"Versão Zabbix inválida: {version!r}")
    match = re.match(
        r"^\s*(\d+(?:\.\d+)*)(?:(?:alpha|beta|rc)\d*)?\s*$",
        version,
        re.IGNORECASE,
    )
    if not match:
        raise ZabbixVersionError(f"Versão Zabbix inválida: {version!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def parse_update_interval(delay):
    """Return a simple Zabbix item interval in seconds, or ``None`` if complex.

    Flexible intervals and user macros cannot be safely classified as polling
    frequency from the plain ``delay`` field, so they remain explicitly
    unclassifiable rather than being mistaken for an aggressive poller.
    """
    if not isinstance(delay, str):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*([smhdwSMHDW]?)\s*", delay)
    if not match:
        return None
    unit = match.group(2).lower()
    multipliers = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return int(match.group(1)) * multipliers[unit]


class ZabbixClient:
    DEFAULT_CONNECT_TIMEOUT = 5
    DEFAULT_READ_TIMEOUT = 30
    TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(
        self,
        url,
        user=None,
        password=None,
        token=None,
        verify_ssl=True,
        logger=None,
        connect_timeout=DEFAULT_CONNECT_TIMEOUT,
        read_timeout=DEFAULT_READ_TIMEOUT,
        max_retries=2,
        backoff_factor=0.5,
    ):
        self.url = url
        self.user = user
        self.password = password
        self.token = token
        self.verify_ssl = verify_ssl
        self.api_version = None
        self.api_version_tuple = None
        self.use_header_auth = False
        self.auth_token = None
        self._logger = logger
        self.compatibility_warnings = []
        self.session = requests.Session()
        self.timeout = (connect_timeout, read_timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = max(0.0, float(backoff_factor))
        self._request_id = 0
        self._request_id_lock = threading.Lock()
        self._closed = False

    def _warn(self, message):
        """Reporta uma falha não-fatal de coleta, se um logger tiver sido fornecido."""
        if self._logger:
            self._logger(message)

    def _warn_compatibility(self, feature, error):
        warning = {
            "category": "zabbix_compatibility",
            "feature": feature,
            "version": self.api_version,
            "error": str(error),
        }
        self.compatibility_warnings.append(warning)
        self._warn(json.dumps(warning, ensure_ascii=False, sort_keys=True))

    def _warn_collection(self, phase, method, error):
        """Keep a machine-readable warning when one collection phase fails.

        Collection is intentionally best-effort: permission or compatibility
        failures in one endpoint must not erase the independent findings that
        were already gathered.  Transport failures are handled separately and
        remain fatal because the rest of the result would be misleading.
        """
        warning = {
            "category": "zabbix_collection",
            "phase": phase,
            "method": method,
            "error": str(error),
        }
        self.collection_warnings.append(warning)
        self._warn(json.dumps(warning, ensure_ascii=False, sort_keys=True))

    def _version_at_least(self, major, minor=0):
        if self.api_version_tuple is None:
            raise ZabbixVersionError(
                "A versão do Zabbix deve ser descoberta antes da operação versionada."
            )
        current = self.api_version_tuple + (0,) * max(0, 2 - len(self.api_version_tuple))
        return current[:2] >= (major, minor)

    def _next_request_id(self):
        with self._request_id_lock:
            self._request_id += 1
            return self._request_id

    @staticmethod
    def _is_idempotent(method):
        return method == "apiinfo.version" or method.endswith(".get")

    def _post(self, payload, headers):
        if self.verify_ssl:
            return self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=True,
            )

        # A supressão é deliberadamente local: outras conexões HTTPS do
        # processo continuam emitindo InsecureRequestWarning normalmente.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            return self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=False,
            )

    def _should_retry(self, method, error, response):
        if not self._is_idempotent(method):
            return False
        if isinstance(
            error,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ),
        ):
            return True
        return response is not None and response.status_code in self.TRANSIENT_STATUS_CODES

    def api_call(self, method, params, auth_required=True):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._next_request_id(),
        }
        headers = {'Content-Type': 'application/json-rpc'}
        
        if auth_required and self.auth_token:
            if self.use_header_auth:
                headers['Authorization'] = f"Bearer {self.auth_token}"
            else:
                payload["auth"] = self.auth_token

        attempts = self.max_retries + 1 if self._is_idempotent(method) else 1
        for attempt in range(attempts):
            response = None
            try:
                response = self._post(payload, headers)
                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                if attempt + 1 < attempts and self._should_retry(method, exc, response):
                    time.sleep(self.backoff_factor * (2 ** attempt))
                    continue
                raise ConnectionError(f"Erro de conexão com o Zabbix: {exc}") from exc

            try:
                result = response.json()
            except (ValueError, requests.exceptions.InvalidJSONError) as exc:
                raise ZabbixInvalidResponseError(
                    f"Resposta não JSON recebida do Zabbix ao chamar {method}."
                ) from exc

            if not isinstance(result, dict):
                raise ZabbixInvalidResponseError(
                    f"Resposta JSON-RPC inválida do Zabbix ao chamar {method}."
                )
            if "error" in result:
                raise ZabbixAPIError(method, result["error"])
            return result.get("result")

        raise AssertionError("Loop de tentativas terminou sem resposta")

    def discover_version(self):
        self.api_version = self.api_call("apiinfo.version", {}, auth_required=False)
        self.api_version_tuple = parse_zabbix_version(self.api_version)
        self.use_header_auth = self._version_at_least(6, 4)
        return self.api_version

    def authenticate(self):
        if self.token:
            self.auth_token = self.token
            # Mantém o comportamento moderno quando authenticate() é usado
            # isoladamente, mas respeita a versão quando discover_version() já
            # estabeleceu o contrato do servidor.
            if self.api_version_tuple is None:
                self.use_header_auth = True
            # Realiza uma chamada simples para validar se o token é autêntico
            self.api_call("user.get", {"output": ["userid"], "limit": 1})
            return self.auth_token

        login_user_field = "user"
        if self.api_version_tuple is None or self._version_at_least(5, 4):
            login_user_field = "username"
        self.auth_token = self.api_call(
            "user.login",
            {login_user_field: self.user, "password": self.password},
            auth_required=False,
        )
        return self.auth_token

    def _get_super_admin_users(self):
        """Retorna Super Admins com o mesmo schema em todas as versões."""
        username_field = "username" if self._version_at_least(5, 4) else "alias"
        user_params = {"output": [username_field, "name"]}

        if self._version_at_least(5, 2):
            roles = self.api_call("role.get", {
                "output": ["roleid"],
                "filter": {"type": 3},
            })
            roleids = [role["roleid"] for role in (roles or []) if role.get("roleid")]
            if not roleids:
                return []
            # user.get não aceita ``roleids`` como parâmetro de topo; o
            # contrato compatível filtra pelo campo roleid retornado por
            # role.get.
            user_params["filter"] = {"roleid": roleids}
        else:
            user_params["filter"] = {"type": 3}

        users = self.api_call("user.get", user_params) or []
        return [
            {
                "username": user.get(username_field, ""),
                "name": user.get("name", ""),
            }
            for user in users
        ]

    def _collect_super_admin_summary(self, sample_limit):
        summary = {
            "super_admin_users_count": 0,
            "super_admin_users_samples": [],
        }
        try:
            users = self._get_super_admin_users()
            summary["super_admin_users_count"] = len(users)
            summary["super_admin_users_samples"] = [
                user["username"] for user in users[:sample_limit]
            ]
        except OperationCancelled:
            raise
        except Exception as exc:
            self._warn_compatibility("super_admin_users", exc)
        return summary

    @staticmethod
    def _normalize_proxy_mode(value, modern):
        modes = {"0": "active", "1": "passive"} if modern else {
            "5": "active",
            "6": "passive",
        }
        return modes.get(str(value), "unknown")

    def _get_proxies(self):
        """Retorna proxies com nome e modo uniformes entre schemas da API."""
        modern = self._version_at_least(7, 0)
        name_field = "name" if modern else "host"
        mode_field = "operating_mode" if modern else "status"
        proxies = self.api_call("proxy.get", {
            "output": [name_field, mode_field, "lastaccess", "version"],
        }) or []
        now = int(time.time())
        normalized = []
        for proxy in proxies:
            try:
                lastaccess = int(proxy.get("lastaccess", 0))
            except (TypeError, ValueError):
                lastaccess = 0
            lag_seconds = max(0, now - lastaccess) if lastaccess else None
            if lag_seconds is None:
                state = "never_seen"
            elif lag_seconds <= 300:
                state = "online"
            else:
                state = "delayed"
            version = str(proxy.get("version") or "unknown").strip() or "unknown"
            normalized.append({
                "name": proxy.get(name_field, ""),
                "operating_mode": self._normalize_proxy_mode(proxy.get(mode_field), modern),
                "state": state,
                "lag_seconds": lag_seconds,
                "lastaccess": str(lastaccess) if lastaccess else None,
                "version": version,
            })
        return normalized

    def _collect_proxies_summary(self, sample_limit):
        try:
            return {"proxies_details": self._get_proxies()[:sample_limit]}
        except OperationCancelled:
            raise
        except Exception as exc:
            self._warn_compatibility("proxies", exc)
            return {"proxies_details": []}

    def logout(self):
        if self.auth_token and not self.token:
            try:
                self.api_call("user.logout", [])
            except Exception as exc:
                self._warn(f"Aviso: não foi possível encerrar a sessão no Zabbix: {exc}")
            finally:
                self.auth_token = None

    def close(self):
        """Encerra autenticação por senha e fecha a conexão HTTP reutilizável."""
        if self._closed:
            return
        try:
            # ``collect_data`` temporarily installs a best-effort wrapper;
            # restore the normal client contract even when collection aborts.
            original_api_call = getattr(self, "_collection_original_api_call", None)
            if original_api_call is not None:
                self.api_call = original_api_call
                del self._collection_original_api_call
            self.logout()
        finally:
            try:
                self.session.close()
            finally:
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def get_active_node_hostid(self, is_cancelled=None):
        """Identifica o hostid do nó Ativo em um cluster HA ou Standalone."""
        def check_cancelled():
            if is_cancelled is not None and is_cancelled():
                raise OperationCancelled("Coleta do Zabbix cancelada.")

        # 1. Tenta API Nativa de High Availability (Zabbix 6.0+)
        check_cancelled()
        try:
            nodes = self.api_call("hanode.get", {"filter": {"status": "3"}}) # 3 = Active
            check_cancelled()
            if nodes and len(nodes) > 0:
                node_name = nodes[0].get("name")
                if node_name:
                    hosts = self.api_call("host.get", {"filter": {"host": node_name}})
                    if hosts:
                        return hosts[0]["hostid"]
        except OperationCancelled:
            raise
        except Exception:
            pass
            
        # 2. Descobre ativamente rastreando itens internos com dados recentes (À prova de falhas)
        try:
            check_cancelled()
            internal_items = self.api_call("item.get", {
                "output": ["itemid", "hostid", "value_type"],
                "search": {"key_": "zabbix[process,poller"},
                "filter": {"type": "5", "status": "0"}
            })
            if internal_items:
                host_history = {}
                for item in internal_items:
                    check_cancelled()
                    hid = item["hostid"]
                    vtype = item["value_type"]
                    hist = self.api_call("history.get", {
                        "output": ["clock"],
                        "itemids": item["itemid"],
                        "history": vtype,
                        "sortfield": "clock",
                        "sortorder": "DESC",
                        "limit": 1
                    })
                    if hist:
                        host_history[hid] = int(hist[0]["clock"])
                if host_history:
                    return max(host_history, key=host_history.get)
        except OperationCancelled:
            raise
        except Exception:
            pass
            
        # 3. Fallback genérico para Zabbix Standalone clássico
        try:
            check_cancelled()
            hosts = self.api_call("host.get", {"filter": {"host": "Zabbix server"}})
            if hosts:
                return hosts[0]["hostid"]
        except OperationCancelled:
            raise
        except Exception:
            pass
        return None

    def _discover_infrastructure_hostids(self, active_hostid, check_cancelled):
        """Find Server/DB hosts once for the template and database phases."""
        hostids = {active_hostid} if active_hostid else set()
        groups = self.api_call("hostgroup.get", {
            "output": ["groupid"],
            "search": {"name": ["Zabbix", "Database", "DB", "Banco"]},
            "searchByAny": True,
        }) or []
        if groups:
            groupids = [group["groupid"] for group in groups if group.get("groupid")]
            if groupids:
                hosts = self.api_call(
                    "host.get", {"output": ["hostid"], "groupids": groupids}
                ) or []
                for host in hosts:
                    check_cancelled()
                    if host.get("hostid"):
                        hostids.add(host["hostid"])

        named_hosts = self.api_call("host.get", {
            "output": ["hostid"],
            "search": {"host": ["zabbix", "database", "db", "mysql", "pgsql"]},
            "searchWildcardsEnabled": True,
            "searchByAny": True,
        }) or []
        for host in named_hosts:
            check_cancelled()
            if host.get("hostid"):
                hostids.add(host["hostid"])
        return hostids

    def _fetch_trend_values(self, itemid, value_type, history_limit, sample_limit, is_cancelled=None):
        """Busca uma amostra cronológica de valores históricos de um item, com fallback para
        trend.get quando o histórico bruto já foi descartado pelo housekeeping — comum em
        ambientes que reduzem a retenção de 'history' para itens internos do Zabbix (ex: para
        economizar espaço em disco) mas mantêm 'trends' por muito mais tempo. Retorna None se
        nenhuma das duas fontes tiver dados."""
        if is_cancelled is not None and is_cancelled():
            raise OperationCancelled("Coleta do Zabbix cancelada.")
        history_data = self.api_call("history.get", {
            "output": ["value"],
            "history": value_type,
            "itemids": itemid,
            "sortfield": "clock",
            "sortorder": "DESC",
            "limit": history_limit
        })
        if is_cancelled is not None and is_cancelled():
            raise OperationCancelled("Coleta do Zabbix cancelada.")
        if history_data:
            step = max(1, len(history_data) // sample_limit)
            values = [h["value"] for h in history_data[0::step]][:sample_limit]
            values.reverse()
            return values

        # trend.get só existe para itens numéricos (float=0, unsigned=3)
        if value_type in ("0", "3"):
            trends_data = self.api_call("trend.get", {
                "output": ["value_avg"],
                "itemids": itemid,
                "sortfield": "clock",
                "sortorder": "DESC",
                "limit": sample_limit
            })
            if is_cancelled is not None and is_cancelled():
                raise OperationCancelled("Coleta do Zabbix cancelada.")
            if trends_data:
                values = [t["value_avg"] for t in trends_data]
                values.reverse()
                return values

        return None

    def collect_data(
        self,
        history_limit=500,
        sample_limit=15,
        template_limit=200,
        only_used_templates=False,
        is_cancelled=None,
        progress_callback=None,
    ):
        """Collect audit evidence without making one optional endpoint fatal.

        The Zabbix API exposes features according to version and permissions.
        This method therefore establishes the complete output schema before
        calling optional endpoints, preserving usable sections when another
        section is unavailable. Authentication is performed before this method;
        a connection failure still propagates as a total transport loss.
        """
        def check_cancelled():
            if is_cancelled is not None and is_cancelled():
                raise OperationCancelled("Coleta do Zabbix cancelada.")

        def report_progress(phase, percent):
            if progress_callback is not None:
                progress_callback(percent, phase)

        # Trava de segurança: impede divisões por zero e quebras caso o usuário digite 0 ou valor negativo
        history_limit = max(1, int(history_limit))
        sample_limit = max(1, int(sample_limit))
        template_limit = max(1, int(template_limit))

        audit_data = {
            "zabbix_version": self.api_version,
            "total_hosts": 0,
            "monitored_hosts": 0,
            "disabled_hosts": 0,
            "disabled_hosts_samples": [],
            "total_host_groups": 0,
            "total_active_items": 0,
            "external_checks_count": 0,
            "external_checks_samples": [],
            "aggressive_polling_count": 0,
            "aggressive_polling_samples": [],
            "unsupported_items_count": 0,
            "unsupported_items_samples": [],
            "unclassifiable_item_intervals_count": 0,
            "unclassifiable_item_intervals_samples": [],
            "total_templates": 0,
            "templates_list_sample": [],
            "zabbix_server_templates": [],
            "zabbix_server_health_metrics": [],
            "database_health_metrics": [],
            "nvps": "Desconhecido",
            "total_active_triggers": 0,
            "unsupported_triggers_count": 0,
            "active_discovery_rules_count": 0,
            "active_discovery_rules_samples": [],
            "authentication_summary": {
                "available": False,
                "mfa_available": False,
                "settings": None,
                "mfa_methods": [],
                "unavailability_reason": None,
            },
            "recent_failed_alerts_count": 0,
            "failed_alerts_errors_samples": [],
            "unacknowledged_critical_problems_count": 0,
            "unacknowledged_critical_problems_samples": [],
            "housekeeping_config": None,
            "super_admin_users_count": 0,
            "super_admin_users_samples": [],
            "global_scripts_count": 0,
            "global_scripts_samples": [],
            "proxies_details": [],
            "active_mediatypes_count": 0,
            "active_mediatypes_samples": [],
            "business_services_count": 0,
            "business_services_samples": [],
            "active_maintenances_count": 0,
            "active_maintenances_samples": [],
            "zabbix_server_os_metrics": [],
        }
        self.collection_warnings = []

        # Keep the existing, well-tested endpoint-specific collection code,
        # while treating failures from optional API calls as an empty result for
        # that phase.  This wrapper is local to this client instance and is
        # restored before a successful return.
        original_api_call = self.api_call
        self._collection_original_api_call = original_api_call
        current_phase = "initialization"

        api_call_count = 0

        def collection_api_call(method, params, auth_required=True):
            nonlocal api_call_count
            api_call_count += 1
            try:
                return original_api_call(method, params, auth_required)
            except OperationCancelled:
                raise
            except ConnectionError:
                # A lost transport means there is no reliable way to continue.
                raise
            except Exception as exc:
                self._warn_collection(current_phase, method, exc)
                return []

        self.api_call = collection_api_call
        report_progress("Iniciando coleta", 30)

        # 2. Resumo de Hosts e Status
        current_phase = "hosts"
        report_progress("Coletando hosts", 34)
        check_cancelled()
        hosts = self.api_call("host.get", {
            "output": ["hostid", "host", "status"],
            "selectInterfaces": ["interfaceid", "type"]
        })
        if hosts:
            audit_data["total_hosts"] = len(hosts)
            audit_data["monitored_hosts"] = len([h for h in hosts if h["status"] == "0"])
            audit_data["disabled_hosts"] = len([h for h in hosts if h["status"] == "1"])
            audit_data["disabled_hosts_samples"] = [h["host"] for h in hosts if h["status"] == "1"][:sample_limit]
            
        # Grupos de Hosts
        check_cancelled()
        try:
            hgroups = self.api_call("hostgroup.get", {"countOutput": True})
            audit_data["total_host_groups"] = int(hgroups or 0)
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar grupos de hosts: {e}")

        # 3. Análise de Itens
        current_phase = "items"
        report_progress("Coletando itens", 39)
        check_cancelled()
        items = self.api_call("item.get", {
            "output": ["itemid", "name", "type", "delay", "key_", "state", "error"],
            "filter": {"status": "0"}
        })
        if items:
            audit_data["total_active_items"] = len(items)
            external_checks = [i for i in items if i["type"] == "10"]
            audit_data["external_checks_count"] = len(external_checks)
            audit_data["external_checks_samples"] = [i["key_"] for i in external_checks[:sample_limit]]
            
            aggressive_items = []
            unclassifiable_intervals = []
            for i in items:
                check_cancelled()
                interval_seconds = parse_update_interval(i.get("delay"))
                if interval_seconds is None:
                    unclassifiable_intervals.append({
                        "name": i.get("name", ""),
                        "delay": i.get("delay", ""),
                        "key": i.get("key_", ""),
                    })
                elif 0 < interval_seconds < 30:
                    aggressive_items.append({"name": i["name"], "delay": i["delay"], "key": i["key_"]})
            
            audit_data["aggressive_polling_count"] = len(aggressive_items)
            audit_data["aggressive_polling_samples"] = aggressive_items[:sample_limit]
            audit_data["unclassifiable_item_intervals_count"] = len(unclassifiable_intervals)
            audit_data["unclassifiable_item_intervals_samples"] = unclassifiable_intervals[:sample_limit]
            
            unsupported_items = [i for i in items if i.get("state") == "1"]
            audit_data["unsupported_items_count"] = len(unsupported_items)
            audit_data["unsupported_items_samples"] = [
                {"key": item.get("key_", ""), "error": item.get("error", "")}
                for item in unsupported_items[:sample_limit]
            ]

        # 4. Templates Utilizados
        current_phase = "templates"
        report_progress("Coletando templates", 44)
        check_cancelled()
        template_params = {"output": ["host"]}
        if only_used_templates:
            template_params["selectHosts"] = ["hostid"]
            
        templates = self.api_call("template.get", template_params)
        if templates:
            if only_used_templates:
                templates = [t for t in templates if len(t.get("hosts", [])) > 0]
            audit_data["total_templates"] = len(templates)
            template_names = [t["host"] for t in templates]
            audit_data["templates_list_sample"] = template_names[:template_limit] # Limita a lista global para não estourar o contexto da IA

        # Templates aplicados na Infraestrutura do Zabbix (Server e Banco)
        check_cancelled()
        active_hostid = self.get_active_node_hostid(is_cancelled=is_cancelled)
        try:
            infra_hostids_for_templates = self._discover_infrastructure_hostids(
                active_hostid, check_cancelled
            )
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao identificar hosts de infraestrutura do Zabbix: {e}")
            infra_hostids_for_templates = set()

        audit_data["zabbix_server_templates"] = []
        if infra_hostids_for_templates:
            server_templates = self.api_call("template.get", {
                "output": ["host"], "hostids": list(infra_hostids_for_templates)
            })
            if server_templates:
                audit_data["zabbix_server_templates"] = list(set([t["host"] for t in server_templates]))

        # 5. Coleta de Histórico: Saúde Interna
        current_phase = "internal_health"
        report_progress("Coletando saúde interna", 50)
        check_cancelled()
        # Limite dedicado (não usa template_limit): itens internos "zabbix[...]" de um host raramente
        # passam de algumas dezenas, então um limite fixo e generoso evita cortar itens críticos caso
        # o usuário configure um template_limit baixo na GUI (esse parâmetro é para a lista de templates).
        INTERNAL_ITEMS_LIMIT = 500
        item_params = {
            "output": ["itemid", "name", "key_", "value_type", "lastvalue"],
            "filter": {"type": "5", "status": "0"},
            "search": {"key_": "zabbix["},
            "limit": INTERNAL_ITEMS_LIMIT
        }

        if active_hostid:
            item_params["hostids"] = active_hostid

        internal_items = self.api_call("item.get", item_params)
        audit_data["zabbix_server_health_metrics"] = []
        if internal_items:
            server_health = []
            # Prefixos amplos (não uma lista fechada de processos específicos): "zabbix[process,"
            # sozinho já cobre poller, unreachable poller, trapper, history syncer, discoverer,
            # timer, escalator, alerter, preprocessing worker etc. Uma whitelist estreita (só
            # "poller"/"history") descartava processos reais retornados pelo Zabbix antes mesmo
            # de chegarem no relatório.
            critical_key_prefixes = ["zabbix[process,", "zabbix[queue", "zabbix[wcache", "zabbix[rcache", "zabbix[vcache", "zabbix[vps"]
            for item in internal_items:
                check_cancelled()
                if any(item["key_"].startswith(p) for p in critical_key_prefixes):
                    trend_values = self._fetch_trend_values(
                        item["itemid"], item["value_type"], history_limit, sample_limit,
                        is_cancelled=is_cancelled,
                    )
                    if not trend_values:
                        trend_values = ["Sem dados"]

                    server_health.append({
                        "metric_name": item["name"],
                        "key": item["key_"],
                        "current_value": item.get("lastvalue", "Desconhecido"),
                        "recent_trend_values": trend_values
                    })
            audit_data["zabbix_server_health_metrics"] = server_health

        # 5.5 Coleta Específica de Banco de Dados da Infra (Zabbix DB)
        current_phase = "database"
        report_progress("Coletando saúde do banco", 58)
        check_cancelled()
        audit_data["database_health_metrics"] = []
        try:
            infra_hostids = self._discover_infrastructure_hostids(
                active_hostid, check_cancelled
            )

            if infra_hostids:
                db_items = self.api_call("item.get", {
                    "output": ["itemid", "name", "key_", "lastvalue", "units", "value_type"],
                    "hostids": list(infra_hostids),
                    "search": {"key_": ["mysql", "pgsql", "oracle"]},
                    "searchByAny": True,
                    "filter": {"status": "0", "state": "0"}
                })
                
                db_metrics = []
                if db_items:
                    # Lista ampliada: termos como "tmp"/"table"/"innodb"/"disk" cobrem métricas
                    # como mysql.status[Created_tmp_disk_tables] e tamanho de tabelas específicas,
                    # que a lista anterior descartava mesmo quando o Zabbix as retornava.
                    critical_db_terms = ["qps", "queries", "connections", "buffer", "cache", "size", "slow", "ping", "uptime", "active", "total", "read", "write", "tmp", "table", "disk", "innodb"]
                    filtered_db_items = [i for i in db_items if any(term in i["key_"].lower() or term in i["name"].lower() for term in critical_db_terms) and "zabbix[" not in i["key_"]]

                    for item in filtered_db_items[:template_limit]:
                        check_cancelled()
                        trend_values = None
                        if item["value_type"] in ["0", "3"]:
                            trend_values = self._fetch_trend_values(
                                item["itemid"], item["value_type"], history_limit, sample_limit,
                                is_cancelled=is_cancelled,
                            )
                        db_metrics.append({"name": item["name"], "key": item["key_"], "current_value": f"{item['lastvalue']} {item.get('units', '')}".strip(), "recent_trend": trend_values if trend_values else ["Sem dados"]})
                audit_data["database_health_metrics"] = db_metrics
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar métricas de saúde do banco de dados: {e}")

        # 6. Coletas Extras de Higiene e Risco
        current_phase = "risk_and_hygiene"
        report_progress("Coletando riscos e higiene", 66)
        # NVPS (New Values Per Second)
        check_cancelled()
        audit_data["nvps"] = "Desconhecido"
        try:
            # Filtro exato (não "search"/LIKE): "zabbix[wcache,values" também casaria com os itens
            # de NVPS por tipo de dado (zabbix[wcache,values,float], ...,uint, ...,str etc.), e a
            # API não garante ordem — pegar o [0] de um "search" arriscava trazer um sub-tipo
            # zerado em vez do item agregado "zabbix[wcache,values]".
            nvps_items = self.api_call("item.get", {
                "output": ["itemid", "lastvalue", "value_type"],
                "filter": {"key_": "zabbix[wcache,values]"},
                "hostids": active_hostid
            })
            if nvps_items:
                nvps_item = nvps_items[0]
                lastvalue = nvps_item.get("lastvalue")
                if lastvalue not in (None, ""):
                    audit_data["nvps"] = lastvalue
                else:
                    trend = self._fetch_trend_values(
                        nvps_item["itemid"], nvps_item.get("value_type", "0"), history_limit,
                        sample_limit, is_cancelled=is_cancelled,
                    )
                    audit_data["nvps"] = trend[-1] if trend else "Sem dados"
            else:
                audit_data["nvps"] = "Item zabbix[wcache,values] não encontrado no host ativo"
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar NVPS: {e}")

        # Triggers Órfãs ou Quebradas
        check_cancelled()
        try:
            triggers = self.api_call("trigger.get", {"output": ["state"], "filter": {"status": "0"}})
            if triggers:
                audit_data["total_active_triggers"] = len(triggers)
                audit_data["unsupported_triggers_count"] = len([t for t in triggers if t.get("state") == "1"])
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar triggers: {e}")

        # Low-level discovery rules. ``drule.get`` is network discovery and
        # must not be used as a substitute for template/item LLD rules.
        check_cancelled()
        try:
            lld_rules = self.api_call("discoveryrule.get", {
                "output": ["name", "key_", "delay", "error"],
                "filter": {"status": "0"},
            })
            audit_data["active_discovery_rules_count"] = len(lld_rules) if lld_rules else 0
            audit_data["active_discovery_rules_samples"] = lld_rules[:sample_limit] if lld_rules else []
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar regras LLD: {e}")

        # Authentication settings are permission/version sensitive.  Preserve
        # that distinction in the schema instead of silently reporting zero MFA.
        check_cancelled()
        authentication_summary = audit_data["authentication_summary"]
        try:
            settings = self.api_call("authentication.get", {"output": "extend"})
            if settings:
                authentication_summary["available"] = True
                authentication_summary["settings"] = settings[0] if isinstance(settings, list) else settings
            else:
                authentication_summary["unavailability_reason"] = "indisponível ou sem permissão"

            if self._version_at_least(7, 0):
                mfa_methods = self.api_call("mfa.get", {"output": "extend"})
                if mfa_methods:
                    authentication_summary["mfa_available"] = True
                    authentication_summary["mfa_methods"] = mfa_methods[:sample_limit]
                elif authentication_summary["unavailability_reason"] is None:
                    authentication_summary["unavailability_reason"] = "MFA indisponível ou sem permissão"
            else:
                authentication_summary["unavailability_reason"] = (
                    "MFA requer Zabbix 7.0 ou superior"
                )
        except OperationCancelled:
            raise
        except Exception as e:
            authentication_summary["unavailability_reason"] = str(e)
            self._warn(f"Aviso: falha ao coletar autenticação/MFA: {e}")

        # Alertas Falhos (Emails que não estão saindo)
        check_cancelled()
        try:
            failed_alerts = self.api_call("alert.get", {"output": ["error"], "filter": {"status": "2"}, "limit": history_limit})
            audit_data["recent_failed_alerts_count"] = len(failed_alerts) if failed_alerts else 0
            if failed_alerts:
                audit_data["failed_alerts_errors_samples"] = list(set([a.get("error", "") for a in failed_alerts if a.get("error")]))[:sample_limit]
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar alertas falhos: {e}")

        # Problemas Críticos Não Reconhecidos
        check_cancelled()
        try:
            problems = self.api_call("problem.get", {"output": ["name", "severity"], "filter": {"acknowledged": "0"}, "severities": [4, 5], "source": 0, "object": 0, "limit": history_limit})
            audit_data["unacknowledged_critical_problems_count"] = len(problems) if problems else 0
            audit_data["unacknowledged_critical_problems_samples"] = [p.get("name") for p in problems[:sample_limit]] if problems else []
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar problemas críticos não reconhecidos: {e}")

        # Configurações de Banco de Dados (Housekeeping)
        check_cancelled()
        try:
            housekeeping = self.api_call("housekeeping.get", {"output": "extend"})
            if isinstance(housekeeping, list) and len(housekeeping) > 0:
                audit_data["housekeeping_config"] = housekeeping[0]
            else:
                audit_data["housekeeping_config"] = housekeeping
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar configurações de housekeeping: {e}")

        # Governança e Segurança: Usuários Super Admin
        current_phase = "governance"
        report_progress("Coletando governança", 76)
        check_cancelled()
        audit_data.update(self._collect_super_admin_summary(sample_limit))

        # Scripts Globais
        check_cancelled()
        audit_data["global_scripts_count"] = 0
        audit_data["global_scripts_samples"] = []
        try:
            scripts = self.api_call("script.get", {"output": ["name", "command"]})
            if scripts:
                audit_data["global_scripts_count"] = len(scripts)
                audit_data["global_scripts_samples"] = [s.get("name", "") for s in scripts][:sample_limit]
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar scripts globais: {e}")

        # Detalhes de Proxies
        check_cancelled()
        audit_data.update(self._collect_proxies_summary(sample_limit))

        # Tipos de Mídia Ativos (canais de notificação: Email, Webhook, SMS...)
        check_cancelled()
        audit_data["active_mediatypes_count"] = 0
        audit_data["active_mediatypes_samples"] = []
        try:
            mediatypes = self.api_call("mediatype.get", {"output": "extend", "filter": {"status": "0"}})
            if mediatypes:
                audit_data["active_mediatypes_count"] = len(mediatypes)
                audit_data["active_mediatypes_samples"] = [m.get("name", m.get("description", "")) for m in mediatypes][:sample_limit]
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar tipos de mídia ativos: {e}")

        # Serviços de Negócio / SLA (ITSM nativo)
        check_cancelled()
        audit_data["business_services_count"] = 0
        audit_data["business_services_samples"] = []
        try:
            services = self.api_call("service.get", {"output": "extend"})
            if services:
                audit_data["business_services_count"] = len(services)
                audit_data["business_services_samples"] = [s.get("name", "") for s in services][:sample_limit]
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar serviços de negócio (SLA/ITSM): {e}")

        # Janelas de Manutenção Ativas (possível supressão de alertas em andamento)
        check_cancelled()
        audit_data["active_maintenances_count"] = 0
        audit_data["active_maintenances_samples"] = []
        try:
            maintenances = self.api_call("maintenance.get", {
                "output": "extend",
                "selectHosts": ["host"],
                "selectGroups": ["name"]
            })
            if maintenances:
                now = int(time.time())
                # active_since/active_till delimitam a janela geral da manutenção; não modelam
                # os períodos recorrentes internos (diário/semanal), mas já indicam se a
                # manutenção está no seu intervalo de vigência agora.
                active_now = [m for m in maintenances if int(m.get("active_since", 0)) <= now <= int(m.get("active_till", 0))]
                audit_data["active_maintenances_count"] = len(active_now)
                audit_data["active_maintenances_samples"] = [
                    {
                        "name": m.get("name", ""),
                        "hosts": [h.get("host") for h in m.get("hosts", [])],
                        "groups": [g.get("name") for g in m.get("groups", [])]
                    }
                    for m in active_now[:sample_limit]
                ]
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar janelas de manutenção ativas: {e}")

        # Métricas de SO do host do Zabbix Server (CPU, Load Average, Swap, Disk I/O)
        current_phase = "server_os"
        report_progress("Coletando métricas do servidor", 88)
        check_cancelled()
        # Só existem se o host ativo tiver um agente/template de SO monitorando a própria máquina
        # (ausência total aqui é, em si, um achado de auditoria: falta observabilidade do host do Server).
        audit_data["zabbix_server_os_metrics"] = []
        try:
            if active_hostid:
                # Uma busca por categoria (em vez de um único item.get fatiado por sample_limit)
                # evita que dezenas de itens de disco por dispositivo (descobertos via LLD) engulam
                # o "slice" e deixem CPU/swap/memória de fora. "vfs.dev" (não só "vfs.dev.io") é
                # necessário para pegar templates mais novos, que usam vfs.dev.read.await/
                # vfs.dev.write.await em vez da chave antiga vfs.dev.io[...].
                os_metric_categories = {
                    "cpu": ["system.cpu"],
                    "swap": ["system.swap"],
                    "memory": ["vm.memory"],
                    "disk_io": ["vfs.dev"],
                }
                os_metrics_per_category_limit = max(5, sample_limit)

                os_metrics = []
                for prefixes in os_metric_categories.values():
                    check_cancelled()
                    category_items = self.api_call("item.get", {
                        "output": ["itemid", "name", "key_", "value_type", "lastvalue", "units"],
                        "hostids": active_hostid,
                        "search": {"key_": prefixes},
                        "searchByAny": True,
                        "filter": {"status": "0"}
                    })
                    if not category_items:
                        continue
                    for item in category_items[:os_metrics_per_category_limit]:
                        check_cancelled()
                        trend_values = self._fetch_trend_values(
                            item["itemid"], item["value_type"], history_limit, sample_limit,
                            is_cancelled=is_cancelled,
                        )
                        os_metrics.append({
                            "metric_name": item["name"],
                            "key": item["key_"],
                            "current_value": f"{item.get('lastvalue', '')} {item.get('units', '')}".strip(),
                            "recent_trend_values": trend_values if trend_values else ["Sem dados"]
                        })
                audit_data["zabbix_server_os_metrics"] = os_metrics
        except OperationCancelled:
            raise
        except Exception as e:
            self._warn(f"Aviso: falha ao coletar métricas de SO do host do Zabbix Server: {e}")

        check_cancelled()
        audit_data["_collection_metadata"] = {
            "schema_version": 1,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "zabbix_version": self.api_version,
            "anonymized": False,
            "warnings": [*self.compatibility_warnings, *self.collection_warnings],
            "api_call_count": api_call_count,
        }
        self.api_call = original_api_call
        del self._collection_original_api_call
        report_progress("Coleta concluída", 95)
        return audit_data
