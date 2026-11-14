"""Subsonic is the only music source.

The package still owns the transport (``api.py``), the concrete service
(``SubsonicService``), cover cache and artist metadata. The generic
``SourceProvider``/``SourceRegistry`` layer was removed with the multi-source
experiment; namespaced ids remain until the later id migration.
"""
from app.music_sources.ids import qualify, unqualify
from app.music_sources.subsonic import SubsonicService
from app.music_sources.subsonic.models import SubsonicAlbum, SubsonicTrack

__all__ = [
    "SubsonicService",
    "SubsonicAlbum",
    "SubsonicTrack",
    "qualify",
    "unqualify",
]
