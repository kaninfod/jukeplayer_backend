import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-kiosk--volume-target' in the HTML
    static targets = [ "fill", "text" ]

    connect() {
        console.log("Volume Controller connected to the DOM")
    }

    // This replaces your updateKioskVolume(data) function
    update(volumeValue) {
        const volume = parseInt(volumeValue) || 0;
        const timestamp = new Date().toLocaleTimeString('en-US', { 
            hour12: false, hour: '2-digit', minute: '2-digit', 
            second: '2-digit', fractionalSecondDigits: 3 
        });

        console.log(`[${timestamp}] STIMULUS UPDATE: ${volume}%`);

        // Update the fill height
        if (this.hasFillTarget) {
            this.fillTarget.style.height = `${volume}%`;
        }

        // Update the text
        if (this.hasTextTarget) {
            this.textTarget.textContent = `${volume}%`;
        }

    }

    handleExternalUpdate(evt) {
        // Modern JS: the data is inside the 'detail' property of the event object
        const newVolume = evt.detail.volume;
        
        if (newVolume !== undefined) {
            this.update(newVolume);
        }
    }
}