#!/usr/bin/env bash
# Native ROS 2 Lyrical plus an isolated Space ROS development image.
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase9 ROS start =="

. /etc/os-release
if [ "${VERSION_CODENAME:-}" != resolute ]; then
  log "ROS phase requires Ubuntu 26.04 resolute; found ${VERSION_CODENAME:-unknown}"
  exit 1
fi

# The official ros2-apt-source package owns repository keys and source files.
if ! dpkg -s ros2-apt-source >/dev/null 2>&1; then
  version="$(curl -fsSL https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | jq -r .tag_name)"
  if [ -z "$version" ] || [ "$version" = null ]; then
    log "FAILED to identify ros2-apt-source release"
    exit 1
  fi
  deb="$(mktemp --suffix=.deb)"
  url="https://github.com/ros-infrastructure/ros-apt-source/releases/download/${version}/ros2-apt-source_${version}.resolute_all.deb"
  if curl -fL --retry 3 "$url" -o "$deb" >>"$LOG" 2>&1 && \
     sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$deb" >>"$LOG" 2>&1; then
    log "installed ros2-apt-source $version"
  else
    log "FAILED installing ros2-apt-source $version"
    rm -f "$deb"
    exit 1
  fi
  rm -f "$deb"
fi

sudo apt-get update >>"$LOG" 2>&1 || { log "FAILED ROS apt update"; exit 1; }
apt_try ros-dev-tools ros-lyrical-desktop python3-rosdep
if command -v rosdep >/dev/null 2>&1; then
  [ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || \
    sudo rosdep init >>"$LOG" 2>&1 || log "rosdep init needs attention"
  rosdep update >>"$LOG" 2>&1 || log "rosdep update needs attention"
fi

mkdir -p "$HOME/Workspaces/ros2_lyrical/src" "$HOME/Workspaces/space_ros/src" "$HOME/Scripts"
for name in ros-lyrical-env.sh space-ros-shell.sh; do
  if [ -e "$HOME/Scripts/$name" ]; then
    log "preserved existing $HOME/Scripts/$name"
  else
    install -m 755 "$root/config/ros/$name" "$HOME/Scripts/$name"
    log "created $HOME/Scripts/$name"
  fi
done

space_image="osrf/space-ros:jazzy-2026.07.0-dev"
space_ready=0
if command -v docker >/dev/null 2>&1; then
  if sudo docker image inspect "$space_image" >/dev/null 2>&1; then
    log "Space ROS dev image already present"
    space_ready=1
  elif sudo docker pull "$space_image" >>"$LOG" 2>&1; then
    log "pulled Space ROS dev image"
    space_ready=1
  else
    log "Space ROS dev image pull FAILED; retry after Docker is healthy"
  fi
else
  log "Docker missing; Space ROS image deferred"
fi

if [ -f /opt/ros/lyrical/setup.bash ]; then
  log "ROS 2 Lyrical installed"
else
  log "ROS 2 Lyrical setup file missing; see setup.log"
  exit 1
fi
log "== phase9 ROS done =="
[ "$space_ready" -eq 1 ]
