import { Controller } from "@hotwired/stimulus"

// sound profile dialog: one per speakers card; a row's EQ button carries
// the speaker name + the CURRENT profile (json value) and this controller
// fills + opens the shared <dialog>, retargets the form's hx-post, and
// closes it after a successful htmx apply (the toast is server-driven).
export default class extends Controller {
    static targets = ["dialog", "form", "title", "preamp"]
    static values = { name: String, label: String, profile: Object }

    open(event) {
        const button = event.currentTarget
        this.name = button.dataset.soundprofileNameParam
        const label = button.dataset.soundprofileLabelParam || this.name
        this.titleTarget.textContent = label
        const profile = JSON.parse(button.dataset.soundprofileProfileValue || "{}")
        this._fill(profile)
        this.formTarget.setAttribute("hx-post",
            `/kiosk/config/speakers/${this.name}/sound-profile`)
        this.dialogTarget.showModal()
    }

    _fill(profile) {
        const preampDb = profile.preamp_db ?? ""
        this.preampTarget.value = preampDb === null ? "" : preampDb
        const bands = profile.bands_db || {}
        this.formTarget.querySelectorAll('input[name^="band_"]').forEach(input => {
            const band = input.name.replace("band_", "")
            const v = bands[band] ?? ""
            input.value = v === null ? "" : v
        })
        this.formTarget.querySelector('input[name="low_shelf_db"]').value = profile.low_shelf_db ?? ""
        this.formTarget.querySelector('input[name="high_shelf_db"]').value = profile.high_shelf_db ?? ""
    }

    cancel() {
        this.dialogTarget.close()
    }

    connect() {
        // close after a successful apply — the toast is already dispatched
        this._after = (event) => {
            if (event.target === this.formTarget && event.detail.successful) {
                this.dialogTarget.close()
            }
        }
        document.body.addEventListener("htmx:afterRequest", this._after)
    }

    disconnect() {
        document.body.removeEventListener("htmx:afterRequest", this._after)
    }
}