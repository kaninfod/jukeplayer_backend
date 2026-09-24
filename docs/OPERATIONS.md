# Jukeplayer Backend — Operations Guide

Deployment, configuration and maintenance for the dedicated-RPi setup.
(Docker/Portainer remains possible — the GHCR image still builds from `main` —
but the dedicated RPi is the primary deployment.)

---

## 1. First-time setup on the RPi (Phase 0)

Target: Raspberry Pi 3 B 1.2 (works on any Pi), Raspberry Pi OS **Lite (Bookworm, 64-bit)**.

1. **Flash the SD card** with Raspberry Pi OS Lite (64-bit) via Raspberry Pi
   Imager — set hostname (e.g. `jukeplayer-rpi`), enable SSH, set user/password
   and Wi-Fi (if not wired) in the Imager's OS customisation.
2. **Get the code** — ssh in, then:
   ```bash
   git clone -b feature/config-management https://github.com/kaninfod/jukeplayer_backend.git ~/jukeplayer_backend
   cd ~/jukeplayer_backend
   ```
   (Switch to `main` once the config work merges.)
3. **Run the setup script** (installs packages, venv, systemd unit, enables
   user-session audio + bluetooth, enables linger for the user services):
   ```bash
   bash scripts/setup_rpi.sh
   ```
4. **Fill in the environment** — the script creates `.env` from
   `deploy/env.rpi.example`. Set `SUBSONIC_USER` / `SUBSONIC_PASS` (and adjust
   speakers if needed). Until the config UI ships, this file carries the full
   configuration.
5. **Start**:
   ```bash
   sudo systemctl start jukeplayer
   journalctl -u jukeplayer -f
   ```
6. **Point clients/speakers at the new host**: set the backend host/port in the
   ESP32 client config and the testbench web client to
   `http://<jukeplayer-rpi>:8000`.

## Updating

```bash
bash scripts/upgrade_rpi.sh   # git pull + pip sync + service restart
```
`data/` (config, covers) and `logs/` are never touched by upgrades.

## Backups

Everything stateful lives in two places — copy both periodically:
- `data/` — configuration (from Phase A: `data/config.json`) + album covers
- (nothing else persists; playlists/state are rebuilt at runtime)

## Bluetooth / audio

The service runs as a normal user with its own PipeWire session
(`loginctl enable-linger` keeps it alive at boot): **mpv → pipewire →
bluetooth**. Pairing today (until the UI audio card ships):

```bash
bluetoothctl
  scan on           # wait for the device address
  pair <MAC>
  trust <MAC>       # auto-reconnect later
  connect <MAC>
```

The BT speaker then becomes the default sink; MPV output follows it.

## Logs

- journald: `journalctl -u jukeplayer -f`
- syslog: shipped to `LOG_SERVER_HOST` (facility local0, tag `jukeplayer_backend`)
- rotated file: `logs/jukebox.log` (10MB × 5)

## Service management

```bash
sudo systemctl status|start|stop|restart jukeplayer
sudo systemctl enable jukeplayer          # start at boot (setup script does this)
```

## Troubleshooting

- **No audio on BT**: check `systemctl --user status wireplumber`, `bluetoothctl
  info <MAC>` (paired+connected+trusted), `pactl get-default-sink` (should name
  a `bluez_sink...` device while the BT speaker is connected).
- **Casts not found**: mDNS needs the same subnet — check `avahi`/network.
- **Service starts but API dead**: `.env` problems — `validate_config` logs a
  clear error; fix the env and `sudo systemctl restart jukeplayer`.

## Roadmap (config & speaker management)

- Phase A: configuration UI (JSON store, effective-config view) — *in progress*
- Phase B: live speaker management with Chromecast discovery
- Phase C: BT/audio card (pair/connect from the web UI)
- Phase D: docs completion, final env trim