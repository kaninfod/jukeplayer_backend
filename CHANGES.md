# Jukeplayer Backend — Refactor Ledger

Working log of the backend cleanup (started 2026-09-24). Batches are deployed
and verified one at a time; new findings discovered along the way are appended
to "New findings (running list)" at the bottom.

## Config & speaker management (feature branch `feature/config-management`)

| Phase | Scope | Status |
|---|---|---|
| 0 | Dedicated RPi deployment (scripts, systemd, ops guide) | ✅ committed — RPi setup in progress by user |
| A | JSON config store + effective-config view + /kiosk/system card | ✅ committed (dcafd79), 57/57 tests |
| B | Live speaker manager (CC discovery picker, add/remove) | ✅ verified on RPi 2026-09-24 — scan, add (tv_lounge), store persistence, live apply; 74/74 tests |
| C | Audio/BT card (pair/connect from the web UI) | ✅ Code done, 96/96 tests — pending test-env run |
| D | Docs + final env trim | ⬜ |
| — | USB-DAC output (MPV audio_device per speaker) | 🔒 backburner — schema slot reserved in Phase B |

Design decisions (user-confirmed): JSON store · everything UI-managed incl.
secrets (masked fields, 0600 file) · no env fallback (store authoritative,
clean cutover) · speakers live-managed · no auth (LAN-only) · dedicated RPi
as phase 0.

## Batch status

| # | Scope | Status |
|---|---|---|
| 1 | Logging & noise | ✅ Code done, tested locally — pending test-env run |
| 2 | Dead/broken endpoints & dead code removal | ✅ Code done — verified in test env |
| 3 | Broker routing hole + broken handlers | ✅ Code done, 28/28 tests — pending test-env run |
| 3.5 | Kill album.db + NOTIFICATION legacy | ✅ Code done, 28/28 tests — pending test-env run |
| 4 | Chromecast stop hardening + fallback policy | ✅ Code done, 32/32 tests — pending test-env run |
| 5 | Subsonic retry + async hygiene + scrobble fix | ✅ Code done, 36/36 tests — pending test-env run |
| 6 | Event bus thread-safety + volume payload + startup-sync deferral | ✅ Code done, 39/39 tests — pending test-env run |
| 6b | Volume sync restoration + device-side volume propagation | ✅ Code done, 46/46 tests — pending test-env run |
| 6c | Web UI: guarded renderState (volume updates lost on missing targets) | ✅ Code done — pending test-env run |
| 6d | Web UI: volume_changed dict payload normalized (0% display bug) | ✅ Code done — pending test-env run |
| 7 | Module name collision resolved (media_player_service package) | ✅ Code done, 46/46 tests — pending test-env run |
| 8 | Config/ops hygiene + docs | ✅ Code done, 46/46 tests — pending test-env run |

---

## Batch 1 — Logging & noise

- `app/main.py`: log level now from `LOG_LEVEL` env (default INFO); was hardcoded DEBUG.
- `app/core/logging_config.py`: file log → `logs/jukebox.log` via `RotatingFileHandler` (10MB × 5); honors `LOG_FILE`; silenced `asyncio` logger.
- `app/websocket/mediaplayer_ws.py`: `WebSocketDisconnect` caught explicitly → DEBUG (was ~70% of all ERROR volume: `(1005, None)` etc.).
- `app/core/event_bus.py`: logger name `core.event_bus` → `app.core.event_bus`.
- `run.py`: removed duplicate `setup_logging` (second call wiped handlers) and permanent debug level.
- `.dockerignore`: added `*.log`, `tmp_mpv.log`, `venv/`, `.env_dev*`.
- `docker-compose.yml`: logs mount corrected `/app/logs` → `/jukeplayer_backend/logs` (matched Dockerfile WORKDIR, so rotation now persists on the Pi).

## Batch 2 — Dead/broken endpoints & dead-code removal

