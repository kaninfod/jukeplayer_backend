import { Controller } from "@hotwired/stimulus"

// Volume popover: replaces the vol+/vol- pair with a single button that
// opens a slider + mute flyout. Controls the SPEAKER's volume (cast
// device / BT sink) via WS — the phone's hardware volume does not.
export default class extends Controller {
    static targets = ["panel", "slider", "readout", "icon", "buttonreadout", "buttonmuteicon"]

    connect() {
        this._onVolumeState = () => this._renderButton()
        window.addEventListener("nowplaying-update", this._onVolumeState)
        window.addEventListener("volume-change", this._onVolumeState)
        window.addEventListener("volume_mute_response", this._onVolumeState)
        this._renderButton()
    }

    disconnect() {
        window.removeEventListener("nowplaying-update", this._onVolumeState)
        window.removeEventListener("volume-change", this._onVolumeState)
        window.removeEventListener("volume_mute_response", this._onVolumeState)
    }

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
        this._renderButton(value)
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

    volumeUp() { this._step(5) }

    volumeDown() { this._step(-5) }

    _step(delta) {
        // optimistic ±5; the server's volume_changed broadcast corrects it
        const value = Math.min(100, Math.max(0, (parseInt(this.sliderTarget.value) || 0) + delta))
        this.sliderTarget.value = value
        this.readoutTarget.textContent = `${value}%`
        this._renderButton(value)
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: delta > 0 ? "volume_up" : "volume_down", payload: {} }
        }))
    }

    // keyboard ESC route: same cleanup as an outside click, no event knowledge
    forceClose() {
        if (!this.hasPanelTarget) return
        this._flushVolume()
        this.panelTarget.classList.add("hidden")
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

    _renderButton(volumeOverride = null) {
        const forced = typeof volumeOverride === "number" ? volumeOverride : null
        const volume = forced ?? (parseInt(window.appState?.volume) || 0)
        const muted = Boolean(window.appState?.isMuted)

        if (this.hasButtonreadoutTarget) {
            this.buttonreadoutTarget.textContent = `${volume}%`
            this.buttonreadoutTarget.classList.toggle("d-none", muted)
        }
        if (this.hasButtonmuteiconTarget) {
            this.buttonmuteiconTarget.classList.toggle("d-none", !muted)
        }
        if (this.hasIconTarget) {
            if (muted) this.iconTarget.className = "mdi mdi-volume-off"
            else this._iconFor(volume)
        }
    }
}
