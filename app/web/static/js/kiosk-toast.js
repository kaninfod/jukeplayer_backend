// Kiosk Toast Utility - Unified notification system for kiosk app
(function() {
    const themeMap = {
        info: 'bg-info text-white',
        success: 'bg-success text-white',
        warning: 'bg-warning text-dark',
        error: 'bg-danger text-white'
    };

    window.showKioskToast = function(message, { timeout = 3000, theme = 'info' } = {}) {
        const container = document.getElementById('kiosk-toast-container');
        if (!container) return;

        // Create toast element
        const toast = document.createElement('div');
        toast.className = `toast kiosk-toast align-items-center ${themeMap[theme] || themeMap.info}`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.style.minWidth = '220px';
        toast.style.maxWidth = '320px';
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

        container.appendChild(toast);

        // Initialize and show toast (Bootstrap 5)
        const bsToast = new bootstrap.Toast(toast, { delay: timeout });
        bsToast.show();

        // Remove toast from DOM after hidden
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    };
})();
