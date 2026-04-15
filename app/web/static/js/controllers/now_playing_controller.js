import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-nowplaying-target' in the HTML
    static targets = [ "artist", "title", "album", "tracknum", "cover", "status", "repeat", "trackinfo", "notrackinfo", "nocover" ]

    connect() {
        console.log("Now Playing Controller connected to the DOM")
        window.dispatchEvent(new CustomEvent("ws:request-sync"));
    }

    // This replaces your updateKioskVolume(data) function
    update(data) {
        const timestamp = new Date().toLocaleTimeString('en-US', { 
            hour12: false, hour: '2-digit', minute: '2-digit', 
            second: '2-digit', fractionalSecondDigits: 3 
        });

        console.log(`[${timestamp}] STIMULUS UPDATE NOW PLAYING: ${data}`);
        

        const hasTrack = !!data.current_track;


        if (data.current_track) {
            if (this.hasArtistTarget) {
                this.artistTarget.textContent = `${data.current_track.artist}`;
            }

            if (this.hasTitleTarget) {
                this.titleTarget.textContent = `${data.current_track.title}`;
            }

            if (this.hasAlbumTarget) {
                this.albumTarget.textContent = `${data.current_track.album}`;
            }

            if (this.hasTracknumTarget) {
                const trackNumberText = `Track ${data.current_track.track_number} of ${data.playlist.length}`;
                this.tracknumTarget.textContent = trackNumberText;
            }
            
            this.renderState(hasTrack);

            if (this.hasCoverTarget) {
                let coverUrl = data.current_track.cover_url;
                if (coverUrl) {

                    if (coverUrl.startsWith('/')) {
                        coverUrl = window.location.origin + coverUrl + '?size=512';
                    }
                    console.log(`[${timestamp}] UPDATE: Loading album art from: ${coverUrl}`);
                    this.coverTarget.src = coverUrl;
                } else {
                    console.log(`[${timestamp}] UPDATE: No cover_url, showing placeholder`);
                    this.coverTarget.src = '';
                }
            }

            const iconMap = {
                    'playing': 'mdi mdi-play',
                    'paused':  'mdi mdi-pause',
                    'idle':    'mdi mdi-stop'
                };
            
            const statusStr = iconMap[data.status] || data.status;

            if (this.hasStatusTarget) {
                this.statusTarget.className = statusStr;
            }

            
            const repeatStr = data.repeat_album ? 'mdi mdi-repeat' : 'mdi mdi-repeat-off';

            if (this.hasRepeatTarget) {
                this.repeatTarget.className = repeatStr;
            }

            this.updateVolume(data.volume);
            this.updateDevice(data.output_device);


        }
    }
    renderState(hasTrack) {
        this.trackinfoTarget.classList.toggle("d-none", !hasTrack);
        this.coverTarget.classList.toggle("d-none", !hasTrack);

        this.notrackinfoTarget.classList.toggle("d-none", hasTrack);
        this.nocoverTarget.classList.toggle("d-none", hasTrack);
    }

    updateVolume(newVol) {
        const event = new CustomEvent("volume-change", { 
            detail: { volume: newVol } 
        });
        window.dispatchEvent(event);
    }    

    updateDevice(deviceId) {
        console.log("Updating active device in UI to:", deviceId);

        const mockResponse = [{
            status: "ok",
            device_name: deviceId,
            backend: "manual-update"
        }];
        const event = new CustomEvent("switch-device-response", { 
            detail: { response: mockResponse } 
        });
        window.dispatchEvent(event);
    }    

    handleExternalUpdate(evt) {
        const trackData = evt.detail.track;
        
        if (trackData !== undefined) {
            this.update(trackData);
        }
    }
}