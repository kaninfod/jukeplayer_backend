window.kioskInitializeContent = function() {
    try {
        const hasPlayer = !!document.getElementById('kiosk-track-info');
        if (hasPlayer && typeof window.initPlayerStatus === 'function') {
            window.initPlayerStatus();
        }

        const hasNfcClientSelect = !!document.getElementById('nfc-client-select-container');
        if (hasNfcClientSelect && typeof window.initNfcClientSelect === 'function') {
            const container = document.getElementById('nfc-client-select-container');
            const albumId = container?.dataset?.albumId;
            const albumName = container?.dataset?.albumName;
            if (albumId && albumName) {
                window.initNfcClientSelect(albumId, albumName);
            }
        }

        const hasNfc = !!document.getElementById('nfc-encoding-container');
        if (hasNfc && typeof window.initNfcEncoding === 'function') {
            const container = document.getElementById('nfc-encoding-container');
            const albumId = container?.dataset?.albumId;
            const albumName = container?.dataset?.albumName;
            const clientId = container?.dataset?.clientId;
            if (albumId && albumName) {
                window.initNfcEncoding(albumId, albumName, clientId);
            }
        }

        const hasSystem = !!document.getElementById('system-status');
        if (hasSystem && typeof window.initSystemMenu === 'function') {
            window.initSystemMenu();
        }
    } catch (error) {
        console.error('kioskInitializeContent error:', error);
    }
};

// Fallback helpers when HTMX is unavailable (e.g. CDN unreachable)
window.kioskLoadContent = async function(url, pushUrl = true) {
    const contentArea = document.getElementById('kiosk-content-area');
    if (!contentArea) return;
    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'HX-Request': 'true',
                'HX-Target': 'kiosk-content-area'
            }
        });
        if (!response.ok) throw new Error(`Failed to load content: ${response.status}`);
        const html = await response.text();
        contentArea.innerHTML = html;
        window.kioskInitializeContent(contentArea);
        if (pushUrl && window.history && window.history.pushState) {
            window.history.pushState({ kiosk: true }, '', url);
        }
    } catch (error) {
        console.error('kioskLoadContent error:', error);
        showKioskToast('Failed to load content', { theme: 'error' });
    }
};

window.kioskPostContent = async function(url, body = null, pushUrl = false) {
    const contentArea = document.getElementById('kiosk-content-area');
    if (!contentArea) return;
    try {
        const options = {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'HX-Request': 'true',
                'HX-Target': 'kiosk-content-area'
            }
        };
        if (body !== null) {
            options.body = JSON.stringify(body);
        }
        const response = await fetch(url, options);
        if (!response.ok) throw new Error(`Failed to post content: ${response.status}`);
        const html = await response.text();
        contentArea.innerHTML = html;
        window.kioskInitializeContent(contentArea);
        if (pushUrl && window.history && window.history.pushState) {
            window.history.pushState({ kiosk: true }, '', url);
        }
    } catch (error) {
        console.error('kioskPostContent error:', error);
        showKioskToast('Failed to update content', { theme: 'error' });
    }
};

window.kioskNavigate = async function(url, pushUrl = true) {
    return window.kioskLoadContent(url, pushUrl);
};

window.kioskOpenLibrary = function() {
    return window.kioskNavigate('/kiosk/library', true);
};

window.kioskOpenPlayer = function() {
    return window.kioskNavigate('/kiosk/player', true);
};

window.kioskOpenDevices = function() {
    return window.kioskNavigate('/kiosk/devices', true);
};

window.kioskOpenPlaylist = function() {
    return window.kioskNavigate('/kiosk/playlist', true);
};

window.kioskOpenSystem = function() {
    return window.kioskNavigate('/kiosk/system', true);
};

window.kioskOpenLibraryGroup = function(groupName) {
    return window.kioskNavigate(`/kiosk/library?group=${encodeURIComponent(groupName)}`, true);
};

window.kioskOpenLibraryArtist = function(artistId, artistName, groupName) {
    const params = new URLSearchParams({ artist_id: artistId, artist_name: artistName });
    if (groupName) {
        params.set('group', groupName);
    }
    return window.kioskNavigate(`/kiosk/library?${params.toString()}`, true);
};

window.kioskPlayAlbum = async function(albumId) {
    if (!albumId) {
        showKioskToast('Missing album id', { theme: 'error' });
        return;
    }
    await window.kioskPostContent(`/kiosk/library/play/${encodeURIComponent(albumId)}`, null, false);
};

window.kioskPlayTrackAtIndex = async function(trackIndex) {
    if (trackIndex === undefined || trackIndex === null || Number.isNaN(Number(trackIndex))) {
        showKioskToast('Invalid track selection', { theme: 'error' });
        return;
    }

    const index = Number(trackIndex);
    try {
        const response = await apiFetch('/api/mediaplayer/play_track', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ track_index: index })
        });

        if (!response.ok) {
            throw new Error(`Failed to play track: ${response.status}`);
        }

        const payload = await response.json();
        if (payload && payload.status === 'error') {
            throw new Error(payload.message || 'Failed to play selected track');
        }

        if (typeof window.refreshKioskStatus === 'function') {
            window.refreshKioskStatus();
        }

        if (document.getElementById('kiosk-playlist-container')) {
            window.kioskLoadContent('/kiosk/playlist', false);
        }
    } catch (error) {
        console.error('kioskPlayTrackAtIndex error:', error);
        showKioskToast('Failed to play selected track', { theme: 'error' });
    }
};

window.kioskOpenNfcEncoding = function(albumId, albumName) {
    if (!albumId || !albumName) {
        showKioskToast('Missing NFC album data', { theme: 'error' });
        return;
    }
    const params = new URLSearchParams({ album_id: albumId, album_name: albumName });
    return window.kioskNavigate(`/kiosk/nfc?${params.toString()}`, true);
};

window.kioskOpenNfcClientSelect = function(albumId, albumName) {
    if (!albumId || !albumName) {
        showKioskToast('Missing NFC album data', { theme: 'error' });
        return;
    }
    const params = new URLSearchParams({ album_id: albumId, album_name: albumName });
    return window.kioskNavigate(`/kiosk/nfc-client-select?${params.toString()}`, true);
};

document.addEventListener('htmx:afterSwap', function(event) {
    const target = event?.detail?.target;
    if (target && target.id === 'kiosk-content-area') {
        window.kioskInitializeContent();
    }
});

document.addEventListener('DOMContentLoaded', () => {
    if (document.body.classList.contains('kiosk-layout')) {
        window.kioskInitializeContent();
    }
});
