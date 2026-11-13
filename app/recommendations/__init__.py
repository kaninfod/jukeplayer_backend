"""Smart-random album picker.

A deliberately small, stateless feature:
- one in-memory gonic catalog,
- one in-memory ListenBrainz profile (quarter + all-time release groups,
  genre x hour activity, recent listens),
- pure scoring/sampling,
- no database, no cache files, no new persistent state.
"""

from .models import Album, AlbumPick, ListeningProfile
from .picker import pick_album, pick_local, pick_neglected, pick_random
from .service import RecommendationService, normalize_mode

__all__ = [
    "Album",
    "AlbumPick",
    "ListeningProfile",
    "RecommendationService",
    "normalize_mode",
    "pick_album",
    "pick_local",
    "pick_neglected",
    "pick_random",
]
