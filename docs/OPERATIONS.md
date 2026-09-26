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
   git clone https://github.com/kaninfod/jukeplayer_backend.git ~/jukeplayer_backend
   cd ~/jukeplayer_backend
   ```
   (The config & speaker management work is merged to `main`.)
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
6. **Configure from the web UI** — three surfaces, each with one job:
   - **`/kiosk/config` — setup**: music source (Subsonic URL/user + masked
     password) and the speaker list — rename displays, set default, remove
     (for BT speakers remove also forgets the pairing). No connect buttons
     here: pairing is setup-adjacent and lives on the System page.
   - **`/kiosk/system` → "Connect Speaker" card**: add speakers. Chromecast:
     Scan → Add (stores the device's cast UUID for robust matching).
     Bluetooth: put the speaker in pairing mode → Scan → **Pair** (pairs,
     trusts, connects and adds it as a speaker automatically, writing the
     pulse sink into `options.audio_device`). A manual (advanced) form hides
     behind the details toggle.
   - **`/kiosk/devices` — runtime**: per-speaker cards with connect/disconnect
     for BT speakers, BT state/battery pills, and tap-to-select for playback.
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

**Normal flow (web UI)**: System menu → **Connect Speaker** → Bluetooth
section → Scan → **Pair** (pair + trust + connect + add as speaker in one
step). The device card on `/kiosk/devices` then shows the state pill,
battery (when clearly reported) and a connect/disconnect button. Everything
below is the manual equivalent (and what the card does under the hood):

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
service start (background reconnect), and a 30s state watchdog refreshes
type/available/connected/battery for every speaker and reconnects BT speakers
whose link dropped mid-session (per-MAC backoff 30s → 300s — after a
reconnect, playback may still need one play/pause tap). Known neighbours/TVs
may appear in scan results — that is expected; they show a Pair button until
paired, and devices already managed as speakers are hidden from the pair list
behind a names note.

## Environment (bootstrap keys)

The config store owns all user configuration; the environment carries only
what the app needs before the store can be read. Canonical template:
`deploy/env.rpi.example` (the live file is `<app dir>/.env`, loaded by the
systemd unit).

| Key | Default | Purpose |
|---|---|---|
| `LOG_SERVER_HOST` | `localhost` | syslog host (empty/localhost disables shipping) |
| `LOG_SERVER_PORT` | `514` | syslog port |
| `LOG_LEVEL` | `INFO` | boot log level; the config UI can change it live |
| `CONFIG_FILE` | `data/config.json` | config store path |
| `LOG_FILE` | `logs/jukebox.log` | rotated app log |
| `STATIC_FILE_PATH` | `static_files` | album covers/assets |
| `ENABLE_DOCS` | `false` | expose `/docs` (also enabled by `DEBUG_MODE=true`) |
| `DEBUG_MODE` | `false` | debug tracing toggle |
| `DOCS_URL` / `OPENAPI_URL` | `/docs`, `/openapi.json` | doc endpoint paths |

| `ENABLE_DOCS` | `false` | expose `/docs` (also enabled by `DEBUG_MODE=true`) |
| `DEBUG_MODE` | `false` | debug tracing toggle |
| `DOCS_URL` / `OPENAPI_URL` | `/docs`, `/openapi.json` | doc endpoint paths |
| `HTTP_PORT` | `8000` | web port the systemd unit binds (`--port ${HTTP_PORT}`). Set `80` to omit the port from URLs — the unit grants `CAP_NET_BIND_SERVICE` so an unprivileged user can bind it. |

**Changing the HTTP port**: set `HTTP_PORT` in `.env`, then
`sudo systemctl daemon-reload && sudo systemctl restart jukeplayer`.
Units installed before this key existed need it added once — re-run
`bash scripts/setup_rpi.sh`, or edit `/etc/systemd/system/jukeplayer.service`
(`Environment=HTTP_PORT=…` + `--port ${HTTP_PORT}` + the `AmbientCapabilities`
line) and `daemon-reload`.

**Existing installs (pre-Phase D)**: if your `.env` still carries the old
Subsonic/speaker/MPV keys, delete them — those values moved into the config
store at the Phase A cutover and the app no longer reads them from the env.
Trim to the bootstrap set above, then `sudo systemctl restart jukeplayer`.

## Bluetooth adapter — BT500 dongle swap (hardware follow-up)

The Pi 3's onboard BT/Wi-Fi chip (BCM43430, UART) dropped A2DP links
repeatedly under streaming (`hci0: link tx timeout` / `killing stalled
connection` in dmesg — only a reboot recovers it). The ASUS USB-BT500
(Realtek RTL8761B) is the replacement; `firmware-realtek` is already in
`scripts/setup_rpi.sh`.

1. Plug the dongle in, then verify: `lsusb` (should list the Realtek device)
   and `dmesg | tail` for the hci registration.
2. Test single + dual streaming through it (`/kiosk/devices`, two speakers).
3. If stable, power off the onboard radio: the onboard BT hangs off the UART,
   so `sudo systemctl mask hciuart && sudo reboot` disables it permanently;
   `sudo rfkill block bluetooth` is the softer variant (radio off, adapter
   still enumerated). Confirm which hci is active with `hciconfig -a`.
4. `firmware-realtek` must be present: `sudo apt install firmware-realtek`.

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
- **BT audio drops mid-stream, dmesg shows `hci0: link tx timeout` /
  `killing stalled connection`**: the onboard controller wedged — the app
  never sees it (no error surfaces) and the watchdog cannot reconnect to a
  dead controller; only a reboot recovers it. Mitigations: PulseAudio stack
  (done), Wi-Fi power-save off, and the BT500 dongle swap (section above).
- **Playback to a Chromecast group fails with "Device 'X' not found on
  network"**: pre-Phase D entries matched the device name exactly and group
  names differ in case ("Home group" vs "Home Group"). Since Phase D the
  match is case/whitespace-insensitive and UUID-first (UUID stored at add
  time) — re-adding the group from the Connect Speaker card is the most
  robust path.
- **Casts not found**: mDNS needs the same subnet — check `avahi`/network.
- **Service starts but API dead**: `.env` problems — `validate_config` logs a
  clear error; fix the env and `sudo systemctl restart jukeplayer`.

## Roadmap (config & speaker management)

- Phase A: configuration UI (JSON store, effective-config view) — ✅ shipped
- Phase B: live speaker management with Chromecast discovery + display names — ✅ shipped
- Phase C: BT/audio card (pair/connect from the web UI) — ✅ shipped
- Phase D: docs completion + final env trim + cast-group match fix — ✅ shipped
  (branch `feature/config-management` is merge-ready; hardware follow-ups
  continue on the ledger)