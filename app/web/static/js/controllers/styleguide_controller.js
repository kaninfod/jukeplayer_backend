import { Controller } from "@hotwired/stimulus"

// Styleguide helper: live theme toggle. The theme is attribute-driven
// (data-bs-theme on <html>) — this flips it to preview both skins.
export default class extends Controller {
    toggleTheme() {
        const root = document.documentElement
        root.dataset.bsTheme = root.dataset.bsTheme === "dark" ? "light" : "dark"
        console.info(`[styleguide] theme → ${root.dataset.bsTheme}`)
    }
}