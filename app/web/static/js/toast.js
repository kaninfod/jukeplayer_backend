/**
 * Toast Notification System
 * Reusable toast notifications with Bootstrap styling
 * Supports stacking, auto-dismiss, and custom durations
 */

class ToastManager {
    constructor() {
        this.toastContainer = null;
        this.init();
    }

    /**
     * Initialize the toast container if it doesn't exist
     */
    init() {
        if (!this.toastContainer) {
            this.toastContainer = document.createElement('div');
            this.toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            this.toastContainer.style.zIndex = '9999';
            document.body.appendChild(this.toastContainer);
        }
    }

    /**
     * Show a toast notification
     * @param {string} message - The message to display
     * @param {string} type - Toast type: 'success', 'error', 'warning', 'info' (default: 'info')
     * @param {number} duration - Auto-dismiss duration in milliseconds (default: 5000, 0 = no auto-dismiss)
     * @param {string} title - Optional title for the toast
     */
    show(message, type = 'info', duration = 5000, title = '') {
        this.init();

        const toastId = 'toast-' + Date.now() + Math.random().toString(36).substr(2, 9);
        
        // Determine colors based on type
        const colorMap = {
            success: { bg: 'bg-success', text: 'text-white' },
            error: { bg: 'bg-danger', text: 'text-white' },
            warning: { bg: 'bg-warning', text: 'text-dark' },
            info: { bg: 'bg-info', text: 'text-white' }
        };

        const colors = colorMap[type] || colorMap['info'];

        // Set default titles if not provided
        const titleMap = {
            success: 'Success',
            error: 'Error',
            warning: 'Warning',
            info: 'Information'
        };

        const finalTitle = title || titleMap[type];

        // Create toast element
        const toastHTML = `
            <div id="${toastId}" class="toast ${colors.bg} ${colors.text} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header ${colors.bg} ${colors.text} border-0">
                    <strong class="me-auto">${finalTitle}</strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;

        this.toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        const toastElement = document.getElementById(toastId);
        
        // Initialize Bootstrap toast
        const bsToast = new bootstrap.Toast(toastElement, {
            autohide: duration > 0,
            delay: duration
        });

        bsToast.show();

        // Remove element from DOM after it's hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    }

    /**
     * Show success toast
     */
    success(message, title = 'Success', duration = 5000) {
        this.show(message, 'success', duration, title);
    }

    /**
     * Show error toast
     */
    error(message, title = 'Error', duration = 5000) {
        this.show(message, 'error', duration, title);
    }

    /**
     * Show warning toast
     */
    warning(message, title = 'Warning', duration = 5000) {
        this.show(message, 'warning', duration, title);
    }

    /**
     * Show info toast
     */
    info(message, title = 'Information', duration = 5000) {
        this.show(message, 'info', duration, title);
    }
}

// Create global instance
const toast = new ToastManager();
