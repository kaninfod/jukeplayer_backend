import { Controller } from "@hotwired/stimulus"

// Connect/disconnect a BT-backed speaker's device from the device card.
// The card's click (switchDevice) is stopped so tapping the button does not
// also switch playback.
export default class extends Controller {
    static params = ["speakerName"]

    toast(message, theme = "info") {
        this.dispatch("toast", { prefix: "app", detail: { message, theme } })
    }

    busy(on) {
        this.dispatch("busy", { prefix: "app", detail: { on } })
    }

    async toggle(event) {
        const name = event.params.speakerName
        console.info(`[bt] toggling connection for ${name} …`)
        try {
            this.busy(true)
            const resp = await fetch("/kiosk/devices/bt-toggle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name })
            })
            const body = await resp.json()
            if (!resp.ok || body.error) {
                const message = body.detail || body.error || `toggle failed (${resp.status})`
                console.warn(`[bt] toggle failed for ${name}:`, message)
                this.toast(message, "error")
                return
            }
            const state = body.connected ? "connected" : "disconnected"
            console.info(`[bt] ${name} → ${state}`)
            this.toast(`${name}: ${state}`, body.connected ? "success" : "info")
            window.dispatchEvent(new CustomEvent("nav:go", { detail: "/kiosk/devices" }))
        } catch (e) {
            console.warn(`[bt] toggle failed for ${name}:`, e)
            this.toast(`BT toggle failed: ${e.message}`, "error")
        } finally {
            this.busy(false)
        }
    }
}