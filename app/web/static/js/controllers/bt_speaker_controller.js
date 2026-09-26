import { Controller } from "@hotwired/stimulus"

// Connect/disconnect a BT-backed speaker's device from the device card.
// The card's click (switchDevice) is stopped so tapping the button does not
// also switch playback.
export default class extends Controller {
    static params = ["speakerName"]

    async toggle(event) {
        const name = event.params.speakerName
        console.info(`[bt] toggling connection for ${name} …`)
        try {
            const resp = await fetch("/kiosk/devices/bt-toggle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name })
            })
            const body = await resp.json()
            if (!resp.ok || body.error) {
                const message = body.detail || body.error || `toggle failed (${resp.status})`
                console.warn(`[bt] toggle failed for ${name}:`, message)
                window.showKioskToast(message, { theme: "error" })
                return
            }
            const state = body.connected ? "connected" : "disconnected"
            console.info(`[bt] ${name} → ${state}`)
            window.showKioskToast(`${name}: ${state}`, { theme: body.connected ? "success" : "info" })
            window.dispatchEvent(new CustomEvent("nav:go", { detail: "/kiosk/devices" }))
        } catch (e) {
            console.warn(`[bt] toggle failed for ${name}:`, e)
            window.showKioskToast(`BT toggle failed: ${e.message}`, { theme: "error" })
        }
    }
}