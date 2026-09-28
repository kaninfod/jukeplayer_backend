import { Controller } from "@hotwired/stimulus"

// The ≡ menu sheet (mobile): a full-screen slide-over carrying the
// speaker quick-select and the content links. System pages stay
// desktop-kiosk surfaces (first mobile slice).
export default class extends Controller {
    static targets = ["panel", "body"]
    static params = ["speaker"]

    async open(event) {
        if (event) event.stopPropagation()
        try {
            const resp = await fetch("/kiosk/menu-sheet", { headers: { "HX-Request": "true" } })
            const html = await resp.text()
            this.bodyTarget.innerHTML = html
            if (window.htmx) window.htmx.process(this.bodyTarget)
            this.panelTarget.classList.remove("hidden")
        } catch (e) {
            console.warn("[menu-sheet] open failed:", e)
        }
    }

    close() {
        this.panelTarget.classList.add("hidden")
    }

    switch(event) {
        const speaker = event.params.speaker
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: { type: "switch_device", payload: { device_id: speaker } }
        }))
        window.showKioskToast(`Playback → ${speaker}`, { theme: "success" })
        this.close()
    }

    navigate(event) {
        if (event && typeof event.preventDefault === "function") event.preventDefault()
        const url = event.currentTarget.getAttribute("href")
        this.close()
        window.dispatchEvent(new CustomEvent("nav:go", { detail: url }))
    }
}
