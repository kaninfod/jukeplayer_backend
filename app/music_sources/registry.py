"""The source registry: instances per source, built once (singleton) at
container setup. Phase 1 seeds SubsonicSource from the existing `subsonic`
config section — the `sources` config section + richer manifests arrives
with the second source."""
from typing import Dict, Optional

from app.music_sources.base import SourceProvider

import logging

logger = logging.getLogger(__name__)


class SourceRegistry:
    def __init__(self, default_pid: Optional[str] = None):
        self._sources: Dict[str, SourceProvider] = {}
        self._default_pid = default_pid

    def register(self, provider: SourceProvider) -> None:
        if provider.id in self._sources:
            logger.warning(f"Source '{provider.id}' re-registered — overwriting")
        self._sources[provider.id] = provider

    def get(self, pid: Optional[str]) -> SourceProvider:
        """pid None = the default source (bare/legacy ids). Unknown pid →
        ValueError (the caller's refusal path owns the user message)."""
        if pid is None:
            return self.default()
        source = self._sources.get(pid)
        if source is None:
            raise ValueError(f"Unknown music source '{pid}'")
        return source

    def default(self) -> SourceProvider:
        if self._default_pid:
            return self.get(self._default_pid)
        if len(self._sources) == 1:
            return next(iter(self._sources.values()))
        raise ValueError("No default music source configured and none is unambiguous")

    def all(self) -> list:
        """All registered sources (the library/future shelf UI)."""
        return list(self._sources.values())