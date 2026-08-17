#!/usr/bin/fish
argparse --name=build_image 'p/push' -- $argv
or exit 2

set -l local_image auditoria-zabbix:latest
set -l remote_image fernandord/auditoria-zabbix

docker build -t $local_image .
or exit $status

if not set -q _flag_push
    echo "Imagem criada localmente: $local_image"
    echo "Nenhum push foi realizado. Use --push para publicar deliberadamente."
    exit 0
end

echo "ATENÇÃO: --push publicará $remote_image:latest e $remote_image:v3 no Docker Hub."
read --local --prompt-str "Digite PUSH para confirmar: " confirmation
if test "$confirmation" != PUSH
    echo "Push cancelado; a imagem local foi preservada."
    exit 1
end

docker tag $local_image $remote_image:latest
or exit $status
docker tag $local_image $remote_image:v3
or exit $status
docker login
or exit $status
docker push $remote_image:v3
or exit $status
docker push $remote_image:latest
