/**
 * Kiosk System Menu Component
 * System controls: Exit kiosk, restart app, reboot, shutdown
 */

(function() {
    window.initSystemMenu = function() {
        // System menu initialized
    };
    
    window.exitKiosk = function() {
        window.location.href = '/status';
    };
    
    window.restartApp = async function() {
        if (!confirm('Restart the jukebox application?\n\nThe app will reload automatically.')) {
            return;
        }
        
        showStatus('Restarting application...', 'info');
        
        try {
            const response = await fetch('/api/system/restart', {
                method: 'POST'
            });
            
            if (response.ok) {
                showStatus('Application restarting... Please wait.', 'success');
                setTimeout(() => {
                    window.location.reload();
                }, 3000);
            } else {
                showStatus('Failed to restart application', 'danger');
            }
        } catch (error) {
            console.error('Error restarting app:', error);
            showStatus('Error: ' + error.message, 'danger');
        }
    };
    
    window.rebootSystem = async function() {
        if (!confirm('Reboot the Raspberry Pi?\n\nThis will restart the entire device.')) {
            return;
        }
        
        showStatus('Rebooting system...', 'warning');
        
        try {
            const response = await fetch('/api/system/reboot', {
                method: 'POST'
            });
            
            if (response.ok) {
                showStatus('System rebooting... This will take a minute.', 'success');
            } else {
                showStatus('Failed to reboot system', 'danger');
            }
        } catch (error) {
            console.error('Error rebooting system:', error);
            showStatus('Error: ' + error.message, 'danger');
        }
    };
    
    window.shutdownSystem = async function() {
        if (!confirm('Shutdown the Raspberry Pi?\n\nThis will power off the device. You will need to manually restart it.')) {
            return;
        }
        
        showStatus('Shutting down system...', 'danger');
        
        try {
            const response = await fetch('/api/system/shutdown', {
                method: 'POST'
            });
            
            if (response.ok) {
                showStatus('System shutting down... Goodbye!', 'success');
            } else {
                showStatus('Failed to shutdown system', 'danger');
            }
        } catch (error) {
            console.error('Error shutting down:', error);
            showStatus('Error: ' + error.message, 'danger');
        }
    };
    
    function showStatus(message, type) {
        const statusDiv = document.getElementById('system-status');
        statusDiv.innerHTML = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
    }
    
    // Auto-initialize when component loads (only if required DOM elements exist)
    function safeInit() {
        if (document.getElementById('system-status')) {
            window.initSystemMenu();
        }
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', safeInit);
    } else {
        safeInit();
    }
})();
