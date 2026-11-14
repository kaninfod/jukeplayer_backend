import { Controller } from "@hotwired/stimulus"

const THEME_CLASSES = {
    info: "bg-info text-white",
    success: "bg-success text-white",
    warning: "bg-warning text-dark",
    error: "bg-danger text-white"
}

// Owns the global toast container. Controllers emit `app:toast` on their own
// element; htmx emits `kioskToast` from HX-Trigger responses. Both bubble to
// the body controller.
export default class extends Controller {
    static targets = ["container"]

    connect() {
        this._onToast = this.show.bind(this)
        this.element.addEventListener("app:toast", this._onToast)
        this.element.addEventListener("kioskToast", this._onToast)
    }

    disconnect() {
        this.element.removeEventListener("app:toast", this._onToast)
        this.element.removeEventListener("kioskToast", this._onToast)
    }

    show(event) {
        const detail = event.detail || {}
        const message = detail.message || String(detail.value || "")
        const theme = detail.theme || "info"
        const timeout = detail.timeout ?? 3000

        if (!message || !this.hasContainerTarget) return
        if (!window.bootstrap?.Toast) {
            console.warn("[toast] Bootstrap Toast is not available")
            return
        }

        const toast = document.createElement("div")
        toast.className = `toast kiosk-toast align-items-center ${THEME_CLASSES[theme] || THEME_CLASSES.info}`
        toast.setAttribute("role", "alert")
        toast.setAttribute("aria-live", "assertive")
        toast.setAttribute("aria-atomic", "true")

        const row = document.createElement("div")
        row.className = "d-flex"

        const body = document.createElement("div")
        body.className = "toast-body"
        body.textContent = message

        const close = document.createElement("button")
        close.type = "button"
        close.className = "btn-close btn-close-white me-2 m-auto"
        close.dataset.bsDismiss = "toast"
        close.setAttribute("aria-label", "Close")

        row.append(body, close)
        toast.append(row)
        this.containerTarget.append(toast)

        const instance = new window.bootstrap.Toast(toast, { delay: timeout })
        toast.addEventListener("hidden.bs.toast", () => toast.remove())
        instance.show()
    }
}
