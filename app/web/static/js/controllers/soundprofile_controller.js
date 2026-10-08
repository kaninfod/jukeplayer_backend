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
        this._button = button                      // remember: refresh its stored profile on success
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
        // close after a successful apply — and write the applied values back
        // to the row button's stored profile so a reopen prefills the truth
        // (the card is intentionally not re-rendered on apply)
        this._after = (event) => {
            if (event.target === this.formTarget && event.detail.successful && this._button) {
                this._button.dataset.soundprofileProfileValue = JSON.stringify(this._collect())
                this.dialogTarget.close()
            }
        }
        document.body.addEventListener("htmx:afterRequest", this._after)
    }

    _collect() {
        const value = (name) => {
            const raw = this.formTarget.querySelector(`input[name="${name}"]`).value.trim()
            return raw === "" ? null : raw
        }
        const bands = {}
        this.formTarget.querySelectorAll('input[name^="band_"]').forEach(input => {
            const raw = input.value.trim()
            if (raw !== "") bands[input.name.replace("band_", "")] = raw
        })
        return {
            preamp_db: value("preamp_db"),
            bands_db: bands,
            low_shelf_db: value("low_shelf_db"),
            high_shelf_db: value("high_shelf_db"),
        }
    }

    disconnect() {
        document.body.removeEventListener("htmx:afterRequest", this._after)
    }
}