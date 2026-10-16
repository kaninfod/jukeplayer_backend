"""The source seam: albums and playable streams through one thin interface.
Consumers get the SourceRegistry via the container key `music_sources`.
"""
from app.music_sources.base import (
    SourceCapability, SourceProvider,
    SourceAlbum, SourceTrack, SourceHit, StreamSpec,
    qualify, unqualify,
)
from app.music_sources.registry import SourceRegistry
from app.music_sources.subsonic import SubsonicSource