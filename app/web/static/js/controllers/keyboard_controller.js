import { Controller } from "@hotwired/stimulus"

// keyboard: global shortcuts + arrow-walking for card views.
//
// globals (no modifier held):
//   s,p,l,c,y  -> navigate to speakers / player / library / clients / playlist
//   space      -> play/pause            m -> mute
//   + / =      -> volume up            - -> volume down
//   esc        -> close the volume popover
//   shift+←/→  -> previous/next track
//
// contextual: any container with data-keyboard-cards="<selector>" can be
// walked with the arrow keys (all four move one card, wrapping at the ends);
// Enter "clicks" the focused card — its own data-action runs, so playlist
// rows play, media cards open, speaker cards select. The focused card gets
// the .kb-focus ring.
//
// stands down in text inputs / textareas / selects / contenteditables (the
// search box lands later) and while ctrl/meta/alt is held.
export default class extends Controller {
    static screens = {
        s: "/kiosk/devices",
        p: "/kiosk/player",
        l: "/kiosk/library",
        c: "/kiosk/clients",
        y: "/kiosk/playlist",
    }

    connect() {
        this._container = null
        this._index = -1
    }

    onKey(event) {
        console.log("[kb] key:", event.key, "target:", event.target.tagName)
        if (event.ctrlKey || event.metaKey || event.altKey) return
        const t = event.target
        if (t.matches("input:not([type=checkbox]), textarea, select, [contenteditable]") || t.isContentEditable) return
        if (t.type === "range") return // keep arrow semantics for the volume slider

        const key = event.key

        if (key === "Escape") {
            window.dispatchEvent(new CustomEvent("volume-pop-close"))
            return
        }

        if (event.shiftKey) {
            if (key === "ArrowRight" || key === "ArrowLeft") {
                event.preventDefault()
                window.dispatchEvent(new CustomEvent("ws:send", {
                    detail: { type: key === "ArrowRight" ? "next_track" : "previous_track", payload: {} }
                }))
            }
            return
        }

        const screen = this.constructor.screens[key]
        if (screen) {
            window.dispatchEvent(new CustomEvent("nav:go", { detail: screen }))
            return
        }

        if (key === " ") {
            event.preventDefault() // page scroll
            window.dispatchEvent(new CustomEvent("ws:send", { detail: { type: "play_pause", payload: {} } }))
            return
        }
        if (key === "m") {
            window.dispatchEvent(new CustomEvent("ws:send", { detail: { type: "volume_mute", payload: {} } }))
            return
        }
        if (key === "+" || key === "=") {
            window.dispatchEvent(new CustomEvent("ws:send", { detail: { type: "volume_up", payload: {} } }))
            return
        }
        if (key === "-") {
            window.dispatchEvent(new CustomEvent("ws:send", { detail: { type: "volume_down", payload: {} } }))
            return
        }

        // --- contextual card walking
        if (key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft" || key === "ArrowRight") {
            this._walk(event, key === "ArrowRight" || key === "ArrowDown" ? 1 : -1)
            return
        }
        if (key === "Enter") {
            const card = this._focusedCard()
            if (card) {
                event.preventDefault()
                this._select(card)
            }
        }
    }

    _select(card) {
        // 1. a card may declare a keyboard destination (client cards -> configure)
        const destination = card.dataset.keyboardEnter
        if (destination) {
            window.dispatchEvent(new CustomEvent("nav:go", { detail: destination }))
            return
        }
        // 2. the card's own action, else the first child that carries one — in
        // most card anatomies the actionable element is a child (album cover
        // plays, card body navigates) and a click on the parent never reaches it
        const actionable = card.hasAttribute("data-action") ? card : card.querySelector("[data-action]")
        actionable?.click()
    }

    _walk(event, delta) {
        // the container: the remembered one while connected, else the first
        // navigable container on the page (one per page in practice)
        const container = (this._container && this._container.isConnected)
            ? this._container
            : document.querySelector("[data-keyboard-cards]")
        if (!container) return
        if (container !== this._container) {
            this._container = container
            this._index = -1
        }
        const selector = container.dataset.keyboardCards || ":scope > *"
        const cards = [...container.querySelectorAll(selector)]
        if (!cards.length) return

        const focused = cards.find((c) => c.classList.contains("kb-focus"))
        const activeRow = cards.find((c) => c.classList.contains("active"))
        let index = focused ? cards.indexOf(focused)
            : activeRow ? cards.indexOf(activeRow)   // start at the playing track
            : (this._index >= 0 ? this._index : -1)
        index = (index + delta) % cards.length
        if (index < 0) index = cards.length - 1

        cards.forEach((c) => c.classList.remove("kb-focus"))
        cards[index].classList.add("kb-focus")
        this._index = index
        cards[index].scrollIntoView({ block: "nearest", behavior: "smooth" })
        event.preventDefault()
    }

    _focusedCard() {
        if (!this._container || !this._container.isConnected) return null
        const selector = this._container.dataset.keyboardCards || ":scope > *"
        return [...this._container.querySelectorAll(selector)].find((c) => c.classList.contains("kb-focus")) || null
    }
}