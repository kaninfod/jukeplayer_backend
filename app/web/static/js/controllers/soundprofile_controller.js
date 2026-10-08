import { Controller } from "@hotwired/stimulus"

// sound dialogs: one per speaker (the config's room-correction row dialog
// and the devices card's DSP dialog); hx-post rendered statically (the
// dynamic-attribute variant submitted into nothing — the lesson). Explicit
// intent only: Apply submits and STAYS open (the tuning loop); Close sets
// a flag then submits and the dialog closes once the apply succeeded;
// Cancel closes with nothing applied. Nothing else closes the dialog.
export default class extends Controller {
    static targets = ["dialog", "form", "dspflag", "preset"]

    open() {
        this._closeAfter = false
        this.dialogTarget.showModal()
    }

    cancel() {
        this.dialogTarget.close()
    }

    close_after_apply() {
        this._closeAfter = true   // the Close button runs this before its submit
    }

    dspToggle() {
        // the bypass disables the preset select; a disabled select isn't
        // posted, so the stored choice survives being bypassed
        if (this.hasPresetTarget) this.presetTarget.disabled = !this.dspflagTarget.checked
    }

    connect() {
        this._closeAfter = false
        this._after = (event) => {
            if (event.target === this.formTarget && event.detail.successful && this._closeAfter) {
                this._closeAfter = false
                this.dialogTarget.close()
            }
        }
        document.body.addEventListener("htmx:afterRequest", this._after)
    }

    disconnect() {
        document.body.removeEventListener("htmx:afterRequest", this._after)
    }
}