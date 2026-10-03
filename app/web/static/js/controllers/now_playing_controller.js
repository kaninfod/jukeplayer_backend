import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-nowplaying-target' in the HTML
    static targets = [ "artist", "title", "album", "tracknum", "cover", "status", "repeat", "trackinfo", "notrackinfo", "notrackinfo", "nocover", "coverimg", "repeatstatus", "playerstatus", "volumefill", "volumetext", "currentdevice", "mutestate", "wsstatus", "speakerscard", "speakername", "speakerstate", "speakericon", "speakertile", "speakertype", "speakertypeicon", "speakertypetext", "speakerclients" ]

    connect() {
        console.log("Now Playing Controller connected to the DOM", window.appState.lastTrackData);
        window.dispatchEvent(new CustomEvent("ws:request-sync"));

        if (window.appState.lastTrackData) {
            this.update();
        }
    

    }

    initialize() {
        // Listen once and stay awake forever
        window.addEventListener("app:screen-changed", (event) => {
            if (event.detail.isPlayer) {
                // this.update();
                this.handleExternalUpdate(event);
            }
        });
    }

    update() {
        const data = window.appState.lastTrackData;
        if (!data) {
            console.log("No track data available to update Now Playing.");
            return;
        }

        console.log("Updating Now Playing with track data:", data);

        const hasTrack = !!data.artist;
        console.log(
            `Has track: ${hasTrack}, Artist: ${data.artist}, Title: ${data.title}, ` +
            `Album: ${data.album}, Tracknum: ${data.track_number}, Cover URL: ${data.cover_url}`
        );

        this.renderState(hasTrack);

        if (hasTrack) {
            this.updateTrackInfo(data);
            this.updateCover(data.cover_url);
        }

        this.updatePlayerControls();
        this.updatePlaylistHighlight();
    }

    // playlist page: keep the playing track's row highlighted + in view;
    // the render-time highlight gets stale as tracks advance
    updatePlaylistHighlight() {
        const data = window.appState.lastTrackData;
        const trackNumber = data && data.track_number;
        if (!trackNumber) return;
        const rows = document.querySelectorAll(".kiosk-playlist-item");
        if (!rows.length) return;
        rows.forEach((row) => {
            const idx = Number(row.dataset.playercontrolsTrackIndexParam);
            row.classList.toggle("active", idx === trackNumber - 1);
        });
        const active = document.querySelector(".kiosk-playlist-item.active");
        if (active) active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    renderState(hasTrack) {
        if (this.hasTrackinfoTarget) {
            this.trackinfoTarget.classList.toggle("d-none", !hasTrack);
        }
        if (this.hasCoverTarget) {
            this.coverTarget.classList.toggle("d-none", !hasTrack);
        }
        if (this.hasNotrackinfoTarget) {
            this.notrackinfoTarget.classList.toggle("d-none", hasTrack);
        }
        if (this.hasNocoverTarget) {
            this.nocoverTarget.classList.toggle("d-none", hasTrack);
        }
    }

    updateTrackInfo(data) {
        if (this.hasArtistTarget) {
            this.artistTarget.textContent = data.artist;
        }
        if (this.hasTitleTarget) {
            this.titleTarget.textContent = data.title;
        }
        if (this.hasAlbumTarget) {
            this.albumTarget.textContent = data.album;
        }
        if (this.hasTracknumTarget && window.appState.playlist) {
            this.tracknumTarget.textContent =
                `Track ${data.track_number} of ${window.appState.playlist.length}`;
        }
    }

    updateCover(coverUrl) {
        if (!this.hasCoverimgTarget) return;

        if (coverUrl) {
            const url = coverUrl.startsWith('/')
                ? `${window.location.origin}${coverUrl}?size=512`
                : coverUrl;
            this.coverimgTarget.src = url;
        } else {
            console.log("UPDATE: No cover_url, showing placeholder");
            this.coverimgTarget.src = '';
        }
    }

    updatePlayerControls() {
        const { playerStatus, repeatState, volume, deviceName } = window.appState;
        console.log(
            `Playback status: ${playerStatus}, Repeat: ${repeatState}, ` +
            `Volume: ${volume}, Output Device: ${deviceName}`
        );

        this.updateRepeatState();
        this.updatePlayerstatus();
        this.updateVolume();
        this.updateDevice();
        this.updateMuteState();
    }


    renderState(hasTrack) {
        // Guarded: this controller also runs on pages (or page states) where
        // these targets do not exist; an unguarded access here would throw
        // "Missing target element" and abort the whole update (volume, mute,
        // player status would stop updating — seen 2026-09-24).
        if (this.hasTrackinfoTarget) {
            this.trackinfoTarget.classList.toggle("d-none", !hasTrack);
        }
        if (this.hasCoverTarget) {
            this.coverTarget.classList.toggle("d-none", !hasTrack);
        }
        if (this.hasNotrackinfoTarget) {
            this.notrackinfoTarget.classList.toggle("d-none", hasTrack);
        }
        if (this.hasNocoverTarget) {
            this.nocoverTarget.classList.toggle("d-none", hasTrack);
        }
    }

    updateVolume() {
        const volume = parseInt(window.appState.volume) || 0;

        if (this.hasVolumetextTarget) {
            this.volumetextTargets.forEach(element => {
                element.textContent = `${volume}%`;
            });
        }

    }  

    updateDevice() {
        const info = this._speakerInfo();
        // status-bar chip: the cast icon stays, the span names the speaker
        if (this.hasCurrentdeviceTarget) {
            this.currentdeviceTarget.textContent =
                (info && info.display_name)
                || window.appState.mediaplayerInstanceName
                || "Active Device";
        }
        this.updateSpeakerCard();
    }

    _speakerMap() {
        if (!this.hasSpeakerscardTarget) return {};
        try {
            return JSON.parse(this.speakerscardTarget.dataset.nowplayingSpeakersMap || "{}");
        } catch (e) {
            console.warn("nowplaying: speakers-map attr unparsable", e);
            return {};
        }
    }

    _speakerInfo() {
        // appState.deviceName = output_device (the technical store name);
        // mediaplayerInstanceName is a display-form transform (underscores →
        // Title Case, mpv speakers can be display-form natively) — so both
        // forms and a folded comparison are tried before giving up
        const key = (window.appState.deviceName || "").toString();
        if (!key) return null;
        const map = this._speakerMap();
        const fold = (s) => (s || "").toString().replace(/[\s_]+/g, " ").trim().toLowerCase();
        const wanted = [key, fold(key), fold(window.appState.mediaplayerInstanceName)];
        for (const w of wanted) {
            if (!w) continue;
            for (const [name, info] of Object.entries(map)) {
                if (name === w || fold(name) === w) return info;
            }
        }
        return null;
    }

    updateSpeakerCard() {
        // guarded — the card lives only on the player page
        if (!this.hasSpeakerscardTarget) return;
        const info = this._speakerInfo();
        const status = (window.appState.playerStatus || "idle").toLowerCase();

        if (this.hasSpeakernameTarget) {
            this.speakernameTarget.textContent =
                (info && info.display_name)
                || window.appState.mediaplayerInstanceName
                || window.appState.deviceName
                || "No speaker configured";
        }

        const type = (info && info.type) || "local";
        const spec = {
            chromecast: { icon: (info && info.icon) || "mdi-cast", tile: "tile-cc",
                          badge: "type-cc", badgeIcon: "mdi-cast", label: "Chromecast" },
            bluetooth:  { icon: (info && info.icon) || "mdi-bluetooth", tile: "tile-bt",
                          badge: "type-bt", badgeIcon: "mdi-bluetooth", label: "BT" },
            local:      { icon: (info && info.icon) || "mdi-speaker", tile: "tile-audio",
                          badge: "type-audio", badgeIcon: "mdi-speaker", label: "Audio" },
        }[type] || { icon: "mdi-speaker", tile: "tile-audio",
                     badge: "type-audio", badgeIcon: "mdi-speaker", label: "Audio" };

        if (this.hasSpeakertileTarget) {
            ["tile-cc", "tile-bt", "tile-audio"].forEach(c =>
                this.speakertileTarget.classList.toggle(c, c === spec.tile));
        }
        if (this.hasSpeakericonTarget) {
            this.speakericonTarget.className = "mdi " + spec.icon;
        }
        if (this.hasSpeakertypeTarget) {
            ["type-cc", "type-bt", "type-audio"].forEach(c =>
                this.speakertypeTarget.classList.toggle(c, c === spec.badge));
        }
        if (this.hasSpeakertypeiconTarget) {
            this.speakertypeiconTarget.className = "mdi " + spec.badgeIcon;
        }
        if (this.hasSpeakertypetextTarget) {
            this.speakertypetextTarget.textContent = spec.label;
        }
        if (this.hasSpeakerclientsTarget) {
            const n = (info && info.clients) ?? 0;
            this.speakerclientsTarget.textContent = `${n} client${n === 1 ? "" : "s"}`;
        }

        if (this.hasSpeakerstateTarget) {
            const pill = {
                playing: { cls: "player-playing", label: "Playing" },
                paused:  { cls: "player-paused",  label: "Paused" },
                idle:    { cls: "player-idle",    label: "Idle" },
            }[status] || { cls: "player-idle", label: "Idle" };
            this.speakerstateTarget.className = "device-player-pill " + pill.cls;
            this.speakerstateTarget.textContent = pill.label;
        }
    }

    updateRepeatState() {
        console.log("Updating repeat state in UI");
        
        const state = window.appState.repeatState;

        if (this.hasRepeatstatusTarget) {
            const repeatStr = state ? 'mdi mdi-repeat' : 'mdi mdi-repeat-off';
            this.repeatstatusTargets.forEach(element => {
                    element.className = repeatStr
            });
        }

    }   

    updateSocketStatus() {
        const status = window.appState.wsStatus;
        
        if (this.hasWsstatusTarget) {
            
            const statusIconMap = {
                'connected': 'mdi mdi-web-check',
                'closed': 'mdi mdi-web-off'
            };
            this.wsstatusTarget.className = statusIconMap[status] || 'mdi mdi-web-off';
        }
    }

    updateMuteState() {
        const state = window.appState.isMuted;
        if (this.hasMutestateTarget) {
            const muteStr = state ? 'mdi mdi-volume-off' : 'mdi mdi-volume-high';
            this.mutestateTarget.className = muteStr;
        }

    }   


    updatePlayerstatus() {
        console.log("Updating player status in UI", window.appState.playerStatus, this.hasPlayerstatusTarget);
        if (this.hasPlayerstatusTarget) {
            const iconMap = {
                    'playing': 'mdi mdi-play',
                    'paused':  'mdi mdi-pause',
                    'idle':    'mdi mdi-stop'
                };
            
            const statusStr = iconMap[window.appState.playerStatus] || window.appState.playerStatus;
            console.log(`Updating player status icon to: ${statusStr}`);
            if (this.hasPlayerstatusTarget) {
                this.playerstatusTarget.className = statusStr;
            }
        }

    }

    handleExternalUpdate(evt) {
        const trackData = window.appState.lastTrackData;
        
        if (trackData !== undefined) {
            this.update();
        } else {
            console.log("Received nowplaying-update event without track data:", evt.detail);
        }
    }
}