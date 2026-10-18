import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
    // These names map to 'data-kiosk--nfcencoding-target' in the HTML
    static targets = [  "waiting", "encoding", "success", "failure", "cancelled", "returnbutton", "cancelbutton", "uid", "errormessage" ]
    static values = {
            id: String,
            name: String,
            clientId: String
        }

    connect() {
        console.log("NFC Encoding Controller connected to the DOM")
        this.waitingTarget.classList.remove("d-none");
        this.cancelbuttonTarget.classList.remove("d-none");
        console.log("Album ID:", this.idValue);
        console.log("Album Name:", this.nameValue);
        console.log("Client ID:", this.clientIdValue);
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
        const payload = event.detail.response || {};
        const state = payload.nfc_write_state || {};

        console.log(`Received external update for NFC encoding, state: ${state} status: ${payload.status}`);

        if (state === 'started') {
            this.waitingTarget.classList.add("d-none");
            this.encodingTarget.classList.remove("d-none");
            this.cancelbuttonTarget.classList.remove("d-none");
        } else if (state === 'completed') {
            // The completion payload carries the real status; the branch is
            // status-aware now — the previous version showed "Card Encoded!"
            // for failed encodes because it only looked at nfc_write_state.
            this.encodingTarget.classList.add("d-none");
            this.cancelbuttonTarget.classList.add("d-none");
            if (payload.status === 'success') {
                this.successTarget.classList.remove("d-none");
                this.returnbuttonTarget.classList.remove("d-none");
                if (this.hasUidTarget && payload.uid) {
                    this.uidTarget.textContent = "UID: " + payload.uid;
                }
            } else {
                this.failureTarget.classList.remove("d-none");
                if (this.hasErrorMessageTarget) {
                    this.errormessageTarget.textContent = payload.error_message || "Unknown error";
                }
            }
        } else if (state === 'cancelled') {
            this.encodingTarget.classList.add("d-none");
            this.cancelledTarget.classList.remove("d-none");
            this.cancelbuttonTarget.classList.add("d-none");
        }
    }
}