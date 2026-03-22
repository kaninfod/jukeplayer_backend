/**
 * Kiosk NFC Encoding Component
 * Handles NFC card encoding with polling status updates
 */

(function() {
    let pollInterval = null;
    let currentAlbumId = null;
    let currentAlbumName = null;
    let currentClientId = null;
    let encodingComplete = false;
    let initialized = false;
    
    // Expose initNfcEncoding globally so kiosk loader can call it
    window.initNfcEncoding = async function(albumId, albumName, clientId) {
        console.log('[NFC] Initializing encoding component for album:', albumName, '(id:', albumId, ') on client:', clientId);
        
        currentAlbumId = albumId;
        currentAlbumName = albumName;
        currentClientId = clientId;
        encodingComplete = false;
        
        // Update UI with album name
        const albumNameDiv = document.getElementById('nfc-album-name');
        if (albumNameDiv) {
            albumNameDiv.innerHTML = `Album: <strong>${escapeHtml(albumName)}</strong>`;
        }
        
        // Show waiting state, show cancel button
        showState('waiting');
        document.getElementById('nfc-cancel-btn').style.display = 'inline-block';
        document.getElementById('nfc-return-btn').style.display = 'none';
        
        // Start encoding session on backend
        try {
            const payload = { album_id: currentAlbumId };
            if (currentClientId) {
                payload.client_id = currentClientId;
            }
            
            const startResponse = await fetch('/api/nfc-encoding/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            if (!startResponse.ok) {
                let errorMessage = `Failed to start encoding session (${startResponse.status})`;
                try {
                    const errorData = await startResponse.json();
                    if (errorData.detail) {
                        errorMessage = errorData.detail;
                    }
                } catch(e) {
                    // Ignore JSON parse errors, use default message
                }
                console.error('[NFC] Failed to start encoding session:', errorMessage);
                showFailureState(errorMessage);
                return;
            }
            
            console.log('[NFC] Encoding session started successfully');
        } catch (error) {
            console.error('[NFC] Error starting encoding:', error);
            showFailureState('Error: ' + error.message);
            return;
        }
        
        // Start polling for status
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(pollStatus, 3000);
        
        // Poll immediately on init
        pollStatus();
    };
    
    async function pollStatus() {
        if (encodingComplete) {
            console.log('[NFC] Encoding already complete, stopping poll');
            return;
        }
        
        try {
            const response = await fetch('/api/nfc-encoding/status');
            if (!response.ok) {
                console.error('[NFC] Status request failed:', response.status);
                return;
            }
            
            const data = await response.json();
            console.log('[NFC] Status update:', data);
            
            // Check if encoding is still active
            if (data.encoding_mode) {
                console.log('[NFC] Still encoding, showing encoding state');
                showState('encoding');
            } else {
                // Encoding session ended
                if (pollInterval) clearInterval(pollInterval);
                encodingComplete = true;
                
                // Check result
                if (data.success && data.last_uid) {
                    console.log('[NFC] ✅ Encoding successful! UID:', data.last_uid);
                    showSuccessState(data.last_uid);
                } else {
                    console.warn('[NFC] ❌ Encoding failed or cancelled');
                    showFailureState('Encoding did not complete successfully');
                }
            }
        } catch (error) {
            console.error('[NFC] Error polling status:', error);
        }
    }
    
    function showState(state) {
        // Hide all states
        document.getElementById('nfc-waiting').style.display = 'none';
        document.getElementById('nfc-encoding').style.display = 'none';
        document.getElementById('nfc-success').style.display = 'none';
        document.getElementById('nfc-failure').style.display = 'none';
        document.getElementById('nfc-cancelled').style.display = 'none';
        
        // Show requested state
        switch(state) {
            case 'waiting':
                document.getElementById('nfc-waiting').style.display = 'block';
                break;
            case 'encoding':
                document.getElementById('nfc-encoding').style.display = 'block';
                break;
            case 'success':
                document.getElementById('nfc-success').style.display = 'block';
                break;
            case 'failure':
                document.getElementById('nfc-failure').style.display = 'block';
                break;
            case 'cancelled':
                document.getElementById('nfc-cancelled').style.display = 'block';
                break;
        }
    }
    
    function showSuccessState(uid) {
        showState('success');
        const uidElement = document.getElementById('nfc-encoded-uid');
        if (uidElement) {
            uidElement.innerHTML = `UID: <code>${escapeHtml(uid)}</code>`;
        }
        
        // Show return button, hide cancel button
        document.getElementById('nfc-cancel-btn').style.display = 'none';
        document.getElementById('nfc-return-btn').style.display = 'inline-block';
    }
    
    function showFailureState(errorMessage) {
        showState('failure');
        const errorElement = document.getElementById('nfc-error-message');
        if (errorElement) {
            errorElement.textContent = errorMessage || 'Unknown error occurred';
        }
        
        // Show return button, hide cancel button
        document.getElementById('nfc-cancel-btn').style.display = 'none';
        document.getElementById('nfc-return-btn').style.display = 'inline-block';
    }
    
    function showCancelledState() {
        showState('cancelled');
        
        // Show return button, hide cancel button
        document.getElementById('nfc-cancel-btn').style.display = 'none';
        document.getElementById('nfc-return-btn').style.display = 'inline-block';
    }
    
    // Global function to cancel encoding
    window.cancelNfcEncoding = async function() {
        console.log('[NFC] Cancelling encoding session');
        
        if (pollInterval) clearInterval(pollInterval);
        encodingComplete = true;
        
        try {
            const response = await fetch('/api/nfc-encoding/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                console.log('[NFC] Encoding session stopped');
                showCancelledState();
            } else {
                console.error('[NFC] Failed to stop encoding session:', response.status);
                showFailureState('Failed to stop encoding session');
            }
        } catch (error) {
            console.error('[NFC] Error cancelling encoding:', error);
            showFailureState('Error: ' + error.message);
        }
    };
    
    // Helper function to escape HTML
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Auto-initialize when component loads (only if required DOM elements exist)
    function safeInit() {
        const container = document.getElementById('nfc-encoding-container');
        if (container && !initialized) {
            const albumId = container.dataset?.albumId;
            const albumName = container.dataset?.albumName;
            if (albumId && albumName) {
                initialized = true;
                window.initNfcEncoding(albumId, albumName);
            } else {
                console.log('[NFC] Component DOM ready, waiting for initNfcEncoding() call');
            }
        }
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', safeInit);
    } else {
        safeInit();
    }
})();
