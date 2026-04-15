import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    connect() {
        // This runs the moment the <body> is loaded
        this.lastTrackData = null; // Initialize cache
        this.connectWebSocket();
    }

    disconnect() {
        // Cleanup if the controller is removed from the DOM
        if (this.socket) {
            this.socket.close();
        }
    }

    connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/mediaplayer/events?detail=full&session_token=123456789abcdef&client_id=webclient_hinge`;
        
        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => console.log("WS: Connected");

        this.socket.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this.routeMessage(msg);
        };

        this.socket.onclose = () => {
            console.log("WS: Closed. Reconnecting...");
            setTimeout(() => this.connectWebSocket(), 2000);
        };
    }

    routeMessage(msg) {
        // Instead of calling functions, we just broadcast events

        console.log(`WS: Received message of type "${msg.type}" with payload:`, msg.payload);

        if (msg.type === 'current_track') {
            this.lastTrackData = msg.payload;
            this.broadcast("nowplaying-update", { track: msg.payload });
        }

        if (msg.type === 'volume_changed') {
            this.broadcast("volume-change", { volume: msg.payload });
        }

        if (msg.type === 'switch_device_response') {
            this.broadcast("switch-device-response", { response: msg.payload });
        }

        if (msg.type === 'nfc_encoding_started') {
            this.broadcast("nfc-encoding-started", { response: msg.payload });
        }

        if (msg.type === 'nfc_encoding_completed') {
            this.broadcast("nfc-encoding-completed", { response: msg.payload });
        }

    }

    broadcast(name, detail) {
        window.dispatchEvent(new CustomEvent(name, { detail }));
    }

    handleOutgoing(event) {
        const { type, payload } = event.detail;
        
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ 
                type: type, 
                payload: payload || {} 
            }));
            console.log(`WS: Sent ${type}`, payload);
        } else {
            console.warn("WS: Attempted to send message while socket was closed.");
        }
    }

    syncNowPlaying() {
        console.log("Syncing Now Playing data to new UI component");
        if (this.lastTrackData) {
            console.log("Syncing cached track data to new UI component");
            this.broadcast("nowplaying-update", { track: this.lastTrackData });
        } else {
            // Option 2: If we don't have a cache, ask the server via WS
            // this.send("get_current_status"); 
        }
    }
}