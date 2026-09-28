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
        if (!opening) {
            this._flushVolume()  // closing: deliver any pending level
        }
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
        // debounce: dragging fires one input event per step - the speaker
        // would be spammed with every intermediate value. Send once after
        // the drag settles (300ms); the readout stays live.
        clearTimeout(this._sendTimer)
        this._sendTimer = setTimeout(() => {
            this._sendTimer = null
            this._sendVolume(value)
        }, 300)
    }

    _sendVolume(value) {
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: "volume", payload: { value } }
        }))
    }

    _flushVolume() {
        if (this._sendTimer) {
            clearTimeout(this._sendTimer)
            this._sendTimer = null
            this._sendVolume(parseInt(this.sliderTarget.value) || 0)
        }
    }

    toggleMute() {
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: "volume_mute", payload: {} }
        }))
    }

    close(event) {
        if (!event || !this.element.contains(event.target)) {
            this._flushVolume()  // outside click: deliver any pending level
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
