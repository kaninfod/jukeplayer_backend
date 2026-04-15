import { Application } from "@hotwired/stimulus"
import VolumeController from "./controllers/volume_controller.js"
import NowPlayingController from "./controllers/now_playing_controller.js"
import WebSocketController from "./controllers/websocket_controller.js"
import playerControlsController from "./controllers/player_controls_controller.js"
import NavigationController from "./controllers/navigation_controller.js"
import DeviceController from "./controllers/device_controller.js"
import NfcEncodingController from "./controllers/nfc_encoding_controller.js"

const application = Application.start()

// 1. Enable Debugging (Logs all Stimulus activity to console)
application.debug = true

// 2. Register your controllers
application.register("volume", VolumeController)
application.register("nowplaying", NowPlayingController)
application.register("websocket", WebSocketController)
application.register("playercontrols", playerControlsController)
application.register("navigation", NavigationController)
application.register("device", DeviceController)
application.register("nfcencoding", NfcEncodingController)
// 3. Optional: Global access for console debugging
window.Stimulus = application
