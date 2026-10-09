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


def compose_profiles(base: Dict[str, Any] | None,
                     preset: Dict[str, Any] | None) -> Tuple[Dict[str, Any], List[str]]:
    """The speaker's room correction (base) + a global EQ preset (additions)
    → ONE composed profile. Documented rules:
    - band-wise sums, clamped to ±12 (a clamp = a warning, never silent)
    - the shelves summed the same way
    - the preamp = AUTO: the more negative of (the base's own preamp,
      −(the largest composed boost)) — the doc's headroom rule enforced at
      composition; the base's AutoEQ preamp sets the floor.
    """
    warnings: List[str] = []
    base = base or {}
    preset = preset or {}

    def band(value, default=0.0) -> float:
        try:
            return float(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def clamp(value: float, what: str) -> float:
        if value > BAND_LIMIT or value < -BAND_LIMIT:
            clamped = max(-BAND_LIMIT, min(BAND_LIMIT, value))
            warnings.append(f"{what} {value:+g} clamped to {clamped:+g}")
            return clamped
        return value

    base_bands = base.get("bands_db") or {}
    add_bands = preset.get("bands_db") or {}
    bands: Dict[str, float] = {}
    for b in BANDS:
        bands[b] = clamp(band(base_bands.get(b)) + band(add_bands.get(b)), f"band {b}")

    low = clamp(band(base.get("low_shelf_db")) + band(preset.get("low_shelf_db")), "low shelf")
    high = clamp(band(base.get("high_shelf_db")) + band(preset.get("high_shelf_db")), "high shelf")

    max_boost = max([bands[b] for b in BANDS] + [low, high, 0.0])
    auto_preamp = -max_boost if max_boost > 0 else 0.0
    preamp = min(auto_preamp, band(base.get("preamp_db")))   # the more negative wins
    return {"preamp_db": preamp, "bands_db": bands,
            "low_shelf_db": low, "high_shelf_db": high}, warnings