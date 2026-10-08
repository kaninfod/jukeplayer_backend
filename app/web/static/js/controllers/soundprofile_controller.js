import { Controller } from "@hotwired/stimulus"

// sound dialogs: one per speaker (the config's room-correction row dialog
// and the devices card's DSP dialog); hx-post rendered statically (the
// dynamic-attribute variant submitted into nothing — the lesson). The
// controller opens/closes, closes after a successful apply, and on the DSP
// dialog gates the preset dropdown behind the Use-DSP checkbox.
export default class extends Controller {
    static targets = ["dialog", "form", "dspflag", "preset"]

    open() {
        this.dialogTarget.showModal()
    }

    cancel() {
        this.dialogTarget.close()
    }

    dspToggle() {
        // the bypass disables the preset select; a disabled select isn't
        // posted, so the stored choice survives being bypassed
        if (this.hasPresetTarget) this.presetTarget.disabled = !this.dspflagTarget.checked
    }

    connect() {
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