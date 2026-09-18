import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    static params = ["clientId", "clientName"]

    reboot(event) {
        const clientId = event.params.clientId;
        const clientName = event.params.clientName;

        if (!confirm(`Reboot ${clientName}?`)) return;

        console.log(`Client actions: sending device_reset to ${clientName} (${clientId})`);
        window.dispatchEvent(new CustomEvent("ws:send", {
            detail: {
                type: "device_reset",
                payload: { "client_id": clientId }
            }
        }));

        window.showKioskToast(`Reboot command sent to ${clientName}`, { theme: "success" });
    }

    handleResponse(event) {
        const response = event.detail.response;
        if (!response || response.client_id !== event.params.clientId) return;

        if (response.status === "error") {
            console.error(`Reboot failed for ${event.params.clientId}: ${response.message}`);
            window.showKioskToast(`Reboot failed: ${response.message || "client not connected"}`, { theme: "error" });
        }
    }
}