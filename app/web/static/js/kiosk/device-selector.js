/**
 * Kiosk Device Selector Component
 * Displays available output devices (Bluetooth/MPV + Chromecast) and allows switching
 */

// Device selector JS: Only switching logic remains; device list is now server-rendered

window.selectOutputDevice = async function(backend, deviceName, label) {
    const targetLabel = label || deviceName || backend;
    showKioskToast('Switching to ' + targetLabel + '...', { theme: 'info' });
    try {
        const payload = { backend: backend };
        if (deviceName) {
            payload.device_name = deviceName;
            payload.backend = backend;
        }

        const response = await fetch('/api/output/switch', {
            method: 'POST',
            headers: {
                'accept': 'application/json',
                'content-type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            const result = await response.json();
            if (result.status === 'ok') {
                showKioskToast('Switched to ' + targetLabel, { theme: 'success' });
            } else {
                const errMsg = result.message || result.error || 'Unknown error';
                showKioskToast('Failed to switch output: ' + errMsg, { theme: 'error' });
            }
            // Always route back inside kiosk content area (avoid full-page navigation)
            if (typeof window.kioskLoadContent === 'function') {
                window.kioskLoadContent('/kiosk/player', true);
            } else if (window.htmx) {
                window.htmx.ajax('GET', '/kiosk/player', { target: '#kiosk-content-area', swap: 'innerHTML' });
            } else if (typeof window.kioskOpenPlayer === 'function') {
                window.kioskOpenPlayer();
            }
        } else {
            // Try to parse error body
            let errMsg = 'Unknown error';
            try {
                const error = await response.json();
                errMsg = error.detail || error.message || errMsg;
            } catch (e) {}
            showKioskToast('Failed to switch output: ' + errMsg, { theme: 'error' });
        }
    } catch (error) {
        console.error('Error selecting output:', error);
        showKioskToast('Error: ' + error.message, { theme: 'error' });
    }
};

// Backward-compatible wrapper used by older templates/callers
window.selectChromecastDevice = async function(deviceName) {
    return window.selectOutputDevice('chromecast', deviceName, deviceName);
};
