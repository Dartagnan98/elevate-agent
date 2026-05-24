#!/bin/bash
# Deploy elevate-hq backend to Hetzner.
# Run from ~/elevate/backend on local machine.
#
# Why rsync and not git pull on the box: a lot of files live untracked in the
# local working tree (held back until git hygiene gets sorted), so the box
# needs the working tree itself. Once everything is committed + pushed,
# this can be swapped for `git pull && npm ci && npm run build`.
set -euo pipefail

HOST="root@5.78.46.234"
REMOTE_DIR="/root/elevation-hq/backend"

cd "$(dirname "$0")/.."

echo "[deploy] rsyncing working tree to $HOST:$REMOTE_DIR"
rsync -avz --delete \
  --exclude=node_modules \
  --exclude=.next \
  --exclude=.vercel \
  --exclude=.git \
  --exclude=.env \
  --exclude=.env.local \
  --exclude=.env.production.local \
  ./ "$HOST:$REMOTE_DIR/" | tail -5

echo "[deploy] installing deps + building on remote"
ssh "$HOST" "cd $REMOTE_DIR && npm ci --no-audit --no-fund --silent && NODE_ENV=production npm run build" 2>&1 | tail -10

echo "[deploy] reloading PM2"
ssh "$HOST" "pm2 reload elevation-hq --update-env"

echo "[deploy] smoke test"
curl -sf https://api.elevationrealestatehq.com/api/health && echo
echo "[deploy] live at https://api.elevationrealestatehq.com"
