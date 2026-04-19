import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    connect() {
        // This runs the moment the <body> is loaded
        window.appState = window.appState || {};
        window.appState.lastTrackData = null; // Initialize cache
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
        
        
        console.log(`WS: Received message of type "${msg.type}" with payload:`, msg.payload);

        if (msg.type === 'current_track') {
            
            window.appState.lastTrackData = msg.payload.current_track;
            window.appState.playlist = msg.payload.playlist;
            window.appState.volume = msg.payload.volume;
            window.appState.deviceName = msg.payload.output_device;
            window.appState.playerStatus = msg.payload.status;
            window.appState.repeatState = msg.payload.repeat_album;
            window.appState.isMuted = msg.payload.is_muted;

            this.broadcast("nowplaying-update", { track: msg.payload });
        }

        if (msg.type === 'volume_changed') {
            window.appState.volume = msg.payload;
            this.broadcast("volume-change", { volume: msg.payload });
        }

        if (msg.type === 'switch_device_response') {
            window.appState.deviceName = msg.payload[0].device_id;
            this.broadcast("switch-device-response", { response: msg.payload });
        }

        if (msg.type === 'nfc_encoding_started') {
            this.broadcast("nfc-encoding-started", { response: msg.payload });
        }

        if (msg.type === 'nfc_encoding_completed') {
            this.broadcast("nfc-encoding-completed", { response: msg.payload });
        }

        if (msg.type === 'toggle_repeat_changed') {
            window.appState.repeatState = msg.payload.mode;
            this.broadcast("toggle-repeat-changed", { response: msg.payload });
            }

        if (msg.type === 'volume_mute_response') {
            window.appState.isMuted = msg.payload.is_muted;
            this.broadcast("volume_mute_response", { response: msg.payload });
            
        }

        console.log("AppState:", window.appState);
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
}