- `app/services/speakers_service.py`: added `get_default_speaker()` (resolves `DEFAULT_CHROMECAST_DEVICE` → lowercase key, falls back to first speaker); fixed `Speaker.to_dict()` UnboundLocalError when `mediaplayer` is None; removed dead commented block.
- `app/routes/output.py`: `/status` + `/switch` no longer call the non-existent `media_player_service` (verified live 500) — resolved via default speaker; `/speakers` + `/control_clients` guarded against vanished clients/speakers; removed bogus `from urllib import request`.
- `app/routes/system.py`: removed `/api/system/clients*` (depended on removed `client_registry` → live 500); kept `/ping` (Docker healthcheck).
- `app/routes/mediaplayer.py`: `/status` now returns the real playback context of the default speaker (consumed by HA's polling fallback, which previously got `payload: null`); deleted `/stream/current` (unreachable since player-registry removal); deleted ~400 lines of commented-out code; `/toggle_repeat_album` now returns a real bool, not `[True]`; removed dead `_get_data_for_current_track` helpers.
- `app/routes/chromecast.py`: deleted (router was never included in `main.py`).
- `app/web/routes.py`: deleted dead `_get_output_status_data`; `/kiosk/playlist` and `/kiosk/nfc-client-select` no longer crash on missing speaker/clients.
- `app/services/media_player_service.py`: removed bogus `from email import message`.
- `app/services/subsonic_service.py`: removed ~65-line commented `get_cover_4bit` block.
- `app/main.py`: removed commented chromecast import.

## Batch 3 — Broker routing hole + broken handlers

- `app/services/speaker_broker_service.py`: `_execute_media_action` no longer crashes on events without routing context (`UnboundLocalError` on `speaker`). Routing is now centralized in a new **`resolve_speaker(client_id, device_name)`** method (client's speaker → named device → default speaker → `None` with a log line), used by both the broker and `load_rfid`. Deleted dead `handle_play_album_from_rfid` (never subscribed, called the old broken `load_rfid` signature). Added `TRACK_CHANGED` subscription → broadcasts fresh context to the speaker's clients.
- `app/services/playback_service.py`: `load_rfid` rewritten to the event-bus signature (`load_rfid(event)`) — the old version referenced an undefined `event` variable and the removed `client_registry` service, so any RFID_READ event would crash. Player resolution delegated to `broker.resolve_speaker()`; album-id lookup collapsed to `album_id = album_id or self.album_db.get_album_id_by_rfid(rfid)`. `load_from_album_id` guards `player=None` before logging.
- `app/services/media_player_service.py`: added missing `emit_update()` (was called twice in the backend-switch path → AttributeError) — emits `TRACK_CHANGED` so clients get fresh context after a switch; fixed the `switch_playback_backend_fac(self, self, ...)` double-`self` call.
- `app/playback_backends/factory.py`: dropped the module-level `self` first parameter.
- `app/services/control_clients_service.py`: `register()` no longer swallows exceptions (returned implicit `None`, which crashed the WS register response); `Dict[str, any]` → `Dict[str, Any]`.
- `app/services/media_player_service/DELETE_media_player_service.py`: **deleted** (357-line dead duplicate; removal pulled forward from Batch 7 after it was dropped from the working tree). `tests/conftest.py`, `tests/core/test_event_bus.py`, `tests/services/test_media_player_service.py` repointed to the live `app.services.MediaPlayerService`; `test_volume_up` updated to the live dict return shape (`{"message": ..., "volume": ...}`).
- `app/services/playback_service.py`: removed `_encode_card` + its `ENCODE_CARD` subscription (nothing anywhere emits `ENCODE_CARD` — dead since the backend-display era, per user) and the `show_screen_queued` emission it contained. `app/core/event_factory.py`: removed `EventFactory.show_screen_queued` + the `SHOW_SCREEN_QUEUED`/`ENCODE_CARD` enum values.
- **Tests added:** `tests/services/test_speaker_broker_default_fallback.py` (5 tests incl. `resolve_speaker` priority matrix) and `tests/services/test_load_rfid.py` (4 tests). Suite: 28 passing.

## Batch 3.5 — Killed album.db + removed NOTIFICATION legacy (user decision)

Scope decided live with the user: the rfid→album SQLite database is legacy from
the unstable-RFID era; cards are self-describing (client reads album_id from
block 4 and sends it), and production logs showed **zero RFID-scans in 7 days**
(the only play path is `play_album`, 46×/week, which carries the album_id).

- **Deleted `app/database/` entirely** (`album_db.py`, `album_schema.py`, `album.py`, `album.db`, `__init__.py`) — all SQLAlchemy/SQLite code gone.
- `app/core/service_container.py`: removed `create_album_database` + registration; `create_playback_service` updated to the new `PlaybackService(subsonic_service, event_bus)` signature.
- `app/services/playback_service.py`: ctor lost the dead `player` + `album_db` params; `load_rfid` now requires the card's album_id in the event payload (rfid-only scans of unencoded cards log-and-drop — matches the Pi's flow where cards carry their album); `load_from_album_id(player=None)` now falls back to the default speaker (also makes `/kiosk/library/play/{album_id}` work — it was guaranteed-400 before). Removed the never-delivered `EventFactory.notification` emits.
- `app/core/event_factory.py`: removed `EventFactory` + `NOTIFICATION`, plus all other zero-usage enum values (`CLEAR_ERROR`, `BUTTON_PRESSED`, `ROTARY_ENCODER`, `SHOW_*`, `TOGGLE_REPEAT_CHANGED`, `SWITCH_DEVICE`, `BROADCAST_GENERIC_MESSAGE`). `EventType` now only contains live events.
- `app/services/subsonic_service.py`: removed dead `add_or_update_album_entry`, `add_or_update_album_entry_from_album_id`, `_fetch_and_cache_coverart` (116 lines; one referenced the deleted DB module, one called a non-existent method).
- `app/config.py`: removed `get_database_url()`, plus unused `get_icon_path`/`get_image_path` (verified zero usage — display-era leftovers).
- `requirements.txt`: dropped `sqlalchemy`. `docker-compose.yml`: removed the (mismatched) database volume mount + `DATABASE_URL` env.
- Tests: `test_load_rfid.py` rewritten for the new contract (card album_id → play via `resolve_speaker`; no album_id → clean ignore; no speaker → clean fail). **Suite: 28 passing.** Container verified: 8 services registered, `album_database` gone.

## Batch 4 — Chromecast stop hardening + fallback policy

- `app/playback_backends/chromecast.py`:
  - `stop()` no longer reconnects before stopping — a missing connection means nothing is playing, so stop returns `True` immediately. Reconnect-before-stop was waiting `CHROMECAST_WAIT_TIMEOUT` (10s) per device (plus fallbacks ≈ 30s) against offline devices and was the direct cause of the "Failed to stop: Execution of stop timed out after 10.0 s" spam (137×/week in prod, confirmed in test env 2026-09-24 09:04).
  - A stop that doesn't confirm (device already idle/off) is now logged at **INFO** ("did not confirm — device may already be idle") instead of ERROR.
  - `connect(fallback=...)` default flipped **True → False**: silent wrong-room playback (e.g. asking for the offline Kitchen and getting Bedroom music) no longer happens by accident; `ensure_connected` reconnects target only. Fallback stays available for explicit callers (UI-driven).
- **Tests added:** `tests/playback_backends/test_chromecast_stop.py` (4 tests: stop-without-connection succeeds without reconnect, benign timeout, no-fallback device list, explicit fallback list). Suite: **32 passing**.

## Batch 5 — Subsonic retry + async hygiene + scrobble fix

- `app/services/subsonic_service.py`:
  - `_api_request` retries transient failures (connection reset / `RemoteDisconnected` / read timeout) once after a 0.5s backoff; HTTP errors are **not** retried. Directly targets the 26×/week `RemoteDisconnected`/timeout errors.
  - `scrobble_now_playing` now sends `submission=false` — a true "now playing" notice per the Subsonic API and the method's own docstring. Previously every track start was scrobbled to Last.fm as fully played.
- `app/services/media_player_service.py`: `_scrobble_track_now_playing` no longer blocks the event loop — the HTTP call runs in the default executor, fire-and-forget, with all error handling inside the worker.
- `app/services/playback_service.py`: `load_from_album_id` offloads `get_album_info` + `ensure_cover_variants` to a thread (`asyncio.to_thread`). Album loading no longer stalls the event loop / WS clients — the likely driver of the 1005-disconnect churn (481 reg/week).
- `app/web/routes.py`: kiosk library endpoints (`list_artists`, `list_albums_for_artist`) offloaded to a thread — they were blocking calls inside `async def` handlers.
- Design note: stayed with `requests` + `asyncio.to_thread` at call sites instead of a full httpx.AsyncClient migration — smaller, lower-risk diff; sync `def` routes (threadpool) keep working unchanged. Full httpx conversion can be a later cleanup if wanted.
- **Tests added:** `tests/services/test_subsonic_retry.py` (4 tests: transient retry, retry exhaustion, HTTP-error-no-retry, scrobble=now-playing). Suite: **36 passing**.

## Batch 6 — Event bus thread-safety + volume payload + startup-sync deferral

- `app/core/event_bus.py`: `EventBus.set_main_loop(loop)` captures the app's main loop at startup (`main.py` startup event). `emit()` from a **foreign thread** (pychromecast/MPV callback threads) now schedules async handlers via `loop.call_soon_threadsafe(...)` on the main loop. The per-event `asyncio.run()` fallback — which created a fresh event loop per event and raced loop-bound primitives (locks, `asyncio.Event`, websocket sends) — is gone. Without a captured loop, async handlers are dropped with an error log; emit never raises.
- `app/services/speaker_broker_service.py`: `broadcast_volume_to_clients` now sends `{"volume": n, "muted": bool}` (was a bare int). ESP32's `handle_volume_changed` already accepts the dict shape and now also receives mute state; HA updates volume from full-context messages and is unaffected. Iteration made list()-safe.
- `app/services/media_player_service.py`: removed the dead `VOLUME_CHANGED` event emit from `_set_volume` (zero subscribers since the old display architecture — it went nowhere; real client-visible delivery is the broker broadcast). `VOLUME_CHANGED` enum value removed.
- `app/services/media_player_service/volume_manager.py`: removed the eager `sync_volume_from_backend()` task from `__init__` — constructing a player no longer connects every device at startup (slow boot + connection-storm logs). Volume converges on first interaction or backend switch.
- **Tests added/updated:** cross-thread emit on main loop, emit-without-loop safety, volume dict payload + muted. Suite: **39 passing**.

## Batch 6b — Volume sync restored (properly) + device-side volume propagation

Follow-up to Batch 6: removing the eager startup sync left clients showing the
50% default until the first interaction, and device-side volume changes
(Google Home app, hardware buttons) were never propagated — the cast status
listener logged volume but told nobody.

- `app/playback_backends/chromecast.py`: `ChromecastMediaStatusListener` now tracks `volume_level`/`volume_muted` and emits `VOLUME_CHANGED {device_name, volume (0-100), muted}` whenever the device reports a change — covers Google Home app changes, hardware buttons, and the initial status pushed on connect. Removed the stray `print()` in `new_cast_status`; removed a leftover duplicate `new_cast_status` definition that had been shadowing the new implementation.
- `app/core/event_factory.py`: re-added `VOLUME_CHANGED` (now actually delivered).
- `app/services/speaker_broker_service.py`: new `handle_volume_changed` subscription — updates the speaker's VolumeManager via `set_local_volume()` and broadcasts to its clients. **Read-back only, never written to the device.**
- `app/services/media_player_service/volume_manager.py`: new `set_local_volume(volume, muted)` (clamped); `sync_volume_from_backend()` rewritten **read-only** — the old version wrote the pulled value straight back to the device (a read→write loop).
- `app/main.py`: startup schedules a background `sync_all_speaker_volumes()` task — connects each configured device off the startup path and pulls its real volume; each connect also triggers the cast-status listener, so clients get the true volume shortly after boot without delaying startup.
- Behavior after this batch: restart → background sync pulls real device volumes → clients display them; volume changed on the device/GH app while connected → clients update live; first client volume adjustment adjusts from the REAL volume (no more jump to 50→53).
- **Tests added:** `tests/playback_backends/test_volume_sync.py` (6 tests: cast-status emission, dedupe, mute toggle, read-only sync, None handling, clamping) + broker handling test. Suite: **46 passing**.

## Batch 6c — Web UI fix: guarded `renderState` (volume updates lost)

User report 2026-09-24: device/GH-app volume changes reached ESP32 but not the
web UI — browser console showed `Missing target element "trackinfo" for
"nowplaying" controller` from `now_playing_controller.js renderState()`.

- `app/web/static/js/controllers/now_playing_controller.js`: `renderState()` accessed four targets (`trackinfo`, `cover`, `notrackinfo`, `nocover`) without `has…Target` guards — unlike the rest of the file. When the controller was connected before those elements existed (or on pages without them), `renderState()` threw, and `update()` aborted **before** `updateVolume()`/`updateMuteState()` ran — so all subsequent WS updates were dropped until the page recovered ("then it started getting the events"). All four accesses are now guarded; a scan of the whole file confirms every bare target access is guarded (plural `…Targets` getters are safe by design).
- Note: dead `update_old()` method in the same file (~60 lines) → remove in Batch 8.

## Batch 6d — Web UI fix: `volume_changed` dict payload (0% display bug)

User report 2026-09-24 (follow-up to 6b's wire-format change): changing volume
from the web UI showed **0%** in the UI while the actual volume applied
correctly.

- Root cause: Batch 6b changed the backend's `volume_changed` WS payload from a bare int to `{"volume": n, "muted": bool}`. ESP32's handler accepts both shapes; the web UI did not — `websocket_controller.js` stored the whole dict into `window.appState.volume`, and both consumers (`volume_controller.update()`, `now_playing_controller.updateVolume()`) do `parseInt(...) || 0` → NaN → 0%.
- Fix: `websocket_controller.js` normalizes the payload once at the single entry point — extracts the integer, picks up `muted` into `appState.isMuted`, and broadcasts the plain number downstream. Backward compatible with the old bare-int shape.
- Consumers unchanged (they now receive a real int). ESP32 unaffected (already dual-shape). HA unaffected (reads volume from full context messages).

## Batch 7 — Module name collision resolved

The file `app/services/media_player_service.py` and the package
`app/services/media_player_service/` shared a name, forcing an `importlib` hack
in `services/__init__.py` that loaded the file as `_media_player_service_module`
(6,350 log lines/week under that bogus name).

- `media_player_service.py` → `media_player_service/service.py` (inside the package; logger now `app.services.media_player_service.service`).
- `media_player_service/__init__.py` re-exports `MediaPlayerService`, `PlaylistManager`, `PlaylistItem`, `VolumeManager`.
- `services/__init__.py` is now two plain imports. Zero code changes elsewhere — `from app.services import MediaPlayerService` and `from app.services.media_player_service import X` both keep working.
- Suite: 46 passing; container wiring verified.

## Batch 8 — Config/ops hygiene + docs

- `app/config.py`: rewritten clean. Removed dead keys: `RFID_BLOCKS`, `RFID_*` timeouts, `DISPLAY_*`, `FONT_*` + `get_font_definitions`/`FONT_DEFINITIONS`, `ICON_DEFINITIONS`, `ALLOWED_HOSTS`, `API_KEY`, `WEB_BASIC_AUTH_*`, `ALLOW_LOCAL_API_BYPASS`. Fixed the `_parse_playback_devices.__func__(None)` hack (now a plain module-level function). All removals verified zero-usage.
- `app/core/security.py`: deleted (APIKeyMiddleware was removed from the app long ago; its config keys went with it).
- `requirements.txt`: dropped unused `python-jose`, `passlib`, `python-json-logger`.
- `docker-compose.yml`: removed dead `API_KEY` / `ALLOW_LOCAL_API_BYPASS` / `SUBSONIC_CAST_BASE_URL` env lines; `ENABLE_DOCS` default → `false` (docs no longer exposed in prod by default; set `ENABLE_DOCS=true` to restore).
- `app/routes/subsonic.py`: deprecated `regex=` → `pattern=` in Query params (kills the FastAPI deprecation warnings); also dropped the dead `4bit` cover format option (its backend code was removed in Batch 2).
- Web JS: removed the dead `update_old()` method (~90 lines) from `now_playing_controller.js`.
- `.env_dev` (active test config): removed the 4 dead keys. `.env_dev.example` + `.env.example` trimmed of all dead keys.
- `README.md`: rewritten to match reality — current env vars, run commands, architecture (speaker broker), live endpoints, client list (web/ESP32/HA only), log setup. Removed stale references (`.env.example` path, album database, `/api/display/brightness`, Pi client).
- Suite: 46 passing; app imports clean (47 routes).

## Phase B — Live speaker manager (2026-09-24)

Speakers are now fully UI-managed and apply **live** — no restart for
add/remove/default. The store stays the single source of truth; every change
is persisted there first, then applied to the live registry, then to the
broker. `SECTION_APPLIES["speakers"]` flipped `restart → live`.

- `app/services/config_store.py`: `add_speaker()` (single-default invariant: an
  added default clears the previous), `remove_speaker()` (promotes the first
  remaining speaker when the default is removed), `set_default_speaker()`; all
  normalize names and persist atomically. `effective()` speakers view now
  carries `"applies": "live"`.
- `app/services/speakers_service.py`: construction extracted to
  `_build_speaker()` (shared by boot-time `initialize_speakers` and the new
  live path); new `add_speaker(entry)`, `remove_speaker(name)` (returns the
  removed object), `set_default_name(name)`.
- `app/services/speaker_broker_service.py`: new `handle_speaker_removed()` —
  clients attached to a removed speaker are re-homed to the default speaker
  (or detached when no default remains) and get a fresh context broadcast.
- `app/playback_backends/chromecast.py`: module-level `discover_devices()`
  scan over the persistent global discovery browser (blocking — callers go
  through `asyncio.to_thread`), used by the picker; the connect path is
  untouched.
- **New `app/services/speaker_manager_service.py`** (`speaker_manager`
  singleton): `discover()` (maps friendly names to store format, flags
  already-configured devices), `add_speaker()` (construct live → persist;
  rolls the live side back if the store write fails), `remove_speaker()`
  (stop playback → disconnect backend → drop from registry → persist →
  re-point default → re-home clients), `set_default()`; also owns
  `sync_speaker_volume()` / `sync_all_speaker_volumes()` (moved from
  `main.py`), so a speaker added live gets its real device volume pulled in
  the background.
- `app/routes/config_api.py`: `GET/POST /api/config/speakers`,
  `DELETE /api/config/speakers/{name}`, `PUT /api/config/speakers/{name}/default`,
  `GET /api/config/speakers/discovered` (mDNS scan off the event loop).
- Web UI: new `components/kiosk/config/_speakers_card.html` (replaces the
  Phase A placeholder card) — configured list with make-default/remove
  buttons, "Scan network" → discovered picker with `added` badges, manual add
  (Chromecast or MPV; the `audio_device` option slot for USB-DAC stays
  reserved). Every action htmx-swaps the card fragment
  (`/kiosk/config/speakers/*`); errors render inside the card.
- `app/main.py`: volume sync delegated to the manager; the no-speakers boot
  warning now points at the working UI.
- **Tests added:** `tests/services/test_speaker_manager.py` (14: store
  invariants, live registry, broker re-homing incl. detach-when-empty,
  discovery mapping) + 3 API/htmx tests (add/remove lifecycle incl. 400/404
  paths, discovered endpoint, card fragment flow). **Suite: 74 passing.**
- **Test-isolation bug fixed** (pre-existing from Phase A):
  `Config.CONFIG_FILE` is a class attr resolved at import, so the tests'
  `monkeypatch.setenv("CONFIG_FILE", …)` never reached the store and route
  tests could write the repo's real `data/config.json` (an artifact from
  today's runs was created and removed). All config-api tests now patch
  `app.config.config.CONFIG_FILE` to a tmp path.

Notes: scan results collapse after an add (re-scan to pick more — v1
simplicity); MPV speakers are added manually (no discovery); the
`options.audio_device` schema slot stays reserved for the USB-DAC backburner.

## Phase B.1 — Friendly display names (2026-09-24)

User request on the RPi: `living_room` should display as e.g. "Living Room
Speaker" — a per-speaker, user-configurable label. The technical name stays
the matching key everywhere (store, discovery matching, API paths); only
cosmetic presentation changes.

- Store schema: optional `display_name` on every speaker entry (stripped
  free text; empty = show technical name). New
  `set_speaker_display_name(name, value)`; `add_speaker` accepts it;
  `load()`/`set_speakers` preserve it.
- `Speaker` registry objects carry `display_name` (set at build, updated on
  rename) and expose it via `to_dict()`; the device-selector card shows
  `display_name` (technical name underneath when set);
  `get_available_output_devices()` gained a `display` key (additive for HA).
- `SpeakerManagerService.set_display_name()` updates store + live registry;
  `add_speaker()` takes the label — **scan-added speakers get their friendly
  name (e.g. "TV lounge") as display name automatically**.
- API: `PUT /api/config/speakers/{name}/display`; `POST /api/config/speakers`
  accepts `display_name`.
- Speakers card: display label first, technical name in muted parens when
  set; pencil button edits via htmx `hx-prompt` (empty prompt clears →
  technical name); manual add form has an optional Display name field;
  confirm-dialogs now use the display label.
- **Tests added:** 3 manager tests (persist+register, set/clear incl. live
  attr, unknown rejected) + 2 route tests (API set/clear/404; card shows
  display name + edits via the HX-Prompt header). **Suite: 79 passing.**

## RPi verification — Phase B (2026-09-24, user)

- `scripts/upgrade_rpi.sh` delivered Phase B (earlier password/paste trouble
  was from running things from `~` instead of the repo dir — no harm done).
- Config page shows the speakers card; scan found the real network: the 3
  configured speakers badged "added", plus unconfigured "TV lounge" and cast
  group "Home group".
- Added `tv_lounge` from the picker: card updated live, store persisted
  (`data/config.json` shows the entry with `is_default: false`).

## Phase C pre-work — BT audio feasibility on the RPi (2026-09-24 evening)

User-tested on the Pi 3 before implementation. Findings, decisions:

- **rfkill soft-block on boot**: `hci0` was soft-blocked (fresh Trixie image);
  `sudo rfkill unblock bluetooth` fixed power-on/scan. → `setup_rpi.sh` should
  unblock rfkill.
- **Pairing flow verified**: scan/pair/trust/connect via `bluetoothctl` as the
  pi user, no sudo, no agent issues. BOOM 3 paired+bonded+trusted. Cast-group
  name-matching caveat captured in New findings #8.
- **A2DP connect broken on the pipewire stack**: bluetoothd logs
  `a2dp-sink profile connect failed: Protocol not available` — no A2DP
  endpoints are ever registered. Verified across wireplumber's monitor, a
  manual `spa-node-factory` monitor with `api.bluez5.enum.dbus`, and
  `pipewire-audio` installed (pipewire 1.4.2-1+rpt3, wireplumber 0.5.8-2,
  bluez 5.82-1.1+rpt2, kernel 6.18.50+rpt-rpi-v8). Matches the open BlueZ bug
  family (bluez#1610/#1922 — Pi 3/arm reports; no distro fix shipped yet).
- **Decision (user):** Phase C's BT audio layer uses **PulseAudio +
  pulseaudio-module-bluetooth** — the docker-era stack that already served
  this Boom speaker. mpv plays via `ao=pulse`; per-speaker `options.
  audio_device` targets pulse sink ids (`pulse/bluez_sink.<MAC>.a2dp-sink`).
  pipewire/wireplumber/pipewire-pulse stay installed but disabled (user
  services). The bluetoothctl-based BT card design is unchanged.
- **RESOLVED (executed on the RPi):** PulseAudio + pulseaudio-module-bluetooth
  installed, pipewire/wireplumber/pipewire-pulse user services disabled,
  bluetooth restarted → `Endpoint registered` handlers exist →
  `bluetoothctl connect` to BOOM 3 **succeeded** (A2DP UUIDs + GATT services
  enumerated; BT battery level available via GATT). Phase C feasibility fully
  confirmed on hardware. `deploy/jukeplayer.service` already sets
  `XDG_RUNTIME_DIR=/run/user/__APP_UID__`, so mpv inside the backend reaches
  the user's pulse server.
- **Verified sink format (2026-09-24, user-confirmed):** pulse sink
  `bluez_sink.10_94_97_0F_CB_BF.a2dp_sink` (underscores for colons, sink
  profile), mpv device id `pulse/bluez_sink.10_94_97_0F_CB_BF.a2dp_sink`.
  The BT card's "add as speaker" flow writes exactly this id into the
  speaker's `options.audio_device`.
- The `pipewire-audio` meta-package was also missing from setup (now
  installed for completeness) → add it to `setup_rpi.sh` if pipewire is ever
  revisited.

## Phase C — Audio/BT card (2026-09-24, evening)

Live Bluetooth speaker management, built on the evening's verified ground
truth: bluetoothctl lifecycle as the app user + PulseAudio as the A2DP
endpoint provider (see "Phase C pre-work" for the pipewire regression that
forced the stack swap).

- **New `app/services/bluetooth_service.py`** (`bluetooth_service` singleton):
  blocking wrapper around `bluetoothctl` (status/devices/info/scan/pair/
  trust/connect/disconnect/remove — routes offload via `asyncio.to_thread`)
  and `pactl` (sink discovery). The scan keeps one bluetoothctl session alive
  for the window (bluez stops discovery when the starting client exits).
  Parsers (`parse_devices`/`parse_info`/`parse_pactl_sinks`) are pure and
  unit-tested; UUIDs are extracted from the parenthesised form bluetoothctl
  prints. `pair_and_connect()` = the card's single click (pair → trust →
  connect). `auto_connect_trusted()` reconnects paired A2DP devices at boot
  (design decision #3).
- **API** `app/routes/bluetooth_api.py`: `GET /api/bluetooth/status`,
  `GET /api/bluetooth/scan?seconds=…`, `POST /api/bluetooth/pair|connect|
  disconnect|forget`, `GET /api/bluetooth/sinks`. MAC-validated; blocking
  calls in `asyncio.to_thread`.
- **Web card** `components/kiosk/config/_bluetooth_card.html` (included on
  the config page under the Speakers card): adapter status, scan button with
  the pairing-mode hint, device list with per-state actions — connected:
  Disconnect / Add-as-speaker (only when a pulse sink exists); paired:
  Connect; unpaired (after scan): Pair. Errors render inside the card.
  `_config_ui_context` merges the card context so the full-page include works.
- **Add-as-speaker flow:** connected BT device → speaker entry via
  `SpeakerManagerService.add_speaker` — backend `mpv`,
  `options.audio_device = pulse/bluez_sink.<MAC>.a2dp_sink` (verified sink
  format), display_name = the device's friendly name. Duplicate names are
  rejected with the card error (existing entries: remove + re-add to rebind
  the sink — v1).
- `main.py` startup: background `reconnect_bluetooth()` task (paired BT
  speakers auto-connect after a reboot).
- `scripts/setup_rpi.sh`: swaps the audio stack — installs
  `pulseaudio pulseaudio-module-bluetooth pulseaudio-utils` (+ `rfkill`),
  unblocks rfkill on boot, enables `pulseaudio.service/.socket` and disables
  the pipewire user services.
- **Tests added:** `tests/services/test_bluetooth_service.py` (8: parsers,
  device flags, pair success/failure, sink mapping, auto-connect gating) +
  `tests/routes/test_bluetooth_api.py` (7: status/scan/pair validation/
  sinks/card add-speaker incl. duplicate rejection and full-page render).
  **Suite: 96 passing.**

## Routing bug: mpv display-form device names (found 2026-09-24, RPi)

While debugging the simultaneous audio stop, the journal exposed a routing
bug: MPVService emits TRACK_FINISHED with the **display-form** device name
(`OPENRUN PRO 2 BY SHOKZ` — uppercased, spaces) while the speakers registry
keys are normalized store names (`openrun_pro_2_by_shokz`).
`SpeakerBrokerService.resolve_speaker` matched exactly → miss → **fallback to
the default speaker**: after a track ended on a live-added BT speaker,
next_track/stop executed against the Chromecast instead ("stop(bedroom)") and
the mpv playlist stopped instead of advancing.

- Fix: `resolve_speaker` normalizes the payload device_name
  (`normalize_speaker_name`) before the lookup — covers case, spaces and
  underscores for every event source. Test added (display/store/mixed forms
  all resolve to the right speaker). Suite: 104 passing.

## Final state notes

- Old 44MB `jukebox.log` at repo root and `tmp_mpv.log` are orphaned — safe to delete.
- For the RPi deployment: rebuild the image (requirements changed), and note `ENABLE_DOCS` now defaults to false in compose.
- Test-env config still has `LOG_LEVEL=DEBUG` — consider INFO now that debug logging is opt-in.

## Test-env verification (Batch 1) — 2026-09-24

- Startup clean on second attempt; INFO-only logging (no DEBUG), zero `Error receiving message` lines; auto-advance (`TRACK_FINISHED → next_track`) works; chromecast stop-timeout still present (expected — Batch 4).
- **Startup failure at 09:02:29 was environmental**, not code: the first launch picked up `/Users/martinhinge/projects/resumator/.venv` (Python 3.14, no pychromecast). The retry used the right venv. Recommendation: launch explicitly with `jukeplayer_backend/venv/bin/uvicorn`.
- Observed: startup eagerly connects to all 3 Chromecasts + spawns MPV just to sync the default volume (50%) — `VolumeManager.__init__` runs `sync_volume_from_backend` at construction. Slow startup + log noise; candidate deferral in Batch 6.

## Consumers checked before removals (Batch 2)

- `/api/mediaplayer/status` — **used** by Home Assistant polling fallback (`media_player.py:315`) → fixed, not removed.
- `/api/output/status`, `/api/output/switch` — HA calls commented out; web UI doesn't call → fixed anyway (cheap).
- `/api/output/speakers` — actively used by HA `get_output_devices` → kept, hardened.
- `/stream/current`, `/api/chromecast/*`, `/api/system/clients*` — no consumers anywhere → removed.

---

## New findings (running list)

0. **Dead projects** (user, 2026-09-24): `jukeplayer_dial/`, `jukeplayer_rpi/`, `ws_client/` are inactive — only ESP32, HA, and web (part of the backend) clients are live. Earlier concerns about the Pi client's bare HTTP calls are moot; the bare-HTTP consumers that matter are HA and the web UI, both covered by the default-speaker fallback.
1. ~~DB not persisted~~ — **moot**: album.db deleted entirely (Batch 3.5). The old `album.db` in the container image dies with the next image build; nothing reads it anymore.
2. **HA `switch_output_device`** calls `mediaplayer/instances/{device}/control` — an endpoint that was removed with the client registry (and its call site in HA is commented out). If device switching from HA is wanted later, it must be re-implemented against the speaker broker. Tracked for a later batch (HA client changes out of scope for now).
3. `routes/subsonic.py` uses deprecated `regex=` in `Query(...)` (FastAPI warning) → switch to `pattern=` (Batch 8).
4. Old 44MB `jukebox.log` at repo root is orphaned after Batch 1 (app now writes `logs/jukebox.log`) — safe to delete.
5. ~~NOTIFICATION events go nowhere~~ — **resolved**: events removed entirely (Batch 3.5).
6. ~~NFC-encode flow never persists an rfid→album mapping~~ — **moot**: DB removed (Batch 3.5); cards are self-describing.
7. Startup eagerly connects to all Chromecasts + spawns MPV just to sync default volume 50 (`VolumeManager.__init__` → `sync_volume_from_backend`) — slow startup + log noise; candidate deferral in Batch 6.
8. **Cast groups don't match by name** (found on RPi 2026-09-24): discovery surfaces cast GROUPS (e.g. "Home group"), but the connect path normalizes the store name `home_group` → `"Home Group"` while the device reports `"Home group"` — and the match is an exact string compare, so playback to such a speaker fails with "Device 'Home Group' not found on network". Exact-title-case names (Living Room, Bedroom, …) match fine. Fix plan: make the target match case/whitespace-insensitive (and consider storing the cast UUID in speaker options at add time for robust matching). Until then, adding a group works as a config entry but playback to it will not connect.