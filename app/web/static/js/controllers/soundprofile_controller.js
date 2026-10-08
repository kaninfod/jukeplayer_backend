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

    swallow(event) {
        // Dialog-local by construction: every click/change/keypress inside a
        // sound dialog stops at the dialog element. The dialogs are DOM
        // children of interactive cards (the devices card carries
        // click->device#switchDevice) and event bubbling follows the DOM
        // tree, NOT the <dialog> top layer — without this, a click on the
        // DSP checkbox switched the speaker AND navigated away, destroying
        // the open dialog. Esc still cancels natively (that is the dialog's
        // own cancel event, not a keydown that needs to propagate).
        event.stopPropagation()
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