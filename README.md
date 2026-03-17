# Jukeplayer Backend

Central music playback server for the Jukeplayer ecosystem.

## Features

- FastAPI REST API for music control
- WebSocket real-time updates for all clients
- Integration with Subsonic/Gonic music servers
- Support for multiple playback backends (MPV, Chromecast)
- Database management for albums and playlists

## Setup

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env

# Edit .env with your configuration
# - Set SUBSONIC_URL and credentials
# - Configure playback backend
```

## Running

```bash
python run.py
```

The server will start on `http://localhost:8000`

API documentation: `http://localhost:8000/docs`

## Architecture

- **Routes** (`app/routes/`): HTTP endpoints for control
- **Services** (`app/services/`): Business logic
- **Core** (`app/core/`): Event bus, configuration
- **Database** (`app/database/`): Album and track data
- **WebSocket** (`app/websocket/`): Real-time updates

## API Endpoints

- `POST /api/mediaplayer/next_track` - Play next track
- `POST /api/mediaplayer/previous_track` - Play previous track
- `POST /api/mediaplayer/play_pause` - Toggle play/pause
- `POST /api/display/brightness` - Set display brightness
- `WebSocket /ws/mediaplayer` - Real-time updates

## Clients

This backend serves multiple clients:
- Raspberry Pi hardware client (buttons, display)
- ESP32 hardware client
- Web browser client
- Home Assistant integration
