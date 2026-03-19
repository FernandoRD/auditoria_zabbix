#!/usr/bin/fish
docker build --build-arg CACHEBUST=$(date +%s) -t auditoria-zabbix .
docker tag auditoria-zabbix:latest fernandord/auditoria-zabbix:latest
docker tag auditoria-zabbix:latest fernandord/auditoria-zabbix:v3

docker login

docker image ls fernandord/auditoria-zabbix | grep ':v' | cut -f2 -d ':' | awk '{print $1}'

docker push fernandord/auditoria-zabbix:v3
docker push fernandord/auditoria-zabbix:latest
