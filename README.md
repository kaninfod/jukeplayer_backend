# Jukeplayer Backend

Central music playback server for the Jukeplayer ecosystem.

## Features

- FastAPI REST API for music control
- WebSocket real-time updates for all clients (web, ESP32, Home Assistant)
- Integration with Subsonic/Gonic music servers
- Multi-room playback via per-speaker players (Chromecast, MPV/Bluetooth)
- Speaker management from the web UI: live add/remove/rename, Chromecast
  discovery, Bluetooth pairing (pair + trust + connect in one step)
- Self-describing RFID/NFC cards (album id written on the card, no backend database)
- Centralized syslog shipping (RFC3164, real PRI severity) + rotated local file log

## Setup

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

The environment carries **bootstrap keys only** (see `deploy/env.rpi.example`
for the canonical list — syslog host/port, `LOG_LEVEL`, file paths, docs
toggle). All user configuration — Subsonic, speakers, MPV — lives in the JSON
config store (`data/config.json`) and is edited from the web UI.

## Running

```bash
# Local / test (from this directory)
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env_dev

# or
python run.py
```

The server starts on `http://localhost:8000`. On first run, open
`/kiosk/config` to set the music source and add speakers.

API documentation is only exposed when `ENABLE_DOCS=true` (or `DEBUG_MODE=true`):
`http://localhost:8000/docs`

## Architecture

- **Routes** (`app/routes/`): HTTP endpoints for control
- **Services** (`app/services/`): business logic — playback, speaker broker, clients, Subsonic
- **Playback backends** (`app/playback_backends/`): Chromecast, MPV (local/Bluetooth)
- **Core** (`app/core/`): event bus, config, logging
- **WebSocket** (`app/websocket/`): real-time status + control channel
- **Web UI** (`app/web/`): kiosk web client (part of the backend)

## How playback works

1. Clients (web, ESP32, Home Assistant) send commands over HTTP or WebSocket.
2. The **SpeakerBrokerService** routes each command to the right speaker's player
   (by `client_id`, by `device_name`, or to the default speaker).
3. Players use a playback backend (Chromecast/MPV) and broadcast state changes
   back to all clients on that speaker.

## Speaker management (web UI)

Three surfaces, one job each:

- **`/kiosk/config` — setup**: music source + the speaker list (rename,
  default, remove; removing a BT speaker also forgets the pairing).
- **`/kiosk/system` → Connect Speaker card**: add speakers — Chromecast
  scan/add, Bluetooth pairing (pair + trust + connect + add automatically),
  manual (advanced) form.
- **`/kiosk/devices` — runtime**: connect/disconnect BT speakers, state and
  battery pills, tap a card to switch playback.

A 30s watchdog keeps the runtime flags (available/connected/battery) fresh and
reconnects dropped BT speakers.

## API endpoints (main)

- `POST /api/mediaplayer/play_pause|next_track|previous_track|stop` — transport control
- `POST /api/mediaplayer/play_album_from_albumid/{album_id}` — play an album
- `POST /api/mediaplayer/volume_set?volume=0-100`, `/volume_up`, `/volume_down`, `/volume_mute`
- `GET /api/mediaplayer/status` — full playback context of the default speaker
- `GET /api/output/speakers`, `/api/output/control_clients` — speakers/clients introspection
- `GET /api/subsonic/...` — artists/albums/covers (proxy)
- `WS /ws/mediaplayer/events` — bidirectional control + status updates

## Clients

- **Web browser client** (served by this backend at `/`)
- **ESP32 hardware client** (`../jukeplayer_esp32`)
- **Home Assistant integration** (`../jukeplayer_ha`)

## Logs

- Syslog to `LOG_SERVER_HOST` (facility local0, tag `jukeplayer_backend`, real PRI severity)
- Local rotating file: `logs/jukebox.log` (10MB × 5, `LOG_FILE` to override)
- Level from `LOG_LEVEL` (default INFO)