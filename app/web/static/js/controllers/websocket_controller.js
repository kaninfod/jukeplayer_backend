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
        
        // Generate or retrieve unique client ID per browser tab (using sessionStorage)
        // Prefers crypto.randomUUID(), falls back to manual UUID generation
        let clientId = sessionStorage.getItem('clientId');
        if (!clientId) {
            if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                clientId = crypto.randomUUID();
            } else {
                // Fallback: Generate UUID v4 manually
                clientId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                    const r = Math.random() * 16 | 0;
                    const v = c === 'x' ? r : (r & 0x3 | 0x8);
                    return v.toString(16);
                });
            }
            sessionStorage.setItem('clientId', clientId);
        }
        console.log("Client ID:", clientId);
        
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/mediaplayer/events?detail=full&session_token=${clientId}&client_id=${clientId}`;
        
        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
            console.log("WS: Connected");
            window.appState.wsStatus = "connected";
            this.broadcast("ws-status", {"status": "connected"});
        };

        this.socket.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this.routeMessage(msg);
        };

        this.socket.onclose = () => {
            console.log("WS: Closed. Reconnecting...");
            window.appState.wsStatus = "closed";
            this.broadcast("ws-status", {"status": "closed"});
            setTimeout(() => this.connectWebSocket(), 2000);
        };
    }

    routeMessage(msg) {
        
        
        console.log(`WS: Received message of type "${msg.type}" with payload:`, msg.payload);

        if (msg.type === 'register_response') {
            // Backend-assigned client ID - store it and update app state
            if (msg.payload.status === 'success' && msg.payload.client_id) {
                const backendClientId = msg.payload.client_id;
                sessionStorage.setItem('clientId', backendClientId);
                window.appState.clientId = backendClientId;
                console.log("Client registered with backend ID:", backendClientId);
                this.broadcast("register-response", { response: msg.payload });
            }
        }

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
            console.log("Handling switch device response:", msg.payload);
            window.appState.deviceName = msg.payload.device_id;
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

        if (msg.type === 'ping') {
            window.appState.wsStatus = "connected";
            this.broadcast("ws-status", {"status": "connected"});
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
}