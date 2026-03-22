/**
 * Kiosk NFC Client Selection Component
 * Loads available NFC clients and handles selection
 */

(function() {
    let currentAlbumId = null;
    let currentAlbumName = null;
    let clients = [];
    
    // Helper to escape HTML and prevent XSS
    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    // Expose initNfcClientSelect globally so kiosk loader can call it
    window.initNfcClientSelect = async function(albumId, albumName) {
        console.log('[NFC-SELECT] Initializing client selection for album:', albumName, '(id:', albumId, ')');
        
        currentAlbumId = albumId;
        currentAlbumName = albumName;
        
        // Update UI with album name
        const albumNameDiv = document.getElementById('nfc-album-name');
        if (albumNameDiv) {
            albumNameDiv.innerHTML = `Album: <strong>${escapeHtml(albumName)}</strong>`;
        }
        
        // Load available NFC clients
        await loadNfcClients();
    };
    
    async function loadNfcClients() {
        try {
            console.log('[NFC-SELECT] Fetching NFC clients...');
            const response = await fetch('/api/system/clients/by-capability/nfc_reader', {
                headers: {
                    'X-API-Key': window.API_KEY || ''
                }
            });
            
            if (!response.ok) {
                console.error('[NFC-SELECT] Failed to fetch clients:', response.status);
                showErrorState('Failed to load available NFC clients');
                return;
            }
            
            const data = await response.json();
            // API returns {count, clients: [...]}
            clients = data.clients || data || [];
            console.log('[NFC-SELECT] Loaded clients:', clients);
            
            if (!clients || clients.length === 0) {
                showErrorState('No NFC-capable clients are currently connected');
                return;
            }
            
            renderClientCards(clients);
            
        } catch (error) {
            console.error('[NFC-SELECT] Error loading clients:', error);
            showErrorState('Error loading NFC clients: ' + error.message);
        }
    }
    
    function renderClientCards(clientList) {
        const clientsDiv = document.getElementById('nfc-clients-list');
        if (!clientsDiv) return;
        
        clientsDiv.innerHTML = '';
        
        clientList.forEach(client => {
            const card = document.createElement('div');
            card.className = 'nfc-client-card';
            card.onclick = function() {
                selectClient(client);
            };
            
            // Choose icon based on client type
            let iconClass = 'mdi-nfc-variant';
            if (client.client_type === 'esp32') {
                iconClass = 'mdi-chip';
            } else if (client.client_type === 'rpi') {
                iconClass = 'mdi-raspberry-pi';
            }
            
            card.innerHTML = `
                <div class="nfc-client-icon">
                    <i class="mdi ${iconClass}"></i>
                </div>
                <div class="nfc-client-info">
                    <p class="nfc-client-name">${escapeHtml(client.user_name || client.client_id)}</p>
                    <p class="nfc-client-type">${escapeHtml(client.client_type)} • Connected</p>
                </div>
            `;
            
            clientsDiv.appendChild(card);
        });
    }
    
    function selectClient(client) {
        console.log('[NFC-SELECT] Selected client:', client.client_id, client.user_name);
        
        // Build URL to encoding screen with album_id, album_name, and client_id
        const params = new URLSearchParams({
            album_id: currentAlbumId,
            album_name: currentAlbumName,
            client_id: client.client_id
        });
        
        // Navigate to encoding screen
        return window.kioskNavigate(`/kiosk/nfc?${params.toString()}`, true);
    }
    
    function showErrorState(message) {
        const errorDiv = document.getElementById('nfc-error-state');
        const messageDiv = document.getElementById('nfc-error-message');
        const listDiv = document.getElementById('nfc-clients-list');
        
        if (errorDiv && listDiv && messageDiv) {
            listDiv.style.display = 'none';
            errorDiv.style.display = 'flex';
            messageDiv.textContent = message;
        }
    }
    
    // Helper function to escape HTML entities
    window.escapeHtml = function(unsafe) {
        if (!unsafe) return '';
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    };
})();
