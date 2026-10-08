"""Sound profiles: per-speaker equalization compiled to mpv's filter chain.

The profile (documented in docs/SOUND_TUNING.md §9) rides the speaker's
options in the config store:

    options.sound_profile = {
        "preamp_db": -3.0,            # headroom; NEVER above 0 (anti-clip)
        "bands_db": {                 # the 10 ISO octave bands; -12..+12
            "31": 0.0, "63": 1.5, "125": 1.0, "250": 0.0, "500": 0.0,
            "1000": 0.0, "2000": -1.0, "4000": -1.5, "8000": -2.0,
            "16000": -2.5,
        },
        "low_shelf_db": 0.0,          # optional tilt controls, fixed corners
        "high_shelf_db": -1.0,
    }

compile_snd_profile(profile) -> (af_string, errors):
- the af string = mpv's 'af' property value: preamp (volume filter) → the
  shelves (fixed corners: 80 Hz / 8 kHz) → one peaking equalizer per
  non-zero band, low to high;
- bands that are 0/absent are left out of the chain;
- errors = the validation problems (range/type/unknown-band names).
An empty profile compiles to "" — which means "no filters" (a clean way
to clear an applied profile).
"""
from typing import Any, Dict, List, Tuple

BANDS = ("31", "63", "125", "250", "500", "1000", "2000", "4000", "8000", "16000")
BAND_LIMIT = 12.0
PREAMP_RANGE = (-24.0, 0.0)  # headroom only — the preamp never boosts


def _num(value, errors: List[str], what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{what}: '{value}' is not a number")
        return 0.0


def validate(profile: Dict[str, Any]) -> List[str]:
    """Return the list of problems with a sound profile (empty = valid)."""
    errors: List[str] = []
    if not isinstance(profile, dict):
        return ["sound_profile must be an object"]
    lo, hi = (-24.0, 0.0)
    preamp = profile.get("preamp_db")
    if preamp is not None and preamp != "":
        v = _num(preamp, errors, "preamp_db")
        if not (lo <= v <= hi):
            errors.append(f"preamp_db {v} outside {-24.0}..0")
    bands = profile.get("bands_db", {}) or {}
    if not isinstance(bands, dict):
        errors.append("bands_db must be an object")
    else:
        for band, gain in bands.items():
            if str(band) not in BANDS:
                errors.append(f"unknown band '{band}' (known: {', '.join(BANDS)})")
                continue
            if gain in (None, ""):
                continue   # an unset band = not part of the profile at all
            v = _num(gain, errors, f"bands_db.{band}")
            if not (-BAND_LIMIT <= v <= BAND_LIMIT):
                errors.append(f"band {band} gain {v} outside -12..+12")
    for shelf in ("low_shelf_db", "high_shelf_db"):
        v = profile.get(shelf)
        if v is not None and v != "":
            num = _num(v, errors, shelf)
            if not (-BAND_LIMIT <= num <= BAND_LIMIT):
                errors.append(f"{shelf} {num} outside -12..+12")
    return errors


def compile_snd_profile(profile: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Profile → mpv 'af' filter string (+ validation errors)."""
    errors = validate(profile)
    if errors:
        return "", errors
    filters: List[str] = []
    if isinstance(profile, dict):
        preamp = profile.get("preamp_db")
        if preamp not in (None, "") and float(preamp) != 0.0:
            filters.append(f"volume={float(preamp):+g}dB")
        low = profile.get("low_shelf_db")
        if low not in (None, "", 0) and float(low or 0) != 0.0:
            filters.append(f"bass=f=80:w=0.3:g={float(low):+g}")
        high = profile.get("high_shelf_db")
        if high not in (None, "", 0) and float(high or 0) != 0.0:
            filters.append(f"treble=f=8000:w=0.2:g={float(high):+g}")
        bands = profile.get("bands_db", {}) or {}
        for band in BANDS:
            gain = bands.get(band) or bands.get(int(band))
            if gain in (None, "", 0, 0.0):
                continue
            g = float(gain)
            if g == 0.0:
                continue
            filters.append(f"equalizer=f={band}:t=q:w=2:g={g:+g}")
    return ",".join(filters), errors


def is_empty(profile) -> bool:
    """True when the profile sets nothing at all (no preamp, no bands)."""
    if not isinstance(profile, dict):
        return True
    preamp = profile.get("preamp_db")
    if preamp not in (None, "", 0, 0.0) and float(preamp or 0) != 0.0:
        return False
    bands = profile.get("bands_db", {}) or {}
    for band in BANDS:
        if (bands.get(band) or 0) != 0 and float(bands.get(band) or 0) != 0.0:
            return False
    for shelf in ("low_shelf_db", "high_shelf_db"):
        v = profile.get(shelf)
        if v not in (None, "", 0, 0.0) and float(v or 0) != 0.0:
            return False
    return True