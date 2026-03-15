import requests
import json
import config

ZABBIX_API_VERSION = None
USE_HEADER_AUTH = False

def zabbix_api_call(method, params, auth=None):
    """
    Função genérica para realizar chamadas na API do Zabbix.
    Levanta exceções em caso de erro de conexão ou erro da API.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }

    headers = {'Content-Type': 'application/json-rpc'}
    
    if auth:
        if USE_HEADER_AUTH:
            headers['Authorization'] = f"Bearer {auth}"
        else:
            payload["auth"] = auth

    try:
        response = requests.post(config.ZABBIX_URL, data=json.dumps(payload), headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            raise Exception(f"Erro na API do Zabbix ({method}): {result['error']['data']}")
            
        return result.get("result")
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Erro de conexão com o Zabbix em {config.ZABBIX_URL}: {e}")

def discover_zabbix_version():
    """
    Descobre a versão do Zabbix para determinar o formato de autenticação.
    """
    global ZABBIX_API_VERSION, USE_HEADER_AUTH
    try:
        ZABBIX_API_VERSION = zabbix_api_call("apiinfo.version", {})
        
        if ZABBIX_API_VERSION:
            parts = ZABBIX_API_VERSION.split('.')
            if len(parts) >= 2:
                major, minor = int(parts[0]), int(parts[1])
                if major > 6 or (major == 6 and minor >= 4):
                    USE_HEADER_AUTH = True
        return ZABBIX_API_VERSION, USE_HEADER_AUTH
    except Exception as e:
        # Não levanta exceção aqui, pois a autenticação pode funcionar no modo antigo
        print(f"Aviso: Não foi possível descobrir a versão do Zabbix antecipadamente: {e}")
        return None, False

def authenticate_zabbix():
    """
    Realiza a autenticação no Zabbix e retorna o token de sessão.
    """
    params = {
        "username": config.ZABBIX_USER,
        "password": config.ZABBIX_PASS
    }
    return zabbix_api_call("user.login", params)

def logout_zabbix(auth_token):
    """
    Encerra a sessão da API do Zabbix.
    """
    if auth_token:
        try:
            zabbix_api_call("user.logout", [], auth=auth_token)
            return True
        except Exception as e:
            # Não crítico se o logout falhar, apenas registra
            print(f"Aviso: Falha ao encerrar a sessão do Zabbix: {e}")
            return False

def collect_zabbix_data(auth_token):
    """
    Coleta as informações vitais do ambiente Zabbix para a auditoria.
    """
    audit_data = {}

    # 1. Versão do Zabbix
    audit_data["zabbix_version"] = ZABBIX_API_VERSION

    # 2. Resumo de Hosts e Status
    hosts = zabbix_api_call("host.get", {
        "output": ["hostid", "host", "status"],
        "selectInterfaces": ["interfaceid", "type"]
    }, auth_token)
    
    if hosts:
        audit_data["total_hosts"] = len(hosts)
        audit_data["monitored_hosts"] = len([h for h in hosts if h["status"] == "0"])
        audit_data["disabled_hosts"] = len([h for h in hosts if h["status"] == "1"])
        audit_data["disabled_hosts_samples"] = [h["host"] for h in hosts if h["status"] == "1"][:15] # Pega até 15 nomes como exemplo

    # 3. Análise de Itens
    items = zabbix_api_call("item.get", {
        "output": ["itemid", "name", "type", "delay", "key_"],
        "filter": {"status": "0"}
    }, auth_token)

    if items:
        audit_data["total_active_items"] = len(items)
        
        external_checks = [i for i in items if i["type"] == "10"]
        audit_data["external_checks_count"] = len(external_checks)
        audit_data["external_checks_samples"] = [i["key_"] for i in external_checks[:10]]
        
        aggressive_items = []
        for i in items:
            delay_str = i["delay"].replace("s", "")
            if delay_str.isdigit() and int(delay_str) < 30:
                aggressive_items.append({"name": i["name"], "delay": i["delay"], "key": i["key_"]})
        
        audit_data["aggressive_polling_count"] = len(aggressive_items)
        audit_data["aggressive_polling_samples"] = aggressive_items[:10]

    # 4. Templates Utilizados
    templates = zabbix_api_call("template.get", {
        "output": ["host"]
    }, auth_token)
    
    if templates:
        audit_data["total_templates"] = len(templates)
        template_names = [t["host"] for t in templates]
        audit_data["templates_list"] = template_names
        
        # Identifica se existem templates de Banco de Dados ou Web (Frontend)
        db_web_keywords = ['mysql', 'postgresql', 'oracle', 'sql', 'nginx', 'apache', 'iis', 'web']
        audit_data["db_web_templates_in_use"] = [name for name in template_names if any(kw in name.lower() for kw in db_web_keywords)]

    # 5. Coleta de Histórico e Tendência: Saúde Interna do Zabbix Server
    internal_items = zabbix_api_call("item.get", {
        "output": ["itemid", "name", "key_", "value_type"],
        "filter": {"type": "5", "status": "0"},
        "search": {"key_": "zabbix["},
        "limit": 200
    }, auth_token)

    server_health = []
    if internal_items:
        for item in internal_items:
            critical_keys = ["zabbix[process,poller", "zabbix[process,history", "zabbix[queue", "zabbix[rcache", "zabbix[wcache"]
            if any(k in item["key_"] for k in critical_keys):
                history_data = zabbix_api_call("history.get", {
                    "output": "extend",
                    "history": item["value_type"],
                    "itemids": item["itemid"],
                    "sortfield": "clock",
                    "sortorder": "DESC",
                    "limit": 15
                }, auth_token)
                
                if history_data:
                    # Pega os valores e inverte para ficar em ordem cronológica (mais antigo -> mais recente)
                    trend_values = [h["value"] for h in history_data]
                    trend_values.reverse()
                else:
                    trend_values = ["Sem dados"]
                    
                server_health.append({
                    "metric_name": item["name"],
                    "key": item["key_"],
                    "recent_trend_values": trend_values
                })
        
        audit_data["zabbix_server_health_metrics"] = server_health

    # 6. Coleta de Status dos Proxies
    proxies = zabbix_api_call("proxy.get", {
        "output": "extend"
    }, auth_token)
    
    audit_data["total_proxies"] = len(proxies) if proxies else 0
    audit_data["proxies_details"] = proxies if proxies else []

    return audit_data