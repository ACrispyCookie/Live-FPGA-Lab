#!/usr/bin/env bash
# Sync this checkout to the production host and rebuild the web-api image there.
#
#   scripts/deploy-vm2.sh            sync, build web-api, restart it
#   scripts/deploy-vm2.sh --no-build sync only
#
# Copies with tar over ssh (vm2 has no rsync). Never copies .env, node_modules, the built
# static folder, bitstreams or ELFs, and never deletes anything on vm2 (the untracked demo
# folders there must survive). VITE_MOCK_STATES=1 in the environment enables the
# ?mock=<state> switch in the build.
set -euo pipefail

cd "$(dirname "$0")/.."
host=${DEPLOY_HOST:-vm2}
dest=${DEPLOY_DIR:-'~/Live-FPGA-Lab'}

tar czf - \
  --exclude='./.git' --exclude='./.venv' --exclude='./.venv-checks' --exclude='./.superpowers' \
  --exclude='node_modules' --exclude='./src/web_api/static' --exclude='.env' --exclude='.env.*' \
  --exclude='*.bit' --exclude='*.elf' --exclude='__pycache__' --exclude='./docs' --exclude='.pytest_cache' \
  . | ssh "$host" "mkdir -p $dest && cd $dest && tar xzf -"
echo "synced to $host:$dest"

if [ "${1:-}" = "--no-build" ]; then
  exit 0
fi

# A VITE_MOCK_STATES set in this shell wins; otherwise the host's .env decides (compose reads it).
mock_env=${VITE_MOCK_STATES:+VITE_MOCK_STATES=$VITE_MOCK_STATES }
ssh "$host" "cd $dest && ${mock_env}docker compose build web-api && docker compose up -d web-api && docker compose ps web-api"
