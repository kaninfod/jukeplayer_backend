# Room correction + EQ presets — best practices for equalizing a speaker/DAC

*How to decide what to correct, which frequencies matter, and how to profile.*
Scope: the mpv/PulseAudio output path (local, USB-DAC, Bluetooth-SBC) — each
speaker carries a **room correction** (its calibration, `options.room_correction`)
and picks a global **EQ preset** (`sound_presets`, shared) at run time,
gated by the **Use DSP** master (`options.dsp_enabled`; off = bypass).

---

## 1. What you are actually correcting

Digital out (USB to a DAC) is neutral below the analog stage — the DAC itself
does not "color" the music. What needs correcting is:

- **The speakers** — their response droops, humps, and breaks up in the
  transition region (~200 Hz – 4 kHz) depending on size and crossover.
- **The room** — room modes (standing waves) in the bass, boundary gain,
  early reflections dulling the midrange, and reverberation hiding detail.
- **The amp** — usually neutral; ignore unless a tone switch is engaged.

So: **bass-band corrections are mostly room corrections.** They depend on
*where the speaker sits and where you sit* — which is why a profile is
per-speaker and per-placement, not universal.

## 2. Room modes — the free, theoretic profiling

Standing waves occur when a room dimension fits half-wavelengths of a
frequency:

```
f (Hz) = 343 / (2 × dimension_m) × n    (n = 1, 2, 3 …)
```

Fill in your room's length L, width W, height H; compute the first two or
three multiples per axis. Those frequencies are **axial modes** — bass energy
piles up at them (boom) and cancels between them (suck-out at the null
positions). Practical uses:

- Cut predicted boom frequencies with **narrow Q** (w = 1–3) and modest
  gain (−3…−6 dB). Cutting is more trustworthy than boosting.
- Your listening position matters: near a wall = pressure (more bass);
  at a mode null = that frequency disappears. Move the seat before
  fighting the EQ.
- Tangential/oblique modes (the diagonal/3D ones) are weaker — axial modes
  (one dimension = half wavelength) are the ones worth pre-computing.

Example: a 5.0 × 4.0 × 2.6 m room → axial ~34, 69, 43, 86, 66, 132 Hz.
The 34/43 region is where "one-note bass" lives in most living rooms.

## 3. Band-by-band: what the sound symptom tells you

| Band | What lives there | Symptom → correction |
|---|---|---|
| 31.5 Hz | deepest room rumble, pipe-organ/sub-bass | One-note "rumble" → cut; no content below 50 in the music → leave |
| 63 Hz | bass weight, kick fundament | Boomy kick → small cut; thin, weak bass → small boost (+2…) |
| 125 Hz | bass body, warmth | "Woolly/muddy" midbass → cut 2–4 dB (the most common correction!) |
| 250 Hz | warmth, chest | "Boxy/cardboard" → small cut; cold/hollow → +1–2 dB |
| 500 Hz | mid warmth | Usually **leave alone**; nasality → tiny cut |
| 1 kHz | presence, speech | "Honky" → small cut; dull voices → touch up |
| 2 kHz | clarity, definition | Harsh/shouty → −2 dB; recessed vocals → +1–2 dB |
| 4 kHz | edge, sibilance onset | Sibilant/tiring → −2…−3 dB; veiled → +1 dB |
| 8 kHz | detail, sizzle | Dull → +1–2 dB; splashy cymbals → −2 dB |
| 16 kHz | air | Hiss/thin → cut; lifeless → +2 dB *only if* speakers+room still have it |

Structural controls:

- **Preamp** = headroom. Set it to at least **−(the largest single boost)**
  so combined boosts never reach the DAC's 0 dBFS (digital clipping is
  ugly and cannot be repaired later). Never boost the preamp above 0.
- **Low/high shelf** (fixed corners, gain-only) for the overall tilt —
  see the house curve below.

## 4. Tune at the level you listen at

Bass perception depends on loudness (equal-loudness/Fletcher–Munson): at low
volume everything sounds bassless; at high volume too much. Tune **at the
volume you actually listen at** — a profile dialed in at half volume will be
wrong at full. If the system plays at wildly different volumes during the
day, tune for the dominant level and accept a mild compromise.

## 5. The house curve (where "flat" actually sounds right)

A measured-flat response at the listening position sounds *thin* to human
ears. The widely used target: **flat below ~1 kHz, then a gentle downward
tilt of ~ −1 dB/octave** above it (some prefer −6 to −8 dB total from 8 kHz
up). In profile terms:

- 63–125 Hz: +1–2 dB
- 250–500 Hz: 0
- 1–2 kHz: 0
- 4–8 kHz: −1 to −2
- 16 kHz: −3 to −4 (or let the shelf do it)

Avoid a "smiley" EQ (big bass and treble boosts, scooped mids) — it photographs
well in screenshots and sounds like a boom-box.

## 6. The tuning procedure (ear version)

1. **Pre-fill from §2**: enter the room-mode cuts (narrow, −3 dB) and the
   house-curve tilt (§5) as the starting profile.
2. **A/B honestly**: toggle the profile off and on (bypass = clear the
   profile, apply; or keep two speaker profiles if the UI ever grows
   presets). Equal volume, same source, same chair.
3. **One band at a time**, small steps (±1–2 dB), listen 30 s minimum —
   ears need time; "different" ≠ "better".
