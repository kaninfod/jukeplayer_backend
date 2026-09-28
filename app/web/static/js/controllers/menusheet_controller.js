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
            this.panelTarget.classList.add("open")
        } catch (e) {
            console.warn("[menu-sheet] open failed:", e)
        }
    }

    close() {
        this.panelTarget.classList.remove("open")
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

    playlist(event) {
        // the playlist view needs the client id injected (same as the
        // navigation controller's injectClientId pattern)
        if (event && typeof event.preventDefault === "function") event.preventDefault()
        const raw = event.currentTarget.getAttribute("data-navigation-url-value") || "/kiosk/playlist"
        this.close()
        const url = new URL(raw, window.location.origin)
        const clientId = localStorage.getItem("clientId")
        if (clientId) url.searchParams.append("injected_client_id", clientId)
        window.dispatchEvent(new CustomEvent("nav:go", { detail: url.pathname + url.search }))
    }
}
