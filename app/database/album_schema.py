from pydantic import BaseModel, validator
from typing import Optional, List
import json

class Track(BaseModel):
    title: str
    duration: str
    track_number: int
    track_id: str


class AlbumEntry(BaseModel):
    rfid: str
    album_id: str

    class Config:
        from_attributes = True


class AlbumEntryUpdate(BaseModel):
    album_id: Optional[str] = None
