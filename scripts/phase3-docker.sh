#!/usr/bin/env bash
# Phase 3: Docker Engine + Compose (official repo) and compose templates
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
log "== phase3 start =="
if ! command -v docker >/dev/null; then
  cn=$(. /etc/os-release; echo "$VERSION_CODENAME")
  if curl -fsI "https://download.docker.com/linux/ubuntu/dists/$cn/Release" >/dev/null 2>&1; then
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $cn stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update >>"$LOG" 2>&1
    apt_try docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    log "Docker vendor repo unavailable for $cn; using Ubuntu packages"
    apt_try docker.io docker-compose-v2
  fi
fi
if ! command -v docker >/dev/null 2>&1; then
  log "Docker command still missing; trying Ubuntu packages"
  apt_try docker.io docker-compose-v2
fi
if command -v docker >/dev/null; then
  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    sudo usermod -aG docker "$USER" && log "added to docker group (re-login needed)"
  fi
else
  log "Docker command missing after package installation"
fi
# lazydocker
if ! command -v lazydocker >/dev/null; then
  v=$(curl -s https://api.github.com/repos/jesseduffield/lazydocker/releases/latest | jq -r .tag_name | tr -d v)
  [ -n "$v" ] && [ "$v" != null ] && curl -sL "https://github.com/jesseduffield/lazydocker/releases/download/v${v}/lazydocker_${v}_Linux_x86_64.tar.gz" | tar xz -C ~/.local/bin lazydocker && log "lazydocker $v"
fi
d=~/Containers/local-services; mkdir -p "$d"
[ -f "$d/compose.yaml" ] || cat > "$d/compose.yaml" <<'Y'
# Start only what you need:  docker compose --profile db up -d
# Ports bound to 127.0.0.1 only. Change passwords via .env (not committed).
services:
  postgres:
    image: postgres:17
    profiles: [db]
    environment: { POSTGRES_PASSWORD: "${PG_PASSWORD:-devonly}" }
    ports: ["127.0.0.1:5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: valkey/valkey:8
    profiles: [db, cache]
    ports: ["127.0.0.1:6379:6379"]
  mongo:
    image: mongo:8
    profiles: [mongo]
    ports: ["127.0.0.1:27017:27017"]
    volumes: [mongodata:/data/db]
  minio:
    image: minio/minio
    profiles: [storage]
    command: server /data --console-address ":9001"
    ports: ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"]
    volumes: [miniodata:/data]
  mailpit:
    image: axllent/mailpit
    profiles: [mail]
    ports: ["127.0.0.1:8025:8025", "127.0.0.1:1025:1025"]
  prometheus:
    image: prom/prometheus
    profiles: [monitoring]
    ports: ["127.0.0.1:9090:9090"]
  grafana:
    image: grafana/grafana
    profiles: [monitoring]
    ports: ["127.0.0.1:3000:3000"]
    volumes: [grafanadata:/var/lib/grafana]
  otel-collector:
    image: otel/opentelemetry-collector
    profiles: [monitoring]
    ports: ["127.0.0.1:4317:4317"]
volumes: { pgdata: {}, mongodata: {}, miniodata: {}, grafanadata: {} }
Y
log "== phase3 done =="
command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
