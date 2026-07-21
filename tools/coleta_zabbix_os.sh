#!/bin/bash
# Script de Coleta de Evidências de SO para Auditoria Zabbix
# Execute este script no servidor Zabbix do cliente.
set -uo pipefail

OUTPUT_FILE="evidencias_os_zabbix_$(hostname)_$(date +%Y%m%d_%H%M%S).txt"

echo "Iniciando coleta de evidências do Sistema Operacional..."
echo "O arquivo será salvo como: $OUTPUT_FILE"

{
    echo "=========================================================="
    echo "DATA E HORA: $(date)"
    echo "HOSTNAME: $(hostname)"
    echo "UPTIME: $(uptime)"
    echo "=========================================================="
    
    echo -e "\n[SISTEMA OPERACIONAL]"
    if [ -f /etc/os-release ]; then
        grep -E "^PRETTY_NAME=|^VERSION=" /etc/os-release
    else
        echo "Arquivo /etc/os-release não encontrado."
    fi
    
    echo -e "\n[USO DE MEMÓRIA (free -m)]"
    free -m
    
    echo -e "\n[USO DE DISCO (df -h)]"
    df -h | grep -v "tmpfs\|devtmpfs"
    
    echo -e "\n[TOP 20 PROCESSOS CONSUMINDO CPU/MEMÓRIA]"
    top -b -n 1 | head -n 25
    
    echo -e "\n[STATUS DO SERVIÇO ZABBIX SERVER]"
    systemctl status zabbix-server --no-pager -l || echo "Serviço zabbix-server não encontrado ou usando outro gerenciador."
    
    echo -e "\n[CONFIGURAÇÕES ATIVAS DO ZABBIX SERVER (zabbix_server.conf)]"
    # Extrai o arquivo de configuração ignorando comentários e linhas em branco
    if [ -f /etc/zabbix/zabbix_server.conf ]; then
        grep -v "^#" /etc/zabbix/zabbix_server.conf | grep -v "^$"
    else
        echo "Arquivo /etc/zabbix/zabbix_server.conf não encontrado no caminho padrão."
    fi
} > "$OUTPUT_FILE"

echo "Coleta concluída! Baixe o arquivo $OUTPUT_FILE e anexe na ferramenta de auditoria."