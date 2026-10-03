import { Controller } from "@hotwired/stimulus"

// library filter bar: one segment expanded at a time — the open state lives
// in data-dirfilter-open-value ("alpha" | "genres" | "search"), which BOTH
// the CSS (segment visibility + active toggle tint) and this controller
// read/write. Switching is instant and client-side; search expansion puts
// the caret in the field.
export default class extends Controller {
    static values = { open: { type: String, default: "alpha" } }

    openToSearch() {
        this.openValue = "search"
        // the segment is display:none until the attribute lands — paint first
        requestAnimationFrame(() => this.element.querySelector("input")?.focus())
    }

    openToGenres() {
        this.openValue = "genres"
    }

    openToAlpha() {
        this.openValue = "alpha"
    }
}