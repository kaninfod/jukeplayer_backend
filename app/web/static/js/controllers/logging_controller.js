import { Controller } from "@hotwired/stimulus"

// Console feedback for the web UI (developer aid): htmx traffic, toasts and
// errors land in the browser console. Traffic goes to console.debug (enable
// "Verbose" in DevTools filters); config-card actions, toasts and errors go
// to console.info/warn so they show up by default.
export default class extends Controller {
    connect() {
        this._timers = new WeakMap()

        this._onBeforeRequest = (e) => {
            const cfg = e.detail.requestConfig || {}
            this._timers.set(cfg, performance.now())
            const path = cfg.path || ""
            const msg = `[htmx] ${cfg.verb || "GET"} ${path} …`
            if (path.startsWith("/kiosk/config")) console.info.call(console, msg)
            else console.debug(msg)
        }
        this._onAfterRequest = (e) => {
            const cfg = e.detail.requestConfig || {}
            const started = this._timers.get(cfg) ?? performance.now()
            this._timers.delete(cfg)
            const ms = Math.round(performance.now() - started)
            const line = `[htmx] ${cfg.verb || "GET"} ${cfg.path || ""} → ${e.detail.xhr?.status ?? "?"} in ${ms}ms`
            if (e.detail.successful) console.debug(line)
            else console.warn(line + " (unsuccessful)")
        }
        this._onResponseError = (e) => {
            const cfg = e.detail.requestConfig || {}
            console.warn(`[htmx] ${cfg.verb || "GET"} ${cfg.path || ""} failed: ${e.detail.xhr?.status ?? "?"}`, e.detail.error || "")
        }
        this._onSendError = (e) => {
            console.warn(`[htmx] ${e.detail.requestConfig?.verb || "GET"} ${e.detail.requestConfig?.path || ""} network error`, e.detail.error || "")
        }
        this._onToast = (e) => {
            const d = e.detail || {}
            console.info(`[toast] ${d.message || ""}`, d.theme || "info")
        }

        document.body.addEventListener("htmx:beforeRequest", this._onBeforeRequest)
        document.body.addEventListener("htmx:afterRequest", this._onAfterRequest)
        document.body.addEventListener("htmx:responseError", this._onResponseError)
        document.body.addEventListener("htmx:sendError", this._onSendError)
        document.body.addEventListener("kioskToast", this._onToast)
        console.info("[kiosk] Console logging connected (htmx traffic + toasts)")
    }

    disconnect() {
        document.body.removeEventListener("htmx:beforeRequest", this._onBeforeRequest)
        document.body.removeEventListener("htmx:afterRequest", this._onAfterRequest)
        document.body.removeEventListener("htmx:responseError", this._onResponseError)
        document.body.removeEventListener("htmx:sendError", this._onSendError)
        document.body.removeEventListener("kioskToast", this._onToast)
    }
}