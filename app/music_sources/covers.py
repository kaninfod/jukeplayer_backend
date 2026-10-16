"""Cover art: the fetch-once cache + image formats (extracted from
subsonic_service — the API client and the image pipeline are two crafts).

What lives here:
- the on-disk variant cache: static_files/covers/{album_id}/cover-{size}.webp|jpg
  (served as /assets/... by main's StaticFiles mount — browser/ESP32 fetches
  the cache, never gonic, keeping Basic Auth and CSP out of the picture)
- ensure_cover / ensure_cover_variants: fetch-once from gonic + center-square
  crop + webp/jpg variants; the generated placeholder as the fallback
- get_cover_rgb565: the ILI9488/ESP32 format (framebuf.RGB565 raw bytes)

Seam decisions:
- get_cover_proxy_url ("the browser never hits Subsonic") stays on the
  subsonic module next to get_cover_url — it is the proxy ROUTE's contract
  and several gonic-side album methods build it internally.
- This service consumes the subsonic client only for RAW BYTES
  (cover_art_bytes) — auth/transport stays in the API client.
"""
import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)


class CoverService:
    def __init__(self, subsonic_service):
        self.subsonic = subsonic_service

    # --- cache layout --------------------------------------------------------------
    def _cover_dir(self, album_id: str) -> str:
        base = getattr(self.subsonic.config, "STATIC_FILE_PATH", "static_files")
        return os.path.join(base, "covers", str(album_id))

    def _default_cover_dir(self) -> str:
        base = getattr(self.subsonic.config, "STATIC_FILE_PATH", "static_files")
        return os.path.join(base, "covers", "_default")

    def _cover_paths(self, album_id: str, size: int) -> dict:
        return {
            "webp": os.path.join(self._cover_dir(album_id), f"cover-{size}.webp"),
            "jpg": os.path.join(self._cover_dir(album_id), f"cover-{size}.jpg"),
        }

    def _default_cover_paths(self, size: int) -> dict:
        d = self._default_cover_dir()
        return {"webp": os.path.join(d, f"cover-{size}.webp"),
                "jpg": os.path.join(d, f"cover-{size}.jpg")}

    @staticmethod
    def _ensure_dir(path: str) -> None:
        os.makedirs(path, exist_ok=True)

    # --- image processing -----------------------------------------------------------
    @staticmethod
    def _center_square(image):
        w, h = image.size
        if w == h:
            return image
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return image.crop((left, top, left + side, top + side))

    def _save_variants(self, pil_image, out_paths: dict, size: int) -> None:
        from PIL import Image
        img = self._center_square(pil_image.convert("RGB")).resize(
            (size, size), Image.Resampling.LANCZOS)
        # WebP (preferred by browsers) + JPEG (ESP32-side decode fallback)
        try:
            img.save(out_paths["webp"], format="WEBP", quality=80)
        except Exception:
            pass
        try:
            img.save(out_paths["jpg"], format="JPEG", quality=85)
        except Exception:
            pass

    def _ensure_default_placeholder(self, size: int) -> None:
        """Generate the simple music-note placeholder, once, per size."""
        from PIL import Image, ImageDraw
        paths = self._default_cover_paths(size)
        self._ensure_dir(self._default_cover_dir())
        if not (os.path.exists(paths["webp"]) or os.path.exists(paths["jpg"])):
            img = Image.new("RGB", (size, size), color=(240, 240, 240))
            draw = ImageDraw.Draw(img)
            draw.rectangle([(size * 0.25, size * 0.25), (size * 0.75, size * 0.75)],
                           outline=(200, 200, 200), width=2)
            self._save_variants(img, paths, size)

    # --- the public flow -------------------------------------------------------------
    def ensure_cover(self, album_id: str, size: int = 180) -> str:
        """Ensure a cached variant exists; return its URL. Cache-first,
        fetch-once from gonic via the subsonic client's byte stream, fall
        back to the generated placeholder."""
        paths = self._cover_paths(album_id, size)
        self._ensure_dir(self._cover_dir(album_id))
        if os.path.exists(paths["webp"]) or os.path.exists(paths["jpg"]):
            return self._cover_url(album_id, size)
        try:
            raw = self.subsonic.cover_art_bytes(album_id)
            img = Image_from_bytes(raw)
            self._save_variants(img, paths, size)
            return self._cover_url(album_id, size)
        except Exception:
            self._ensure_default_placeholder(size)
            return self._default_cover_url(size)

    def ensure_cover_variants(self, album_id: str, sizes=(180, 512)) -> None:
        for s in sizes:
            try:
                self.ensure_cover(album_id, s)
            except Exception:
                pass

    def _cover_url(self, album_id: str, size: int, prefer: str = "webp") -> str:
        """Relative /assets URL of the variant that actually exists."""
        ext = "webp" if prefer == "webp" else "jpg"
        chosen = f"/assets/covers/{album_id}/cover-{size}.{ext}"
        paths = self._cover_paths(album_id, size)
        if prefer == "webp" and not os.path.exists(paths["webp"]) and os.path.exists(paths["jpg"]):
            chosen = f"/assets/covers/{album_id}/cover-{size}.jpg"
        return chosen

    def _default_cover_url(self, size: int, prefer: str = "webp") -> str:
        paths = self._default_cover_paths(size)
        if prefer == "webp" and os.path.exists(paths["webp"]):
            return f"/assets/covers/_default/cover-{size}.webp"
        return f"/assets/covers/_default/cover-{size}.jpg"

    def get_cover_static_url(self, album_id: str, size: int = 180,
                             absolute: bool = False, prefer: str = "webp") -> str:
        """Ready-to-use URL (generating the variant if missing)."""
        rel = self.ensure_cover(album_id, size)
        if not absolute:
            return rel
        base = getattr(self.subsonic.config, "PUBLIC_BASE_URL", "").rstrip("/")
        return f"{base}{rel}" if base else rel

    def get_cover_rgb565(self, album_id: str, size: int = 180) -> Optional[bytes]:
        """Raw size×size RGB565 bytes for the ILI9488 (framebuf.RGB565:
        2 bytes/pixel, little-endian). Feeds the ESP32 TTFT flow."""
        from PIL import Image
        self.ensure_cover(album_id, size)

        img_path = None
        for paths in (self._cover_paths(album_id, size), self._default_cover_paths(size)):
            for candidate in ("webp", "jpg"):
                p = paths.get(candidate)
                if p and os.path.exists(p):
                    img_path = p
                    break
            if img_path:
                break
        if not img_path:
            logger.error(f"[COVER] no image file found for {album_id}")
            return None

        try:
            img = Image.open(img_path).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            logger.exception(f"[COVER] failed to open {img_path}")
            return None

        packed = bytearray()
        for r, g, b in img.getdata():
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            packed.append(rgb565 & 0xFF)        # low byte first (little-endian)
            packed.append((rgb565 >> 8) & 0xFF)  # high byte second
        return bytes(packed)


def Image_from_bytes(raw: bytes):
    """PIL image from the raw gonic getCoverArt bytes."""
    from PIL import Image
    return Image.open(BytesIO(raw))