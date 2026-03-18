#!/usr/bin/fish
if not type -q xhost
    echo "Erro: 'xhost' não encontrado. No CachyOS (Arch), instale com: sudo pacman -S xorg-xhost"
    exit 1
end

xhost +local:root > /dev/null
sudo -E docker run -it --rm \
  --name auditoria_zabbix_app \
  --net host \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY \
  -v $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:/tmp/$WAYLAND_DISPLAY:rw \
  -e XDG_RUNTIME_DIR=/tmp \
  -v "$PWD:/app/meus_relatorios" \
#  -v "$PWD:/templates:/app/templates" \
#  -v "$PWD:/prompts:/app/prompts" \
#  -v "$PWD:/app" \
  auditoria-zabbix