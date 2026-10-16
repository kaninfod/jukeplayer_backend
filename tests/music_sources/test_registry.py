"""The source registry: default fallback, unknown-pid refusal, id discipline."""
import pytest

from app.music_sources.base import SourceProvider, SourceCapability, qualify, unqualify
from app.music_sources.registry import SourceRegistry


class FakeSource(SourceProvider):
    def __init__(self, sid, name="Fake", caps=()):
        self.id = sid
        self.name = name
        self.capabilities = frozenset(caps)


def test_get_returns_registered_source():
    registry = SourceRegistry()
    sub = FakeSource("subsonic")
    registry.register(sub)

    assert registry.get("subsonic") is sub


def test_unknown_pid_raises():
    registry = SourceRegistry()
    registry.register(FakeSource("subsonic"))
    with pytest.raises(ValueError, match="Unknown music source"):
        registry.get("ytmusic")


def test_bare_id_falls_back_to_default():
    """None pid = the legacy-card path: the default source."""
    registry = SourceRegistry(default_pid="subsonic")
    sub = FakeSource("subsonic")
    registry.register(sub)

    assert registry.get(None) is sub
    assert registry.default() is sub


def test_default_with_single_source_needs_no_default_pid():
    registry = SourceRegistry()
    only = FakeSource("subsonic")
    registry.register(only)

    assert registry.default() is only


def test_default_ambiguous_without_config_raises():
    registry = SourceRegistry()
    registry.register(FakeSource("a"))
    registry.register(FakeSource("b"))
    with pytest.raises(ValueError, match="No default music source"):
        registry.default()


def test_qualify_idempotent_and_unqualify():
    assert qualify("subsonic", "al-678") == "subsonic:al-678"
    assert qualify("subsonic", "subsonic:al-678") == "subsonic:al-678"
    assert unqualify("subsonic:al-678") == ("subsonic", "al-678")
    # legacy bare ids (every card encoded before the seam)
    assert unqualify("al-678") == (None, "al-678")


def test_capability_flags_shape():
    assert SourceCapability.SEARCH.value == "search"
    sub = FakeSource("subsonic", caps=(SourceCapability.BROWSE, SourceCapability.SCROBBLE))
    assert SourceCapability.SCROBBLE in sub.capabilities
    assert SourceCapability.SEARCH not in sub.capabilities