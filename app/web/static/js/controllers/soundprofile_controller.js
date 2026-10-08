import { Controller } from "@hotwired/stimulus"

// sound profile: one dialog PER speaker row, its hx-post rendered statically
// (the dynamic-attribute variant submitted into nothing — see the lesson in
// the card's header comment). The controller only opens/closes and closes
// after a successful apply; prefills come from the server render, so the
// dialog always shows the speaker's currently stored values.
export default class extends Controller {
    static targets = ["dialog", "form"]

    open() {
        this.dialogTarget.showModal()
    }

    cancel() {
        this.dialogTarget.close()
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