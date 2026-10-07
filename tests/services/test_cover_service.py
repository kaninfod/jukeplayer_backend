"""CoverService — the extracted cover pipeline: cache-first, placeholder
fallback, and the RGB565 packing the ESP32 display consumes."""
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.services.cover_service import CoverService


def _red_png(size=64):
    img = Image.new("RGB", (size, size), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def cover(tmp_path):
    fake = MagicMock()
    fake.config.STATIC_FILE_PATH = str(tmp_path / "static_files")
    fake.cover_art_bytes.return_value = _red_png()
    return CoverService(fake), fake


def test_rgb565_packs_little_endian(cover):
    svc, _ = cover
    data = svc.get_cover_rgb565("al-1", size=64)
    assert data is not None
    assert len(data) == 64 * 64 * 2            # 2 bytes/pixel
    rgb565 = (data[1] << 8) | data[0]          # low byte first
    red = (rgb565 >> 11) * 255 // 31
    green = ((rgb565 >> 5) & 0x3F) * 255 // 63
    assert red >= 240 and green <= 4           # a red image, within lossy-webp tolerance


def test_fetch_once_then_cache_serves(cover):
    svc, fake = cover
    url = svc.ensure_cover("al-1", 180)
    assert url == "/assets/covers/al-1/cover-180.webp"
    url_again = svc.ensure_cover("al-1", 180)
    assert url_again == url
    assert fake.cover_art_bytes.call_count == 1   # the cache absorbed the second request


def test_unfetchable_falls_back_to_placeholder(cover):
    svc, fake = cover
    fake.cover_art_bytes.side_effect = RuntimeError("gonic is asleep")
    url = svc.ensure_cover("al-1", 180)
    assert url.startswith("/assets/covers/_default/cover-180")
    # the placeholder now exists as files (variants, both encodings)
    paths = svc._default_cover_paths(180)
    assert any(__import__("os").path.exists(p) for p in paths.values())