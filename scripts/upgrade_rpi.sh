#!/usr/bin/env bash
# =============================================================================
# Jukeplayer backend — upgrade an existing RPi installation.
# Pulls the latest code on the checked-out branch, syncs dependencies,
# restarts the service. Config (data/config.json) and covers are untouched.
# Usage: bash scripts/upgrade_rpi.sh
# =============================================================================
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "==> Updating ${PWD} (branch: ${BRANCH})"
git pull --ff-only

echo "==> Syncing dependencies..."
./venv/bin/pip install -r requirements.txt -q

echo "==> Restarting service..."
sudo systemctl restart jukeplayer.service
sleep 2
systemctl --no-pager --lines=5 status jukeplayer.service || true
echo "==> Upgrade done. (config data in ./data is untouched)"