import { Application } from "@hotwired/stimulus"
// import VolumeController from "./controllers/volume_controller.js"
import NowPlayingController from "./controllers/now_playing_controller.js"
import WebSocketController from "./controllers/websocket_controller.js"
import playerControlsController from "./controllers/player_controls_controller.js"
import NavigationController from "./controllers/navigation_controller.js"
import DeviceController from "./controllers/device_controller.js"
import NfcEncodingController from "./controllers/nfc_encoding_controller.js"
import ClientActionsController from "./controllers/client_actions_controller.js"
import ConfigureController from "./controllers/configure_controller.js"
import LoggingController from "./controllers/logging_controller.js"
import BtSpeakerController from "./controllers/bt_speaker_controller.js"
import StyleguideController from "./controllers/styleguide_controller.js"
import VolumePopController from "./controllers/volumepop_controller.js"
import MenuSheetController from "./controllers/menusheet_controller.js"
import KeyboardController from "./controllers/keyboard_controller.js"
import LibrarySearchController from "./controllers/library_search_controller.js"
import DirFilterController from "./controllers/dir_filter_controller.js"
import SoundProfileController from "./controllers/soundprofile_controller.js"

const application = Application.start()

// 1. Enable Debugging (Logs all Stimulus activity to console)
application.debug = true

// 2. Register your controllers
// application.register("volume", VolumeController)
application.register("nowplaying", NowPlayingController)
application.register("websocket", WebSocketController)
application.register("playercontrols", playerControlsController)
application.register("navigation", NavigationController)
application.register("device", DeviceController)
application.register("nfcencoding", NfcEncodingController)
application.register("clientactions", ClientActionsController)
application.register("configure", ConfigureController)
application.register("logging", LoggingController)
application.register("btspeaker", BtSpeakerController)
application.register("styleguide", StyleguideController)
application.register("volumepop", VolumePopController)
application.register("menusheet", MenuSheetController)
application.register("keyboard", KeyboardController)
application.register("library-search", LibrarySearchController)
application.register("dir-filter", DirFilterController)
application.register("soundprofile", SoundProfileController)
// 3. Optional: Global access for console debugging
window.Stimulus = application
