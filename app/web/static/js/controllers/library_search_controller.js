import { Controller } from "@hotwired/stimulus"

// library search: enter submits as a library navigation (?search=); arrow-down
// hands the keyboard back to the card grid; esc clears + blur.
export default class extends Controller {
    static targets = ["field"]

    submit(event) {
        event.preventDefault()
        const query = this.fieldTarget.value.trim()
        if (!query) return
        window.dispatchEvent(new CustomEvent("nav:go", {
            detail: `/kiosk/library?search=${encodeURIComponent(query)}`
        }))
    }

    downKey(event) {
        event.preventDefault()
        this.fieldTarget.blur()
        window.dispatchEvent(new CustomEvent("kb-enter-cards"))
    }

    escapeKey(event) {
        event.preventDefault()
        this.fieldTarget.value = ""
        this.fieldTarget.blur()
        window.dispatchEvent(new CustomEvent("kb-enter-cards"))
    }
}