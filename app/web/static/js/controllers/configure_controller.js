import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    static targets = ["raw"]
    static values = { clientId: String }

    connect() {
        // Delegated listeners: any structured field inside this component
        // merges into the raw JSON buffer as it changes.
        this.element.addEventListener("input", (event) => {
            if (event.target.matches("[data-config-path]")) this.fieldChanged(event)
        })
        this.element.addEventListener("change", (event) => {
            if (event.target.matches("[data-config-path]")) this.fieldChanged(event)
        })
    }

    fieldChanged() {
        let cfg
        try {
            cfg = JSON.parse(this.rawTarget.value)
        } catch (e) {
            // Invalid JSON in the Raw tab: skip the merge and flag the buffer
            // instead of alerting on every keystroke. Apply validates anyway.
            this.rawTarget.classList.add("is-invalid")
            return
        }
        this.rawTarget.classList.remove("is-invalid")

        this.element.querySelectorAll("[data-config-path]").forEach((el) => {
            let value = el.type === "checkbox" ? el.checked : el.value
            if (el.type === "number" && value !== "" && !isNaN(value)) value = Number(value)
            this.setPath(cfg, el.dataset.configPath, value)
        })

        this.rawTarget.value = JSON.stringify(cfg, null, 2)
    }

    async apply(event) {
        const reboot = String(event.params.reboot) === "true"
        if (reboot && !confirm("Reboot the device after applying?")) return

        const config = this.rawTarget.value
        try {
            JSON.parse(config)
        } catch (e) {
            this.rawTarget.classList.add("is-invalid")
            window.showKioskToast(`Invalid JSON: ${e.message}`, { theme: "error" })
            return
        }

        try {
            const resp = await fetch(`/kiosk/configure/${this.clientIdValue}/apply${reboot ? "?reboot=true" : ""}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: config
            })
            if (!resp.ok) {
                window.showKioskToast(`Apply failed: ${await resp.text()}`, { theme: "error" })
                return
            }
            window.showKioskToast(reboot ? "Config sent — device rebooting" : "Config sent", { theme: "success" })
            window.dispatchEvent(new CustomEvent("nav:go", { detail: "/kiosk/clients" }))
        } catch (e) {
            window.showKioskToast(`Apply failed: ${e.message}`, { theme: "error" })
        }
    }

    setPath(obj, path, value) {
        const keys = path.split(".")
        let cur = obj
        for (let i = 0; i < keys.length - 1; i++) {
            if (typeof cur[keys[i]] !== "object" || cur[keys[i]] === null) cur[keys[i]] = {}
            cur = cur[keys[i]]
        }
        cur[keys[keys.length - 1]] = value
    }
}