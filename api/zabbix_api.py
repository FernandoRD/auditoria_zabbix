import requests
import json

class ZabbixClient:
    def __init__(self, url, user, password):
        self.url = url
        self.user = user
        self.password = password
        self.api_version = None
        self.use_header_auth = False
        self.auth_token = None

    def api_call(self, method, params, auth_required=True):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        headers = {'Content-Type': 'application/json-rpc'}
        
        if auth_required and self.auth_token:
            if self.use_header_auth:
                headers['Authorization'] = f"Bearer {self.auth_token}"
            else:
                payload["auth"] = self.auth_token

        try:
            response = requests.post(self.url, data=json.dumps(payload), headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                raise Exception(f"Erro na API do Zabbix ({method}): {result['error']['data']}")
                
            return result.get("result")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Erro de conexão com o Zabbix: {e}")

    def discover_version(self):
        try:
            self.api_version = self.api_call("apiinfo.version", {}, auth_required=False)
            if self.api_version:
                parts = self.api_version.split('.')
                if len(parts) >= 2:
                    major, minor = int(parts[0]), int(parts[1])
                    if major > 6 or (major == 6 and minor >= 4):
                        self.use_header_auth = True
            return self.api_version
        except Exception:
            return None

    def authenticate(self):
        self.auth_token = self.api_call("user.login", {
            "username": self.user,
            "password": self.password
        }, auth_required=False)
        return self.auth_token

    def logout(self):
        if self.auth_token:
            try:
                self.api_call("user.logout", [])
            except Exception:
                pass

    def get_active_node_hostid(self):
        """Identifica o hostid do nó Ativo em um cluster HA ou Standalone."""
        # 1. Tenta API Nativa de High Availability (Zabbix 6.0+)
        try:
            nodes = self.api_call("hanode.get", {"filter": {"status": "3"}}) # 3 = Active
            if nodes and len(nodes) > 0:
                node_name = nodes[0].get("name")
                if node_name:
                    hosts = self.api_call("host.get", {"filter": {"host": node_name}})
                    if hosts:
                        return hosts[0]["hostid"]
        except Exception:
            pass
            
        # 2. Descobre ativamente rastreando itens internos com dados recentes (À prova de falhas)
        try:
            internal_items = self.api_call("item.get", {
                "output": ["itemid", "hostid", "value_type"],
                "search": {"key_": "zabbix[process,poller"},
                "filter": {"type": "5", "status": "0"}
            })
            if internal_items:
                host_history = {}
                for item in internal_items:
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
        except Exception:
            pass
            
        # 3. Fallback genérico para Zabbix Standalone clássico
        try:
            hosts = self.api_call("host.get", {"filter": {"host": "Zabbix server"}})
            if hosts:
                return hosts[0]["hostid"]
        except Exception:
            pass
        return None

    def collect_data(self):
    def collect_data(self, history_limit=500, sample_limit=15, template_limit=50):
        audit_data = {}
        audit_data["zabbix_version"] = self.api_version

        # 2. Resumo de Hosts e Status
        hosts = self.api_call("host.get", {
            "output": ["hostid", "host", "status"],
            "selectInterfaces": ["interfaceid", "type"]
        })
        if hosts:
            audit_data["total_hosts"] = len(hosts)
            audit_data["monitored_hosts"] = len([h for h in hosts if h["status"] == "0"])
            audit_data["disabled_hosts"] = len([h for h in hosts if h["status"] == "1"])
            audit_data["disabled_hosts_samples"] = [h["host"] for h in hosts if h["status"] == "1"][:15]
            audit_data["disabled_hosts_samples"] = [h["host"] for h in hosts if h["status"] == "1"][:sample_limit]
            
        # Grupos de Hosts
        try:
            hgroups = self.api_call("hostgroup.get", {"output": ["name"]})
            audit_data["total_host_groups"] = len(hgroups) if hgroups else 0
        except Exception: pass

        # 3. Análise de Itens
        items = self.api_call("item.get", {
            "output": ["itemid", "name", "type", "delay", "key_", "state"],
            "filter": {"status": "0"}
        })
        if items:
            audit_data["total_active_items"] = len(items)
            external_checks = [i for i in items if i["type"] == "10"]
            audit_data["external_checks_count"] = len(external_checks)
            audit_data["external_checks_samples"] = [i["key_"] for i in external_checks[:10]]
            audit_data["external_checks_samples"] = [i["key_"] for i in external_checks[:sample_limit]]
            
            aggressive_items = []
            for i in items:
                delay_str = i["delay"].replace("s", "")
                if delay_str.isdigit() and int(delay_str) < 30:
                    aggressive_items.append({"name": i["name"], "delay": i["delay"], "key": i["key_"]})
            
            audit_data["aggressive_polling_count"] = len(aggressive_items)
            audit_data["aggressive_polling_samples"] = aggressive_items[:10]
            audit_data["aggressive_polling_samples"] = aggressive_items[:sample_limit]
            
            unsupported_items = [i for i in items if i.get("state") == "1"]
            audit_data["unsupported_items_count"] = len(unsupported_items)
            audit_data["unsupported_items_samples"] = [i["key_"] for i in unsupported_items[:10]]
            audit_data["unsupported_items_samples"] = [i["key_"] for i in unsupported_items[:sample_limit]]

        # 4. Templates Utilizados
        templates = self.api_call("template.get", {"output": ["host"]})
        if templates:
            audit_data["total_templates"] = len(templates)
            template_names = [t["host"] for t in templates]
            audit_data["templates_list_sample"] = template_names[:50] # Limita a lista global para não estourar o contexto da IA
            audit_data["templates_list_sample"] = template_names[:template_limit] # Limita a lista global para não estourar o contexto da IA

        # Templates específicos aplicados na Infra do Zabbix (Server)
        active_hostid = self.get_active_node_hostid()
        audit_data["zabbix_server_templates"] = []
        if active_hostid:
            server_templates = self.api_call("template.get", {
                "output": ["host"], "hostids": active_hostid
            })
            if server_templates:
                audit_data["zabbix_server_templates"] = [t["host"] for t in server_templates]

        # 5. Coleta de Histórico: Saúde Interna
        item_params = {
            "output": ["itemid", "name", "key_", "value_type"],
            "filter": {"type": "5", "status": "0"},
            "search": {"key_": "zabbix["},
            "limit": 200
        }
        
        if active_hostid:
            item_params["hostids"] = active_hostid
            
        internal_items = self.api_call("item.get", item_params)
        server_health = []
        if internal_items:
            for item in internal_items:
                critical_keys = ["zabbix[process,poller", "zabbix[process,history", "zabbix[queue", "zabbix[rcache", "zabbix[wcache"]
                if any(k in item["key_"] for k in critical_keys):
                    history_data = self.api_call("history.get", {
                        "output": ["value"],
                        "history": item["value_type"],
                        "itemids": item["itemid"],
                        "sortfield": "clock",
                        "sortorder": "DESC",
                        "limit": 500
                        "limit": history_limit
                    })
                    if history_data:
                        # Faz amostragem (pega ~15 pontos distribuídos num pool de 500)
                        # Isso abrange horas/dias de histórico ao invés de apenas minutos recentes
                        step = max(1, len(history_data) // 15)
                        trend_values = [h["value"] for h in history_data[0::step]][:15]
                        trend_values.reverse()
                    else:
                        trend_values = ["Sem dados"]
                        
                    server_health.append({
                        "metric_name": item["name"],
                        "key": item["key_"],
                        "recent_trend_values": trend_values
                    })
            audit_data["zabbix_server_health_metrics"] = server_health

        # 6. Coletas Extras de Higiene e Risco
        # NVPS (New Values Per Second)
        try:
            nvps_item = self.api_call("item.get", {"output": ["lastvalue"], "search": {"key_": "zabbix[wcache,values"}, "hostids": active_hostid})
            audit_data["nvps"] = nvps_item[0].get("lastvalue", "0") if nvps_item else "Desconhecido"
        except Exception: pass

        # Triggers Órfãs ou Quebradas
        try:
            triggers = self.api_call("trigger.get", {"output": ["state"], "filter": {"status": "0"}})
            if triggers:
                audit_data["total_active_triggers"] = len(triggers)
                audit_data["unsupported_triggers_count"] = len([t for t in triggers if t.get("state") == "1"])
        except Exception: pass

        # Discovery Rules (Regras de Descoberta Ativas)
        try:
            drules = self.api_call("drule.get", {"output": ["name", "delay", "iprange"], "filter": {"status": "0"}})
            audit_data["active_discovery_rules_count"] = len(drules) if drules else 0
            audit_data["active_discovery_rules_samples"] = drules[:5] if drules else []
            audit_data["active_discovery_rules_samples"] = drules[:sample_limit] if drules else []
        except Exception: pass

        # Alertas Falhos (Emails que não estão saindo)
        try:
            failed_alerts = self.api_call("alert.get", {"output": ["error"], "filter": {"status": "2"}, "limit": 100})
            audit_data["recent_failed_alerts_count"] = len(failed_alerts) if failed_alerts else 0
            if failed_alerts:
                audit_data["failed_alerts_errors_samples"] = list(set([a.get("error", "") for a in failed_alerts if a.get("error")]))[:5]
                audit_data["failed_alerts_errors_samples"] = list(set([a.get("error", "") for a in failed_alerts if a.get("error")]))[:sample_limit]
        except Exception: pass

        # Problemas Críticos Não Reconhecidos
        try:
            problems = self.api_call("problem.get", {"output": ["name", "severity"], "filter": {"acknowledged": "0"}, "severities": [4, 5], "source": 0, "object": 0, "limit": 20})
            audit_data["unacknowledged_critical_problems_count"] = len(problems) if problems else 0
            audit_data["unacknowledged_critical_problems_samples"] = [p.get("name") for p in problems[:5]] if problems else []
            audit_data["unacknowledged_critical_problems_samples"] = [p.get("name") for p in problems[:sample_limit]] if problems else []
        except Exception: pass

        # Configurações de Banco de Dados (Housekeeping)
        try:
            housekeeping = self.api_call("housekeeping.get", {"output": "extend"})
            if isinstance(housekeeping, list) and len(housekeeping) > 0:
                audit_data["housekeeping_config"] = housekeeping[0]
            else:
                audit_data["housekeeping_config"] = housekeeping
        except Exception: pass

        # Governança e Segurança: Usuários Super Admin
        try:
            users = self.api_call("user.get", {"output": ["username", "type", "roleid"]})
            super_admins = []
            if users:
                for u in users:
                    # Suporte a versões <= 5.0 (type 3) e >= 5.2 (roleid 3 para SA default)
                    if str(u.get("type")) == "3" or str(u.get("roleid")) == "3":
                        super_admins.append(u.get("username", u.get("alias", "Desconhecido")))
            audit_data["super_admin_users_count"] = len(super_admins)
            audit_data["super_admin_users_samples"] = super_admins[:10]
            audit_data["super_admin_users_samples"] = super_admins[:sample_limit]
        except Exception: pass

        # 7. Operação, ITSM e Automação
        # Manutenções Ativas (Pontos Cegos)
        try:
            maintenances = self.api_call("maintenance.get", {"output": ["name", "active"]})
            active_maint = [m for m in maintenances if str(m.get("active", "")) == "1"] if maintenances else []
            audit_data["active_maintenances_count"] = len(active_maint)
            audit_data["active_maintenances_samples"] = [m.get("name") for m in active_maint[:5]]
            audit_data["active_maintenances_samples"] = [m.get("name") for m in active_maint[:sample_limit]]
        except Exception: pass

        # Integrações / Canais de Notificação
        try:
            mediatypes = self.api_call("mediatype.get", {"output": ["name", "type"], "filter": {"status": "0"}})
            audit_data["active_mediatypes_count"] = len(mediatypes) if mediatypes else 0
            audit_data["active_mediatypes_samples"] = [m.get("name") for m in mediatypes] if mediatypes else []
            audit_data["active_mediatypes_samples"] = [m.get("name") for m in mediatypes][:sample_limit] if mediatypes else []
        except Exception: pass

        # Serviços de Negócio (SLA/ITSM)
        try:
            services = self.api_call("service.get", {"output": ["name"]})
            audit_data["business_services_count"] = len(services) if services else 0
        except Exception: pass

        # Scripts Globais de Frontend
        try:
            scripts = self.api_call("script.get", {"output": ["name"]})
            audit_data["global_scripts_count"] = len(scripts) if scripts else 0
            audit_data["global_scripts_samples"] = [s.get("name") for s in scripts[:5]] if scripts else []
            audit_data["global_scripts_samples"] = [s.get("name") for s in scripts[:sample_limit]] if scripts else []
        except Exception: pass

        # 8. Análise de Proxies
        proxies_details = []
        try:
            proxies = self.api_call("proxy.get", {
                "output": ["name", "operating_mode", "version", "lastaccess"],
                "selectHosts": ["hostid"],
                "selectProxyGroup": ["name"]
            })
            if proxies:
                for proxy in proxies:
                    proxy_detail = {
                        "name": proxy.get("name"),
                        "operating_mode": "Ativo" if proxy.get("operating_mode") == "0" else "Passivo",
                        "version": proxy.get("version"),
                        "lastaccess_timestamp": proxy.get("lastaccess"),
                        "groups": [g['name'] for g in proxy.get('proxyGroups', [])],
                        "host_count": len(proxy.get('hosts', [])),
                    }
                    proxies_details.append(proxy_detail)
        except Exception as e:
            # Em um ambiente de produção, seria ideal logar este erro para facilitar o debug.
            # Ex: self.view.log(f"Aviso: Falha ao coletar detalhes dos proxies: {e}", "warning")
            pass
        audit_data["total_proxies"] = len(proxies_details)
        audit_data["proxies_details"] = proxies_details

        return audit_data