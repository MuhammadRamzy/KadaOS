#!/usr/bin/env bash
# Local SearXNG (free metasearch) for AI web answers. Container is created stopped; the chat starts it on demand.
#   bash scripts/install-search.sh          create/refresh the container
#   docker rm -f searxng                    remove it (config in ~/.config/searxng)
set -euo pipefail
cfg=~/.config/searxng; mkdir -p "$cfg"
if [ ! -f "$cfg/settings.yml" ]; then
  sed "s/SECRET_KEY_PLACEHOLDER/$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')/" \
    "$(dirname "$0")/../config/searxng/settings.yml" > "$cfg/settings.yml"; chmod 644 "$cfg/settings.yml"  # container user must read it; key only signs localhost cookies
fi
docker pull -q searxng/searxng:latest >/dev/null
docker rm -f searxng >/dev/null 2>&1 || true
# 127.0.0.1 only: never reachable from the LAN. No --restart: it runs only while used.
# Mount only the settings file read-only: mounting the folder lets the image chown it to its own user.
docker create --name searxng -p 127.0.0.1:8888:8080 -v "$cfg/settings.yml:/etc/searxng/settings.yml:ro" \
  --cap-drop ALL --cap-add CHOWN --cap-add SETGID --cap-add SETUID searxng/searxng:latest >/dev/null
echo "searxng container ready (stopped). Test: docker start searxng && curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 200"
