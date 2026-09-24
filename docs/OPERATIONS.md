# Jukeplayer Backend — Operations Guide

Deployment, configuration and maintenance for the dedicated-RPi setup.
(Docker/Portainer remains possible — the GHCR image still builds from `main` —
but the dedicated RPi is the primary deployment.)

---

## 1. First-time setup on the RPi (Phase 0)

Target: Raspberry Pi 3 B 1.2 (works on any Pi), Raspberry Pi OS **Lite 64-bit**
(Bookworm/Trixie).

1. **Flash the SD card** with Raspberry Pi OS Lite (64-bit) via Raspberry Pi
   Imager — set hostname (e.g. `jukeplayer-rpi`), enable SSH, set user/password
   and Wi-Fi (if not wired) in the Imager's OS customisation.
2. **Get the code** — ssh in, then:
   ```bash
   git clone -b feature/config-management https://github.com/kaninfod/jukeplayer_backend.git ~/jukeplayer_backend
   cd ~/jukeplayer_backend
   ```
   (Switch to `main` once the config work merges.)
3. **Run the setup script** — installs packages (PulseAudio audio stack, BT
   tools), unblocks rfkill, configures headless BlueZ, installs the venv +
   systemd unit, enables linger, and disables the pipewire user services:
   ```bash
   bash scripts/setup_rpi.sh
   ```
4. **Fill in the environment** — the script creates `.env` from
   `deploy/env.rpi.example` (boot keys only: syslog, docs toggle, file paths).
   Runtime configuration (Subsonic, speakers) lives in the config store and is
   managed from the web UI.
5. **Start**:
   ```bash
   sudo systemctl start jukeplayer
   journalctl -u jukeplayer -f
   ```
6. **Configure from the web UI** — open `http://<jukeplayer-rpi>:8000/kiosk/config`:
   - **Music source (Subsonic)**: set URL/user + the password (masked field),
     save, then restart the service.
   - **Bluetooth**: Scan → the speaker in pairing mode → **Pair** (pairs,
     trusts and connects) → **Add as speaker** (writes the pulse sink into
     the speaker's `options.audio_device`).
   - **Speakers**: rename displays, set defaults, remove — all applies live.
7. **Point clients/speakers at the new host**: set the backend host/port in the
   ESP32 client config and the web client to `http://<jukeplayer-rpi>:8000`.

## Updating

```bash
bash scripts/upgrade_rpi.sh   # git pull + pip sync + service restart
```
`data/` (config, covers) and `logs/` are never touched by upgrades.

## Backups

Everything stateful lives in two places — copy both periodically:
- `data/` — configuration (from Phase A: `data/config.json`) + album covers
- (nothing else persists; playlists/state are rebuilt at runtime)

## Bluetooth / audio (PulseAudio stack)

The service runs as a normal user with linger, and the user-session audio
server is **PulseAudio** (`pulseaudio` + `pulseaudio-module-bluetooth`, kept
alive by linger): **mpv → pulse → bluez A2DP sink**.

> Do NOT re-enable the pipewire user services (`pipewire`, `pipewire-pulse`,
> `wireplumber`). Their bluez monitor never registers A2DP endpoints on this
> Pi 3 / bluez 5.82 stack — connects fail with `br-connection-profile-unavailable`
> / "Protocol not available" (open upstream bug family, see ledger "Phase C
> pre-work"). PulseAudio is the endpoint provider; that is a load-bearing
> decision.

**Normal flow (web UI)**: `/kiosk/config` → Bluetooth card → Scan → Pair →
Add as speaker. Everything below is the manual equivalent (and what the card
does under the hood):

```bash
bluetoothctl
  scan on           # put the speaker in pairing mode; wait for [NEW] Device ...
  pair <MAC>        # JustWorks devices pair silently
  trust <MAC>       # auto-reconnect later
  connect <MAC>
  info <MAC>        # Paired/Trusted/Connected: yes
```

Verification after connecting:

```bash
pactl list sinks short
# → bluez_sink.<MAC_underscores>.a2dp_sink
mpv --audio-device=help 2>&1 | grep -i bluez
# → 'pulse/bluez_sink.<MAC_underscores>.a2dp_sink' (device name)
```

The web UI stores that mpv device id in the speaker's `options.audio_device`;
the backend service reaches the user's PulseAudio via `XDG_RUNTIME_DIR`
(already set in `deploy/jukeplayer.service`). Paired speakers auto-connect at
service start (background reconnect). Known neighbours/TVs may appear in scan
results — that is expected; they show a Pair button until paired.

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

- **BT connect fails with `br-connection-profile-unavailable` / "Protocol not
  available"**: no A2DP endpoints are registered — check the audio server is
  PulseAudio and running (`systemctl --user status pulseaudio`) and that
  pipewire services are disabled (`systemctl --user list-units | grep pipe`).
  Endpoints appear as `Endpoint registered: … A2DPSink` in
  `sudo journalctl -u bluetooth`.
- **Adapter won't power on / scan says `NotReady`**: rfkill soft-block —
  `sudo rfkill unblock bluetooth` (the setup script does this; fresh images
  have shipped blocked).
- **BT device paired but not connected**: `bluetoothctl info <MAC>` —
  Paired/Trusted/Connected must all be yes; the web card shows per-state
  buttons. If A2DP still refuses, remove + re-pair (device-side profile state
  can go stale).
- **No audio on BT**: `bluetoothctl info <MAC>` (paired+connected+trusted),
  `pactl list sinks short` (should list a `bluez_sink...` device while the BT
  speaker is connected), and the speaker's `options.audio_device` in the
  config store must match the mpv device id (`pulse/<sink name>`).
- **Casts not found**: mDNS needs the same subnet — check `avahi`/network.
- **Service starts but API dead**: `.env` problems — `validate_config` logs a
  clear error; fix the env and `sudo systemctl restart jukeplayer`.

## Roadmap (config & speaker management)

- Phase A: configuration UI (JSON store, effective-config view) — ✅ shipped
- Phase B: live speaker management with Chromecast discovery + display names — ✅ shipped
- Phase C: BT/audio card (pair/connect from the web UI) — ✅ shipped
- Phase D: docs completion, final env trim — *remaining*