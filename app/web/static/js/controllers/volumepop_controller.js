import { Controller } from "@hotwired/stimulus"

// Volume popover: replaces the vol+/vol- pair with a single button that
// opens a slider + mute flyout. Controls the SPEAKER's volume (cast
// device / BT sink) via WS — the phone's hardware volume does not.
export default class extends Controller {
    static targets = ["panel", "slider", "readout", "icon"]

    toggle(event) {
        if (event) event.stopPropagation()
        const panel = this.panelTarget
        const opening = panel.classList.contains("hidden")
        if (opening) {
            // initialise from the last known level (the nowplaying state)
            const current = parseInt(window.appState?.volume) || 0
            this.sliderTarget.value = current
            this.readoutTarget.textContent = `${current}%`
        }
        panel.classList.toggle("hidden")
        panel.classList.toggle("open")
    }

    setVolume(event) {
        const value = parseInt(event.target.value) || 0
        this.readoutTarget.textContent = `${value}%`
        this._iconFor(value)
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: "volume", payload: { value } }
        }))
    }

    toggleMute() {
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: "volume_mute", payload: {} }
        }))
    }

    close(event) {
        if (!event || !this.element.contains(event.target)) {
            this.panelTarget.classList.add("hidden")
        }
    }

    _iconFor(value) {
        if (!this.hasIconTarget) return
        const icon = value === 0 ? "mdi-volume-off"
            : value < 40 ? "mdi-volume-low"
            : value < 70 ? "mdi-volume-medium" : "mdi-volume-high"
        this.iconTarget.className = `mdi ${icon}`
    }
}
