import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-playercontrols-target' in the HTML
    static targets = []

    connect() {
        console.log("player controls Controller connected to the DOM")

    }


    playPause() {
        console.log("Play/Pause button clicked - Sending via WS");
        
        // Create the event that the WebSocket controller is listening for
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "play_pause", 
                payload: {} // Your server expects this payload
            } 
        });
        
        window.dispatchEvent(event);
    }  

    next() {
        console.log("Next button clicked - Sending via WS");
        
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "next_track", 
                payload: {} 
            } 
        });
        
        window.dispatchEvent(event);
    }

    previous() {
        console.log("Previous button clicked - Sending via WS");
        
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "previous_track", 
                payload: {} 
            } 
        });
        
        window.dispatchEvent(event);
    }

    stop() {
        console.log("Stop button clicked - Sending via WS");
        
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "stop", 
                payload: {} 
            } 
        });
        
        window.dispatchEvent(event);
    }

    volumeDown() {
        console.log("Volume Down button clicked - Sending via WS");
        
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "volume_down", 
                payload: {} 
            } 
        });
        
        window.dispatchEvent(event);
    }

    volumeUp() {
        console.log("Volume Up button clicked - Sending via WS");
        
        const event = new CustomEvent("ws:send", { 
            detail: { 
                type: "volume_up", 
                payload: {} 
            } 
        });
        
        window.dispatchEvent(event);
    }

    playAlbum(event) {
        console.log("Play Album button clicked - Sending via WS");
        
        const albumId = event.params.albumId;
        const wsEvent = new CustomEvent("ws:send", { 
            detail: { 
                type: "play_album", 
                payload: { "album_id": albumId } 
            } 
        });
        
        window.dispatchEvent(wsEvent);


        window.dispatchEvent(new CustomEvent("nav:go", { 
            detail: "/kiosk/player" 
        }));
    }

    playTrack(event) {
        console.log("Play Track button clicked - Sending via WS");
        
        const trackIndex = event.params.trackIndex;
        const wsEvent = new CustomEvent("ws:send", { 
            detail: { 
                type: "play_track", 
                payload: { "track_index": trackIndex } 
            } 
        });
        
        window.dispatchEvent(wsEvent);


        window.dispatchEvent(new CustomEvent("nav:go", { 
            detail: "/kiosk/player" 
        }));
    }

}