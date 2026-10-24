#!/usr/bin/env bash
# Copy the bot sources to the server and restart the containers.
#
# .env and credentials.json are not copied — they live only on the server.
# sudo on the server asks for the password (docker requires root there).
#
# Server settings come from deploy.env (not committed), see deploy.env.example.
#
# Usage: ./deploy.sh            copy files and rebuild/restart containers
#        ./deploy.sh --no-up    copy files only
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f deploy.env ]]; then
    echo "deploy.env not found — copy deploy.env.example to deploy.env and fill it in" >&2
    exit 1
fi
# shellcheck source=/dev/null
source deploy.env

: "${SERVER_USER:?SERVER_USER is not set in deploy.env}"
: "${SERVER_IP:?SERVER_IP is not set in deploy.env}"
: "${SSH_KEY:?SSH_KEY is not set in deploy.env}"
REMOTE_DIR="${REMOTE_DIR:-EasyGoTracker}"  # relative to the remote home

FILES=(
    bot
    utils
    Dockerfile
    docker-compose.yml
    pyproject.toml
    uv.lock
    .env.example
)

REMOTE="${SERVER_USER}@${SERVER_IP}"
SSH_OPTS=(-i "$SSH_KEY")

# Don't ship local bytecode caches
find bot utils -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "==> Copying files to ${REMOTE}:${REMOTE_DIR}"
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p ${REMOTE_DIR}"
scp "${SSH_OPTS[@]}" -r "${FILES[@]}" "${REMOTE}:${REMOTE_DIR}/"

if [[ "${1:-}" == "--no-up" ]]; then
    echo "==> Files copied, containers not restarted"
    exit 0
fi

# The disk is small: prune before the build to make room for it, and after
# to drop the previous bot image.
echo "==> Rebuilding and restarting containers"
ssh -t "${SSH_OPTS[@]}" "$REMOTE" "cd ${REMOTE_DIR} \
    && sudo docker system prune -af \
    && sudo docker compose up -d --build \
    && sudo docker system prune -af \
    && sudo docker compose ps \
    && df -h /"

echo "==> Done. Logs: ssh -i $SSH_KEY $REMOTE 'sudo docker logs --tail 50 -f tracker_bot'"
