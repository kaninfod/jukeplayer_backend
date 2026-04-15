import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-kiosk--nfcencoding-target' in the HTML
    static targets = [  "waiting", "encoding", "success", "failure", "cancelled", "returnbutton", "cancelbutton" ]
    static values = {
            id: String,
            name: String,
            clientId: String  // CamelCase here maps to client-id in HTML
        }

    connect() {
        console.log("NFC Encoding Controller connected to the DOM")
        this.waitingTarget.classList.remove("d-none");
        this.cancelbuttonTarget.classList.remove("d-none");
        console.log("Album ID:", this.idValue);
        console.log("Album Name:", this.nameValue);
        console.log("Client ID:", this.clientIdValue);
        //this.startEncoding()

    }



    async post(url, data) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error(response.statusText);
        return response.json();
    }

    async startEncoding() {
        try {
            const data = await this.post('/api/nfc-encoding/start', {
                album_id: this.idValue,
                client_id: this.clientIdValue
            });
            this.showState('encoding');
        } catch (e) {
            this.showState('failure');
        }
    }

    handleCancelClick() {

        console.log("Cancel button clicked, sending cancel request to backend");

        const wsEvent = new CustomEvent("ws:send", { 
            detail: { 
                type: "nfc_encoding_cancelled", 
                payload: { "album_id": this.idValue, "client_id": this.clientIdValue } 
            } 
        });
        window.dispatchEvent(wsEvent);


        window.dispatchEvent(new CustomEvent("nav:go", { 
            detail: "/kiosk/player" 
        }));
    }

    handleExternalUpdate(event) {
        const state = event.detail.response.nfc_write_state || {};
        
        console.log(`Received external update for NFC encoding, state: ${state}`);
        
        if (state === 'started') {
            this.waitingTarget.classList.add("d-none");
            this.encodingTarget.classList.remove("d-none");
            this.cancelbuttonTarget.classList.remove("d-none");
        } else if (state === 'completed') {
            this.encodingTarget.classList.add("d-none");
            this.successTarget.classList.remove("d-none");
            this.returnbuttonTarget.classList.remove("d-none");
            this.cancelbuttonTarget.classList.add("d-none");
        } else if (state === 'cancelled') {
            this.encodingTarget.classList.add("d-none");
            this.cancelledTarget.classList.remove("d-none");
            this.cancelbuttonTarget.classList.add("d-none");
        }
    }
}