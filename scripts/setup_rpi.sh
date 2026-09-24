#!/usr/bin/env bash
# =============================================================================
# Jukeplayer backend — one-shot setup for a dedicated Raspberry Pi.
# Target: Raspberry Pi OS Lite (Bookworm, 64-bit), run as the default user.
# Idempotent: safe to re-run. App dir default: /home/<user>/jukeplayer_backend
#
# Usage (on the Pi, from the repo checkout):
#   bash scripts/setup_rpi.sh [APP_DIR]
# =============================================================================
set -euo pipefail

APP_DIR="${1:-$HOME/jukeplayer_backend}"
APP_USER="$(id -un)"
APP_UID="$(id -u)"

echo "==> Jukeplayer setup on $(hostname) (user: ${APP_USER}, dir: ${APP_DIR})"

# --- System packages (audio: PulseAudio is the BT audio server — pipewire's
# bluez monitor never registers A2DP endpoints on this Pi 3 / bluez 5.82
# stack; see ledger "Phase C pre-work". mpv -> pulse -> bluez sink.)
# --no-install-recommends keeps this headless-Lite: no desktop/X stack, no
# yt-dlp & friends. (mpv still links a few X11/Wayland *client* libs — a few
# MB of shared libraries, not a desktop — needed by the package even for
# audio-only use; mpv runs with force_window=no.)
echo "==> Installing system packages (needs sudo)..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git python3 python3-venv python3-pip \
    mpv \
    pulseaudio pulseaudio-module-bluetooth pulseaudio-utils \
    bluez bluez-firmware rfkill \
    alsa-utils curl

# --- Bluetooth + audio server
# rfkill: fresh images can ship hci0 soft-blocked (boot-time finding 2026-09-24)
echo "==> Enabling bluetooth + PulseAudio audio server..."
sudo rfkill unblock bluetooth 2>/dev/null || true
sudo systemctl enable --now bluetooth 2>/dev/null || true
loginctl enable-linger "${APP_USER}" >/dev/null 2>&1 || \
    sudo loginctl enable-linger "${APP_USER}" || true
# PulseAudio provides the A2DP endpoints (user-session service)
systemctl --user enable --now pulseaudio.service pulseaudio.socket 2>/dev/null || true
# Disable the pipewire stack so it does not fight PulseAudio for the pulse socket
systemctl --user disable --now pipewire pipewire-pulse wireplumber \
    pipewire.socket pipewire-pulse.socket 2>/dev/null || true

# --- App directory: assume this script lives in the checked-out repo
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$(pwd -P)" != "${APP_DIR}" ] && [ "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)" != "${APP_DIR}" ]; then
    echo "==> Moving app to ${APP_DIR}..."
    mkdir -p "$(dirname "${APP_DIR}")"
    [ -d "${APP_DIR}" ] || cp -r "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)" "${APP_DIR}"
    cd "${APP_DIR}"
else
    cd "${APP_DIR}"
fi

# --- Python environment
echo "==> Python venv + dependencies..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt

# --- Runtime dirs + config store seed (speakers pre-filled; set the
#     Subsonic password via the web UI on first run)
mkdir -p data logs
[ -f data/config.json ] || cp deploy/config.seed.json data/config.json
chmod 600 data/config.json 2>/dev/null || true

# --- Environment file (full config until the config store lands)
if [ ! -f ".env" ]; then
    cp deploy/env.rpi.example .env
    echo "==> Created .env from deploy/env.rpi.example"
    echo "    >>> EDIT IT NOW: SUBSONIC_USER / SUBSONIC_PASS (+ speakers) <<<"
    ENV_EDITED=0
else
    echo "==> .env already present — keeping it"
    ENV_EDITED=1
fi

# --- systemd unit
echo "==> Installing systemd unit..."
sed -e "s|__APP_DIR__|${APP_DIR}|g" \
    -e "s|__APP_USER__|${APP_USER}|g" \
    -e "s|__APP_UID__|${APP_UID}|g" \
    deploy/jukeplayer.service | sudo tee /etc/systemd/system/jukeplayer.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable jukeplayer.service

echo
echo "==> Setup complete."
if [ "${ENV_EDITED}" = "0" ]; then
    echo "Next:"
    echo "  1. nano ${APP_DIR}/.env      (set SUBSONIC_PASS etc.)"
    echo "  2. sudo systemctl start jukeplayer"
else
    echo "Start it with:  sudo systemctl start jukeplayer"
fi
echo "Logs: journalctl -u jukeplayer -f   |   syslog: ${LOG_SERVER_HOST:-<from .env>}"