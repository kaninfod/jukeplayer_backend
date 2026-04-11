// Control and navigation functions (moved from template)
function control(action) {
    const actionMap = {
        play: 'play_pause',
    };
    const resolvedAction = actionMap[action] || action;

    apiFetch(`/api/mediaplayer/${resolvedAction}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data && data.status === 'error') {
                showKioskToast(data.message || 'Media control failed', { theme: 'error' });
                return;
            }
            if (typeof window.refreshKioskStatus === 'function') {
                window.refreshKioskStatus();
            }
        })
        .catch(error => {
            console.error('Media control error:', error);
            showKioskToast('Media control failed', { theme: 'error' });
        });
}

// Auto-initialize when component loads (only if required DOM elements exist)
function safeInit() {
    const safeTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
    const element = document.getElementById('kiosk-track-info');
    console.log(`[${safeTimestamp}] INIT: safeInit() called. kiosk-track-info element exists: ${!!element}`);
    
    if (element) {
        console.log(`[${safeTimestamp}] INIT: DOM ready, calling window.initPlayerStatus()`);
        window.initPlayerStatus();
    } else {
        console.log(`[${safeTimestamp}] INIT: kiosk-track-info not present; refreshing global status widgets`);
        if (typeof window.refreshKioskStatus === 'function') {
            window.refreshKioskStatus();
        }
    }
}

// Progress bar state
let progressInterval = null;
let trackDuration = 0;
let currentPosition = 0;
let lastUpdateTime = Date.now();

function formatTime(seconds) {
    if (!seconds || seconds < 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function renderProgress() {
    const progressFill = document.getElementById('kiosk-progress-fill');
    const progressTime = document.getElementById('kiosk-progress-time');
    
    if (progressFill && progressTime && trackDuration > 0) {
        const percent = Math.min(100, (currentPosition / trackDuration) * 100);
        progressFill.style.width = percent + '%';
        progressTime.textContent = `${formatTime(currentPosition)} / ${formatTime(trackDuration)}`;
    }
}

function syncProgress(serverPosition, duration, isPlaying) {
    trackDuration = duration || 0;
    currentPosition = serverPosition || 0;
    lastUpdateTime = Date.now();
    
    renderProgress();
    
    // Clear any existing interval
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    // Start new interval only if playing
    if (isPlaying && trackDuration > 0) {
        progressInterval = setInterval(() => {
            const elapsed = (Date.now() - lastUpdateTime) / 1000;
            currentPosition = (serverPosition || 0) + elapsed;
            
            if (currentPosition >= trackDuration) {
                clearInterval(progressInterval);
                progressInterval = null;
                currentPosition = trackDuration;
            }
            renderProgress();
        }, 1000);
    }
}

function updateKioskTrackInfo(data) {
    const timestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
    console.log(`[${timestamp}] UPDATE: Received data:`, data);
    console.log(`[${timestamp}] UPDATE: Data structure - has current_track: ${!!data.current_track}, has playlist: ${!!data.playlist}`);
    
    const kioskInfoDiv = document.getElementById('kiosk-track-info');
    const kioskThumbDiv = document.getElementById('kiosk-track-thumb');
    const deviceDiv = document.getElementById('current-device');
    const volumeFill = document.getElementById('kiosk-volume-fill');
    const volumeText = document.getElementById('kiosk-volume-text');
    
    console.log(`[${timestamp}] UPDATE: DOM elements - info: ${!!kioskInfoDiv}, thumb: ${!!kioskThumbDiv}, device: ${!!deviceDiv}, volumeFill: ${!!volumeFill}, volumeText: ${!!volumeText}`);
    
    const hasPlayerPanel = !!(kioskInfoDiv && kioskThumbDiv);
    if (!hasPlayerPanel) {
        console.warn(`[${timestamp}] UPDATE: Player panel not present; applying global UI updates only.`);
    }

    console.log(`[${timestamp}] UPDATE: ${deviceDiv}`);
    // Update Chromecast device name
    if (data.output_device && deviceDiv) {
        console.log(`[${timestamp}] UPDATE: Setting device to: ${data.output_device}`);
        deviceDiv.textContent = data.output_device;
    }
    
    // Update volume bar
    if (data.volume !== undefined && volumeFill && volumeText) {
        const volume = parseInt(data.volume) || 0;
        console.log(`[${timestamp}] UPDATE: Setting volume to: ${volume}%`);
        volumeFill.style.height = volume + '%';
        volumeText.textContent = volume + '%';
    }
    
    if (!hasPlayerPanel) {
        return;
    }

    if (data.current_track) {
        console.log(`[${timestamp}] UPDATE: Current track found - title: "${data.current_track.title}"`);
        console.log(`[${timestamp}] UPDATE: Validating required fields - artist: ${!!data.current_track.artist}, album: ${!!data.current_track.album}, year: ${!!data.current_track.year}, playlist length: ${data.playlist ? data.playlist.length : 'N/A'}`);
        
        // Validate all required fields exist before rendering
        if (!data.current_track.artist || !data.current_track.album || !data.current_track.year || !data.playlist) {
            console.error(`[${timestamp}] UPDATE: MISSING REQUIRED FIELDS - Cannot render. artist: "${data.current_track.artist}", album: "${data.current_track.album}", year: "${data.current_track.year}", playlist: ${!!data.playlist}`);
        }
        
        if (data.status == 'playing') {
            statusStr = 'mdi mdi-play';
        } else if (data.status == 'paused') {
            statusStr = 'mdi mdi-pause';
        } else if (data.status == 'idle') {
            statusStr = "mdi mdi-stop";
        } else {
            statusStr = data.status;
        }

        if (data.repeat_album) {
            repeatStr = 'mdi mdi-repeat';
        } else {
            repeatStr = 'mdi mdi-repeat-off';
        }

        kioskInfoDiv.innerHTML = `
            
            <div class="kiosk-artist">${data.current_track.artist}</div>
            <div class="kiosk-title">${data.current_track.title}</div>
            <div class="kiosk-album">${data.current_track.album} (${data.current_track.year})</div>
            <div class="kiosk-album">Track ${data.current_track.track_number} of ${data.playlist.length}</div>
            <div class="kiosk-status"><i class="${statusStr}"></i>   <i class="${repeatStr}"></i></div>
            
        `;
        console.log(`[${timestamp}] UPDATE: Track info rendered successfully  - original`);
        
        let coverUrl = data.current_track.cover_url;
        if (coverUrl) {
            // Prepend window.location.origin if coverUrl is a relative path
            if (coverUrl.startsWith('/')) {
                coverUrl = window.location.origin + coverUrl + '?size=512';
            }
            console.log(`[${timestamp}] UPDATE: Loading album art from: ${coverUrl}`);
            kioskThumbDiv.innerHTML = `<img src="${coverUrl}" alt="Album Cover" />`;
        } else {
            console.log(`[${timestamp}] UPDATE: No cover_url, showing placeholder`);
            kioskThumbDiv.innerHTML = '<div class="kiosk-no-cover"><i class="mdi mdi-music"></i></div>';
        }
        
        // Update progress bar
        const duration = data.current_track.duration || 0;
        const elapsed = data.elapsed_time || 0;
        const isPlaying = data.status === 'playing';
        console.log(`[${timestamp}] UPDATE: Progress - duration: ${duration}s, elapsed: ${elapsed}s, playing: ${isPlaying}`);
        syncProgress(elapsed, duration, isPlaying);
    } else {
        console.warn(`[${timestamp}] UPDATE: No current_track in data. data.message: "${data.message}"`);
        kioskInfoDiv.innerHTML = '<div class="kiosk-no-track">' + (data.message || 'No track loaded') + '</div>';
        kioskThumbDiv.innerHTML = '<div class="kiosk-no-cover"><i class="mdi mdi-music"></i></div>';
        
        // Clear progress bar when no track
        syncProgress(0, 0, false);
    }
}

window.updateKioskTrackInfo = updateKioskTrackInfo;

window.refreshKioskStatus = async function() {
    try {
        const response = await fetch('/api/mediaplayer/status');
        if (!response.ok) {
            throw new Error(`Status fetch failed: ${response.status}`);
        }
        const data = await response.json();
        const payloadData = (data && data.type && data.payload) ? data.payload : data;
        updateKioskTrackInfo(payloadData || {});
    } catch (error) {
        console.error('refreshKioskStatus error:', error);
    }
};

/**
 * Kiosk Player Status Component
 * Displays current track information, album art, and volume
 * 
 * WebSocket spec:
 * - Connects to /ws/mediaplayer/events?detail=full with session_token
 * - Receives messages: current_track, volume_changed, notification
 * - Handles reconnection via exponential backoff
 */

(function() {
    const initTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
    console.log(`[${initTimestamp}] INIT: player-status.js module loading`);
    console.log(`[${initTimestamp}] INIT: document.readyState = "${document.readyState}"`);

    // Close existing WebSocket if reloading
    if (window.__kioskPlayerStatusWs && window.__kioskPlayerStatusWs.readyState !== WebSocket.CLOSED) {
        try {
            window.__kioskPlayerStatusWs.close(1000, 'player-status reinit');
        } catch (e) {
            console.warn('Failed to close existing player-status websocket:', e);
        }
    }
    
    let wsReady = false;
    let apiReady = false;
    let wsReconnectDelay = 1000; // Start with 1 second
    const maxReconnectDelay = 30000; // Cap at 30 seconds
    let wsReconnectTimer = null;
    
    // Generate or retrieve unique session token for this browser tab
    function getOrCreateSessionToken() {
        const STORAGE_KEY = 'jukeplayer_session_token';
        let token = sessionStorage.getItem(STORAGE_KEY);
        if (!token) {
            // Generate new token using UUID v4
            token = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            sessionStorage.setItem(STORAGE_KEY, token);
            const tokenTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.log(`[${tokenTimestamp}] SESSION: Generated new session token: ${token}`);
        } else {
            const tokenTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.log(`[${tokenTimestamp}] SESSION: Retrieved existing session token: ${token}`);
        }
        return token;
    }
    
    // Expose initPlayerStatus globally so kiosk loader can call it
    window.initPlayerStatus = async function() {
        const funcTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        console.log(`[${funcTimestamp}] INIT: initPlayerStatus() called`);
        
        // Fetch initial state from API
        try {
            const response = await fetch('/api/mediaplayer/status');
            const respTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            
            if (response.ok) {
                const data = await response.json();
                console.log(`[${respTimestamp}] INIT: API response received (raw):`, data);
                
                // Unwrap API envelope if present (API returns {type, payload} but we need just the payload)
                const payloadData = (data.type && data.payload) ? data.payload : data;
                console.log(`[${respTimestamp}] INIT: API response unwrapped:`, payloadData);
                
                updateKioskTrackInfo(payloadData);
                apiReady = true;
                console.log(`[${respTimestamp}] INIT: API data rendered, apiReady = true`);
            } else {
                console.error(`[${respTimestamp}] INIT: API response not OK, status: ${response.status}`);
            }
        } catch (error) {
            const errTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.error(`[${errTimestamp}] INIT: Error fetching initial player status:`, error);
        }
    };
    
    // Connect to WebSocket with reconnection logic
    function connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const sessionToken = getOrCreateSessionToken();
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/mediaplayer/events?detail=full&session_token=${encodeURIComponent(sessionToken)}`;
        const connTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        console.log(`[${connTimestamp}] WS: Creating WebSocket connection to: ${wsUrl}`);
        
        const ws = new WebSocket(wsUrl);
        window.__kioskPlayerStatusWs = ws;
        
        ws.onopen = function(event) {
            const wsTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            wsReady = true;
            wsReconnectDelay = 1000; // Reset backoff on successful connection
            console.log(`[${wsTimestamp}] WS: WebSocket connected, wsReady = true`);
        };
        
        ws.onerror = function(event) {
            const wsTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.error(`[${wsTimestamp}] WS: WebSocket error:`, event);
        };

        ws.onclose = function() {
            const wsTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            wsReady = false;
            if (window.__kioskPlayerStatusWs === ws) {
                window.__kioskPlayerStatusWs = null;
            }
            console.log(`[${wsTimestamp}] WS: WebSocket closed, will reconnect in ${wsReconnectDelay}ms`);
            
            // Schedule reconnection with exponential backoff
            wsReconnectTimer = setTimeout(() => {
                wsReconnectDelay = Math.min(wsReconnectDelay * 2, maxReconnectDelay);
                connectWebSocket();
            }, wsReconnectDelay);
        };
        
        ws.onmessage = function(event) {
            const wsTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.log(`[${wsTimestamp}] WS: Message received. apiReady: ${apiReady}, wsReady: ${wsReady}`);
            
            const msg = JSON.parse(event.data);
            console.log(`[${wsTimestamp}] WS: Parsed message type: "${msg.type}"`);
            
            // Handle messages according to server spec
            if (msg && msg.type) {

                // Server spec: sends current_track, volume_changed, notification, ping
                if (msg.type === 'error') {
                    console.error(`[${wsTimestamp}] WS: Error message:`, msg.payload && msg.payload.message);
                    return;
                }
                if (msg.type === 'ping') {
                    // Server heartbeat - just log and ignore
                    console.log(`[${wsTimestamp}] WS: Received heartbeat ping from server`);
                    return;
                }
                if (msg.type === 'notification') {
                    // Handle notification event
                    const payload = msg.payload || {};
                    console.log(`[${wsTimestamp}] WS: Notification:`, payload);
                    showKioskToast('Notification: ' + (payload.message || ''), { theme: 'info' });
                    return;
                }

                if (msg.type === 'current_track' || msg.type === 'volume_changed') {
                    // Handle current_track and volume_changed    
                    const payload = msg.payload || {};
                    if (typeof window.updateKioskTrackInfo === 'function' && payload && typeof payload === 'object') {
                        console.log(`[${wsTimestamp}] WS: Applying update for event type "${msg.type}"`);
                        window.updateKioskTrackInfo(payload);
                    }
                }
                

            } else {
                console.warn(`[${wsTimestamp}] WS: Message structure unexpected:`, msg);
            }
        };
    }
    
    // Initial connection
    connectWebSocket();
    
    if (document.readyState === 'loading') {
        console.log(`[${initTimestamp}] INIT: document.readyState is "loading", waiting for DOMContentLoaded`);
        document.addEventListener('DOMContentLoaded', function() {
            const domTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
            console.log(`[${domTimestamp}] INIT: DOMContentLoaded fired, calling safeInit()`);
            safeInit();
        });
    } else {
        const readyTimestamp = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        console.log(`[${readyTimestamp}] INIT: document.readyState is "${document.readyState}", calling safeInit() immediately`);
        safeInit();
    }
})();
