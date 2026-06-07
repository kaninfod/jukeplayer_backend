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
        
        // Build WebSocket URL (client_id now sent via register_client message, not query param)
        let wsUrl = `${wsProtocol}//${window.location.host}/ws/mediaplayer/events?detail=full`;
        
        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
            console.log("WS: Connected");
            window.appState.wsStatus = "connected";
            this.broadcast("ws-status", {"status": "connected"});
            
            // Send explicit registration message (like ESP32 does)
            this.sendRegisterClient();
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

    sendRegisterClient() {
        // Send registration message to backend
        // Retrieve stored client_id from previous session (if exists)
        const storedClientId = localStorage.getItem('clientId');
        const storedDeviceId = localStorage.getItem('deviceId');  
        
        const registrationMsg = {
            "type": "register_client",
            "payload": {
                "client_type": "web",
                "client_name": "web_client",
                "capabilities": ["websocket_status"],
                "device_id": storedDeviceId || null,  // Web clients don't specify device_id - backend assigns default
                "client_id": storedClientId  // Send stored ID to enable session recovery
            }
        };
        
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(registrationMsg));
            console.log("WS: Sent register_client message", storedClientId ? `(recovery: ${storedClientId.substring(0, 8)}...)` : "(new session)");
        }
    }

    routeMessage(msg) {
        
        
        console.log(`WS: Received message of type "${msg.type}" with payload:`, msg.payload);

        if (msg.type === 'register_response') {
            // Extract client_id from registration response and store it
            if (msg.payload && msg.payload.status === 'success') {
                const clientId = msg.payload.client_id;
                localStorage.setItem('clientId', clientId);
                window.appState.clientId = clientId;

                console.log("WS: Registration successful, client and device ID stored:", clientId);
            } else {
                console.error("WS: Registration failed:", msg.payload);
            }
        }

        if (msg.type === 'current_track') {
            // Extract and store the assigned client_id from server
            // This ensures browser and backend use the same ID across reconnects
            if (msg.client_id) {
                const assignedClientId = msg.client_id;
                // Only update if different from current stored value
                const storedClientId = localStorage.getItem('clientId');
                if (storedClientId !== assignedClientId) {
                    localStorage.setItem('clientId', assignedClientId);
                    console.log("Updated stored client ID:", assignedClientId);
                }
                window.appState.clientId = assignedClientId;
            }
            
            window.appState.lastTrackData = msg.payload.current_track;
            window.appState.playlist = msg.payload.playlist;
            window.appState.volume = msg.payload.volume;
            window.appState.deviceName = msg.payload.output_device;
            window.appState.mediaplayerInstanceName = msg.payload.mediaplayer_instance_name;
            window.appState.playerStatus = msg.payload.status;
            window.appState.repeatState = msg.payload.repeat_album;
            window.appState.isMuted = msg.payload.is_muted;

            
            localStorage.setItem('deviceId', window.appState.deviceName);
            


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