4. **Vary the material deliberately**: acoustic (checks 125–500), vocal
   (1–4 k), drums/bass (63–125), cymbals (8–16 k).
5. **Revisit after a day.** Ears calibrate to whatever they last heard;
   the next day's fresh listen reveals real excesses. Most final profiles
   differ from the first draft — less correction, not more.
6. **Log the result**: each apply writes to the speaker's profile in the
   store; keep the values you rejected too (the JSON edit history or a
   comment block) — the third iteration usually converges, the first rarely.

## 7. The measured version (later, recommended)

The theoretic approach pre-fills the likely trouble; the measured approach
*gives exact answers*:

- Tool: **REW** (Room EQ Wizard, free) + a **calibrated USB mic**
  (miniDSP UMIK-1/2 or a Dayton EMM-6 — calibrate whatever you get).
- Position: mic at the ear height of the real listening spot; average a
  few positions for the general correction (±20 cm averages room detail).
- Measure: sweep from ~20 Hz to 20 kHz; look at **1/6 octave smoothed**
  curves. Do not chase 1/48-octave detail — that is the mic's own voice.
- Read: **narrow, tall bass peaks = cut** at those exact frequencies
  (Q ≈ 4–8, the room modes confirmed); the smoother response above 300 Hz
  wants broad, gentle shaping (the tilt/2k/4k region), never narrow boosts.
- Translate: for each ISO band, the gain = the distance between the
  measured curve and the target/house curve at that band's center,
  halved if in doubt (half the correction often sounds more natural
  than the full value).

## 8. Notes specific to this chain

- **USB direct out (the Fosi ZD3)**: the speaker's `audio_device` is an ALSA
  id — `alsa/hw:CARD=ZD3,DEV=0` — and mpv drives the card directly:
  PulseAudio is not in the signal path (its sink for the same card simply
  stays suspended), so nothing pins the output to a fixed 44.1 kHz — mpv
  delivers the file's native rate and its softvol handles the volume. The
  EQ chain is identical to the pulse route. `check_ready` verifies the card
  with `aplay -l`; if PulseAudio ever claims the card after a re-plug,
  `pactl set-card-profile <card> off` frees it.
- **DAC via USB**: sample-rate handling is mpv's; its defaults (resample to
  the sink's rate when needed) are fine. EQ is applied in the digital domain
  with 24-bit headroom — the DAC sees more level changes, not fewer bits.
- **The volume knob and the EQ interact**: boosts + high digital volume =
  the clip risk from §3; keep the preamp honest.
- **Bluetooth (SBC) speakers**: SBC is already lossy and device-matched to
  its radio; profiles there can still fix obvious booms, but expect less
  predictability than the wired path. Keep BT profiles conservative.
  Sink-loss rule: when a playing BT speaker's pulse sink vanishes, the
  manager STOPS the playback (the no-silent-handoff rule) instead of leaving
  PulseAudio's stream re-homing audible on some other sink.
- **Bit-perfect purism**: any EQ leaves bit-perfect territory by design.
  That is the point of the exercise — the DAC output stage and the room
  were never bit-perfect to your ears anyway.

## 9. The profile format reference

```
# per speaker — the ROOM CORRECTION (the calibration), the config's
# speakers-card dialog:
options.room_correction = {
  "preamp_db": -3.0,                  # headroom (≤ 0)
  "bands_db": {                       # the 10 ISO octave bands
    "31": 0.0, "63": 1.5, "125": 1.0, "250": 0.0, "500": 0.0,
    "1000": 0.0, "2000": -1.0, "4000": -1.5, "8000": -2.0, "16000": -2.5
  },
  "low_shelf_db": 0.0,                # optional tilt controls (fixed corners)
  "high_shelf_db": -1.0
}

# GLOBAL EQ PRESETS (additions layered on the correction, shared by every
# speaker) — the store's sound_presets section:
{
  "vocal":     {"bands_db": {"125": -1, "250": -1, "1000": 2, "2000": 2, "4000": 1.5}},
  "rock":      {"bands_db": {"63": 1.5, "125": 2, "250": 1, "4000": 1.5}},
  "jazz":      {"bands_db": {"125": 1, "1000": -0.5, "8000": 1.5, "16000": 1}},
  "classical": {"bands_db": {"63": 0.5, "125": 0.5, "2000": -0.5, "8000": 1, "16000": 0.5}}
}

# per speaker: the DSP master (false = bypass: nothing at all) + the choice
options.dsp_enabled = true         # absent = true
options.sound_preset = "vocal"     # a name from sound_presets (or absent)
```

Composition (identical at mpv spawn and on hot-apply): band-wise
`room_correction + preset`, **clamped to ±12** (a clamp = a toast warning,
never silent); the shelves summed the same way; the composed preamp = the
**more negative** of the correction's own preamp and −(the largest composed
boost) — the headroom rule enforced at composition. Validation ranges:
bands & shelves −12…+12 dB, preamp −24…0 dB; decimals enter verbatim
(AutoEQ's −6.4-style values).

`compile → mpv --af volume=<preamp>dB, bass|treble (shelves), then one
`equalizer=f=B:w=2:g=…` per non-zero band.` Applied at mpv spawn and
hot-set over the existing json-IPC channel — no restart.