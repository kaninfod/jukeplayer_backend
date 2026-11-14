import { Controller } from "@hotwired/stimulus"

// Owns the body.page-loading class for the single kiosk busy overlay.
// Controllers emit `app:busy` with { on: true|false }.
export default class extends Controller {
    connect() {
        this._onBusy = this.set.bind(this)
        this.element.addEventListener("app:busy", this._onBusy)
    }

    disconnect() {
        this.element.removeEventListener("app:busy", this._onBusy)
    }

    set(event) {
        const on = Boolean(event.detail?.on)
        this.element.classList.toggle("page-loading", on)
    }
}
