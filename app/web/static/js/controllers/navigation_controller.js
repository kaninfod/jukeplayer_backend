// controllers/navigation_controller.js
import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    static targets = ["content"]


    async load(event) {
        // 1. Prevent default if it's a real click/link event
        if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
        }

        // 2. Extract URL: Check CustomEvent detail FIRST, then the HTML attribute
        let url = null;

        if (typeof event === 'string') {
            url = event; // Direct call: this.load("/path")
        } else if (event?.detail && typeof event.detail === 'string') {
            url = event.detail; // CustomEvent: window.dispatchEvent
        } else if (event?.currentTarget) {
            // Click Event: <button href="..."> or <a href="...">
            url = event.currentTarget.getAttribute("href") || event.currentTarget.dataset.url;
        }

        console.log("Navigation target resolved to:", url);

        if (!url) {
            console.warn("Navigation failed: No URL found in event", event);
            return;
        }

        // 3. The Fetch Logic
        try {
            const response = await fetch(url, {
                headers: { "HX-Request": "true" }
            });
            
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            
            const html = await response.text();
            
            // Update UI
            this.contentTarget.innerHTML = html;
            
            // Update URL bar
            window.history.pushState({ kiosk: true }, '', url);
            
        } catch (error) {
            console.error("Navigation fetch failed:", error);
        }
    }
}