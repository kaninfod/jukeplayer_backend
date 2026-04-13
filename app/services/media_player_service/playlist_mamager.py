from dataclasses import asdict, dataclass, field
from typing import List, Optional

@dataclass
class PlaylistItem:
    
    track_id: str
    stream_url: str
    duration: str
    track_number: int
    title: str
    artist: str
    album: str
    year: str
    cover_url: str
    

@dataclass
class PlaylistManager:
    name: str
    items: List[PlaylistItem] = field(default_factory=list)
    _current_index: int = 0
    _repeat_album: bool = False

    def add_item(self, item: PlaylistItem):
        self.items.append(item)


    @property
    def current_track(self) -> Optional[PlaylistItem]:
        if 0 <= self._current_index < len(self.items):
            return self.items[self._current_index]
        return None


    @property
    def current_index(self) -> int:
        return self._current_index
    
    @current_index.setter
    def current_index(self, index: int):
        if 0 <= index < len(self.items):
            self._current_index = index
        else:
            raise IndexError("Index out of range")
           

    def count(self) -> int:
        return len(self.items)

    def toggle_repeat(self) -> Optional[bool]:
        self._repeat_album = not self._repeat_album
        return self._repeat_album

    def previous_track(self) -> Optional[int]:
        if self.count() == 0:
            return None
        if self._current_index - 1 < 0:
            return 0 
        self._current_index = self._current_index - 1
        return self._current_index
    
    def next_track(self) -> Optional[int]:
        if self._current_index < self.count() - 1:
            self._current_index += 1
            return self._current_index
        elif self._repeat_album:
            self._current_index = 0
            return self._current_index
        else:
            return False

    
    def clear(self):
        self.items.clear()
        self._current_index = 0

    def to_dict(self):
        return [asdict(item) for item in self.items]