import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-playercontrols-target' in the HTML
    static targets = ["currentdevice"]

    connect() {
        console.log("player controls Controller connected to the DOM")

    }


    switchDevice(event) {
        console.log("Switch Device button clicked - Sending via WS");
        this.shouldRedirect = true;
        const deviceBackend = event.params.deviceBackend;
        const deviceId = event.params.deviceId;
        const wsEvent = new CustomEvent("ws:send", { 
            detail: { 
                type: "switch_device", 
                payload: { "device_backend": deviceBackend, "device_id": deviceId } 
            } 
        });
        
        window.dispatchEvent(wsEvent);
    }

    handleSwitchResponse(event) {
        const [data] = event.detail.response;
        if (data && data.status === "ok") {
            this.updateActiveDevice(data.device_name);

            // ONLY redirect if we are actually expecting a user-initiated switch
            if (this.shouldRedirect) {
                this.shouldRedirect = false; // Reset the flag immediately
                window.dispatchEvent(new CustomEvent("nav:go", { 
                    detail: "/kiosk/player" 
                }));
            }
        }
    }

    updateActiveDevice(deviceId) {
        if (this.hasCurrentdeviceTarget) {
            this.currentdeviceTarget.textContent = deviceId;
        } else {
            console.log("Device UI span not found on this page.");
        }

        
    }
}