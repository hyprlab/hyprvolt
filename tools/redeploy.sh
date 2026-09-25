#!/usr/bin/env bash
# Rebuild the local container from the working tree and restart it, so a
# change can be tried in the running app. This is the test loop after every
# change; it publishes nothing.
#
#   tools/redeploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --build
port=$(docker compose port "$(docker compose config --services | head -1)" 8000 | cut -d: -f2)
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; then
        echo "Up: http://localhost:$port ($(curl -fsS "http://127.0.0.1:$port/healthz"))"
        exit 0
    fi
    sleep 1
done
echo "The container did not become healthy. Logs:" >&2
docker compose logs --tail 40 >&2
exit 1
