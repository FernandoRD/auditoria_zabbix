#!/usr/bin/env fish

function usage
    echo "Uso: "(status filename)" [--data-dir DIRETORIO] [--host-network]"
    echo ""
    echo "  --data-dir DIRETORIO  Diretório persistente para configurações e relatórios"
    echo "  --host-network         Usa a rede do host (desligado por padrão)"
end

set -l data_dir "$PWD/auditoria-zabbix-data"
set -l use_host_network 0

while test (count $argv) -gt 0
    switch $argv[1]
        case --help -h
            usage
            exit 0
        case --data-dir
            if test (count $argv) -lt 2
                echo "Erro: --data-dir exige um diretório." >&2
                exit 2
            end
            set data_dir "$argv[2]"
            set -e argv[1..2]
        case --host-network
            set use_host_network 1
            set -e argv[1]
        case '*'
            echo "Erro: argumento desconhecido: $argv[1]" >&2
            usage >&2
            exit 2
    end
end

if not type -q docker
    echo "Erro: Docker não encontrado no PATH." >&2
    exit 1
end

# Umask restritiva para settings, cache e arquivos temporários criados pela GUI.
umask 077
mkdir -p -- "$data_dir"
or begin
    echo "Erro: não foi possível criar o diretório de dados: $data_dir" >&2
    exit 1
end

set data_dir (realpath -- "$data_dir")
or begin
    echo "Erro: não foi possível resolver o diretório de dados." >&2
    exit 1
end

if not test -d "$data_dir"; or not test -w "$data_dir"
    echo "Erro: o diretório de dados deve existir e permitir escrita: $data_dir" >&2
    exit 1
end

chmod 700 -- "$data_dir"
or begin
    echo "Erro: não foi possível restringir as permissões do diretório de dados." >&2
    exit 1
end

# Docker usa ':' na sintaxe de volume; rejeitar separadores ambíguos evita uma
# montagem diferente da solicitada pelo usuário.
if string match -rq '[:,\n]' -- "$data_dir"
    echo "Erro: o diretório de dados não pode conter ':' ou quebra de linha." >&2
    exit 2
end

mkdir -p -- "$data_dir/tmp"
or begin
    echo "Erro: não foi possível preparar o diretório temporário." >&2
    exit 1
end

chmod 700 -- "$data_dir/tmp"
or begin
    echo "Erro: não foi possível restringir as permissões do diretório temporário." >&2
    exit 1
end

if not set -q DISPLAY
    echo "Erro: DISPLAY não está definido. Tk requer um servidor X11/XWayland." >&2
    exit 1
end

set -l display_number (string replace -r '^.*:' '' -- "$DISPLAY")
set display_number (string replace -r '\..*$' '' -- "$display_number")
if not string match -rq '^[0-9]+$' -- "$display_number"
    echo "Erro: DISPLAY inválido: $DISPLAY" >&2
    exit 2
end

set -l x11_socket "/tmp/.X11-unix/X$display_number"
if not test -S "$x11_socket"
    echo "Erro: socket X11 não encontrado: $x11_socket" >&2
    exit 1
end

set -l xauthority
if set -q XAUTHORITY
    set xauthority "$XAUTHORITY"
else if set -q HOME
    set xauthority "$HOME/.Xauthority"
end

if test -z "$xauthority"; or not test -r "$xauthority"
    echo "Erro: não foi encontrado um Xauthority legível. Defina XAUTHORITY para a sessão gráfica." >&2
    exit 1
end

set x11_socket (realpath -- "$x11_socket")
or begin
    echo "Erro: não foi possível resolver o socket X11." >&2
    exit 1
end

set xauthority (realpath -- "$xauthority")
or begin
    echo "Erro: não foi possível resolver o arquivo Xauthority." >&2
    exit 1
end

if string match -rq '[:,\n]' -- "$x11_socket" "$xauthority"
    echo "Erro: os paths de exibição não podem conter ':' ou quebra de linha." >&2
    exit 2
end

set -l docker_args \
    --interactive \
    --tty \
    --rm \
    --name auditoria_zabbix_app \
    --user (id -u):(id -g) \
    --workdir /data \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --env HOME=/data \
    --env TMPDIR=/data/tmp \
    --env "DISPLAY=$DISPLAY" \
    --env XAUTHORITY=/tmp/.Xauthority \
    --volume "$data_dir:/data:rw" \
    --volume "$x11_socket:$x11_socket:rw" \
    --volume "$xauthority:/tmp/.Xauthority:ro"

# Wayland é opcional: Tk usa X11/XWayland, mas, quando o socket nativo existe,
# ele também fica disponível para bibliotecas que o utilizem.
if set -q WAYLAND_DISPLAY; and set -q XDG_RUNTIME_DIR
    if string match -rq '^[A-Za-z0-9._-]+$' -- "$WAYLAND_DISPLAY"
        set -l candidate "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
        if test -S "$candidate"
            set candidate (realpath -- "$candidate")
            if not string match -rq '[:,\n]' -- "$candidate"
                set -a docker_args \
                    --env "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" \
                    --env XDG_RUNTIME_DIR=/tmp \
                    --volume "$candidate:/tmp/$WAYLAND_DISPLAY:rw"
            end
        else
            echo "Aviso: socket Wayland não encontrado; continuando somente com X11/XWayland." >&2
        end
    else
        echo "Aviso: WAYLAND_DISPLAY inválido; continuando somente com X11/XWayland." >&2
    end
end

if test $use_host_network -eq 1
    echo "Aviso: usando a rede do host por solicitação explícita." >&2
    set -a docker_args --network host
end

docker run $docker_args auditoria-zabbix
