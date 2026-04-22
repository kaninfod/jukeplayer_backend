import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-nowplaying-target' in the HTML
    static targets = [ "artist", "title", "album", "tracknum", "cover", "status", "repeat", "trackinfo", "notrackinfo", "notrackinfo", "nocover", "coverimg", "repeatstatus", "playerstatus", "volumefill", "volumetext", "currentdevice", "mutestate", "wsstatus" ]

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
                this.update();
            }
        });
    }

    // This replaces your updateKioskVolume(data) function
    update() {
        const data = window.appState.lastTrackData;
        const hasTrack = !!data.artist;
        
        console.log(`Has track: ${hasTrack}, Artist: ${data.artist}, Title: ${data.title}, Album: ${data.album}, Tracknum: ${data.track_number}, Cover URL: ${data.cover_url}`);
        
        if (hasTrack) {
            console.log("Track data is present, updating UI elements.");
            if (this.hasTrackinfoTarget) {
                this.trackinfoTarget.classList.remove("d-none");
            }
            if (this.hasCoverTarget) {
                this.coverTarget.classList.remove("d-none");
            }
            if (this.hasNotrackinfoTarget) {
                this.notrackinfoTarget.classList.add("d-none");
            }
            if (this.hasNocoverTarget) {
                this.nocoverTarget.classList.add("d-none");
            }

            if (this.hasArtistTarget) {
                this.artistTarget.textContent = `${data.artist}`;
            }

            if (this.hasTitleTarget) {
                this.titleTarget.textContent = `${data.title}`;
            }

            if (this.hasAlbumTarget) {
                this.albumTarget.textContent = `${data.album}`;
            }

            if (this.hasTracknumTarget) {
                const trackNumberText = `Track ${data.track_number} of ${window.appState.playlist.length}`;
                this.tracknumTarget.textContent = trackNumberText;
            }
            
            // this.renderState(hasTrack);

            if (this.hasCoverTarget) {
                let coverUrl = data.cover_url;
                if (coverUrl) {

                    if (coverUrl.startsWith('/')) {
                        coverUrl = window.location.origin + coverUrl + '?size=512';
                    }
                    // console.log(`[${timestamp}] UPDATE: Loading album art from: ${coverUrl}`);
                    this.coverimgTarget.src = coverUrl;
                } else {
                    console.log(`UPDATE: No cover_url, showing placeholder`);
                    this.coverimgTarget.src = '';
                }
            }

        } else {
            console.log("No track data available, showing placeholders.");
            if (this.hasTrackinfoTarget) {
                this.trackinfoTarget.classList.add("d-none");
            }
            if (this.hasCoverTarget) {
                this.coverTarget.classList.add("d-none");
            }
            if (this.hasNotrackinfoTarget) {
                this.notrackinfoTarget.classList.remove("d-none");
            }
            if (this.hasNocoverTarget) {
                this.nocoverTarget.classList.remove("d-none");
            }
        }  
        
        console.log(`Playback status: ${window.appState.playerStatus}, hastarget: ${this.hasPlaystatusTarget}, Repeat: ${window.appState.repeatState}, Volume: ${window.appState.volume}, Output Device: ${window.appState.deviceName}`);


        this.updateRepeatState();
        this.updatePlayerstatus();
        this.updateVolume();
        this.updateDevice();
        this.updateMuteState();
    }


    renderState(hasTrack) {
        this.trackinfoTarget.classList.toggle("d-none", !hasTrack);
        this.coverTarget.classList.toggle("d-none", !hasTrack);

        this.notrackinfoTarget.classList.toggle("d-none", hasTrack);
        this.nocoverTarget.classList.toggle("d-none", hasTrack);
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
        if (this.hasCurrentdeviceTarget) {
            this.currentdeviceTarget.textContent = window.appState.deviceName;
        } else {
            console.log("Device UI span not found on this page.");
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