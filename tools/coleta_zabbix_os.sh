#!/bin/bash
# Script de Coleta de Evidencias de SO para Auditoria Zabbix
# Execute este script no servidor Zabbix do cliente.
set -uo pipefail

OS_RELEASE_FILE="${ZABBIX_OS_RELEASE_FILE:-/etc/os-release}"
ZABBIX_CONF_FILE="${ZABBIX_SERVER_CONF_FILE:-/etc/zabbix/zabbix_server.conf}"
OUTPUT_FILE="${ZABBIX_EVIDENCE_OUTPUT_FILE:-evidencias_os_zabbix_$(hostname)_$(date +%Y%m%d_%H%M%S).txt}"

# Evidencias podem conter dados internos; arquivos novos ficam acessiveis apenas
# pelo usuario que executou o coletor.
umask 077

redact_sensitive_lines() {
    awk '
        {
            lowered = tolower($0)
            if (lowered ~ /(password|passwd|secret|token|community|psk|credential)/) {
                print "[REDACTED: linha potencialmente sensivel omitida]"
                next
            }
            print
        }
    '
}

collect_safe_zabbix_config() {
    awk '
        BEGIN {
            safe_keys = "LogType LogFile LogFileSize DebugLevel PidFile SocketDir ListenIP ListenPort StartPollers StartPollersUnreachable StartPreprocessors StartTrappers StartPingers StartDiscoverers StartHTTPPollers StartTimers StartEscalators StartAlerters StartLLDProcessors JavaGateway JavaGatewayPort StartJavaPollers SNMPTrapperFile StartSNMPTrapper HousekeepingFrequency MaxHousekeeperDelete CacheSize CacheUpdateFrequency StartDBSyncers HistoryCacheSize HistoryIndexCacheSize TrendCacheSize ValueCacheSize Timeout TrapperTimeout UnreachablePeriod UnavailableDelay UnreachableDelay LogSlowQueries StatsAllowedIP EnableGlobalScripts AllowRoot User"
            count = split(safe_keys, keys, " ")
            for (key_position = 1; key_position <= count; key_position++) {
                allowed[keys[key_position]] = 1
            }
        }
        {
            line = $0
            sub(/\r$/, "", line)
            if (line ~ /^[[:space:]]*($|#)/) {
                next
            }

            separator = index(line, "=")
            if (separator == 0) {
                next
            }

            key = substr(line, 1, separator - 1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            lowered_key = tolower(key)
            if (lowered_key ~ /(password|passwd|secret|token|community|psk|credential)/) {
                next
            }

            if (key in allowed) {
                print line
            }
        }
    ' "$ZABBIX_CONF_FILE"
}

echo "Iniciando coleta de evidencias do Sistema Operacional..."
echo "O arquivo sera salvo como: $OUTPUT_FILE"

{
    echo "=========================================================="
    echo "DATA E HORA: $(date)"
    echo "HOSTNAME: $(hostname)"
    echo "UPTIME: $(uptime)"
    echo "=========================================================="

    echo -e "\n[SISTEMA OPERACIONAL]"
    if [ -f "$OS_RELEASE_FILE" ]; then
        grep -E "^PRETTY_NAME=|^VERSION=" "$OS_RELEASE_FILE"
    else
        echo "Arquivo de identificacao do sistema operacional nao encontrado."
    fi

    echo -e "\n[USO DE MEMORIA (free -m)]"
    free -m

    echo -e "\n[USO DE DISCO (df -h)]"
    df -h | grep -v "tmpfs\|devtmpfs"

    echo -e "\n[TOP 20 PROCESSOS POR CPU: PID, EXECUTAVEL, CPU E MEMORIA]"
    printf '%-8s %-24s %8s %8s\n' "PID" "EXECUTAVEL" "%CPU" "%MEM"
    ps -eo pid=,comm=,pcpu=,pmem= --sort=-pcpu | awk 'NR <= 20'

    echo -e "\n[STATUS RESUMIDO DO SERVICO ZABBIX SERVER]"
    service_state="$(systemctl is-active zabbix-server 2>/dev/null || true)"
    service_enabled="$(systemctl is-enabled zabbix-server 2>/dev/null || true)"
    echo "ATIVO: ${service_state:-indisponivel}"
    echo "HABILITADO: ${service_enabled:-indisponivel}"

    echo -e "\n[CONFIGURACOES OPERACIONAIS DO ZABBIX SERVER (ALLOWLIST)]"
    if [ -f "$ZABBIX_CONF_FILE" ]; then
        collect_safe_zabbix_config
    else
        echo "Arquivo de configuracao do Zabbix Server nao encontrado no caminho configurado."
    fi
} | redact_sensitive_lines > "$OUTPUT_FILE"

echo "Coleta concluida! Baixe o arquivo $OUTPUT_FILE e anexe na ferramenta de auditoria."
