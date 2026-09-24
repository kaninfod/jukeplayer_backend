# Jukeplayer Backend

Central music playback server for the Jukeplayer ecosystem.

## Features

- FastAPI REST API for music control
- WebSocket real-time updates for all clients (web, ESP32, Home Assistant)
- Integration with Subsonic/Gonic music servers
- Multi-room playback via per-speaker players (Chromecast, MPV/Bluetooth)
- Self-describing RFID/NFC cards (album id written on the card, no backend database)
- Centralized syslog shipping (RFC3164, real PRI severity) + rotated local file log

## Setup

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp ../.env_dev.example .env_dev   # or create .env — see the example for every option

# Edit the env file with your configuration:
# - SUBSONIC_URL / SUBSONIC_USER / SUBSONIC_PASS
# - PLAYBACK_DEVICES (e.g. living_room=chromecast,kitchen=chromecast,boom3=mpv)
# - LOG_SERVER_HOST/PORT (syslog) and LOG_LEVEL
```

## Running

```bash
# Local / test (from this directory)
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env_dev

# or
python run.py
```

The server starts on `http://localhost:8000`.

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