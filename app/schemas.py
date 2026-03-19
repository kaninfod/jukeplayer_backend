"""
Pydantic schemas for API responses.
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


class Artist(BaseModel):
    """Artist response model."""
    id: str = Field(..., description="Unique artist ID from Subsonic")
    name: str = Field(..., description="Artist name")

    class Config:
        extra = "forbid"


class Album(BaseModel):
    """Album response model."""
    id: str = Field(..., description="Unique album ID from Subsonic")
    name: str = Field(..., description="Album name")
    year: Optional[int] = Field(None, description="Release year")
    cover_url: str = Field(..., description="URL to album cover art")

    class Config:
        extra = "forbid"


class Song(BaseModel):
    """Song/track response model from Subsonic API.
    
    Includes common fields returned by Subsonic, but allows extra fields
    for API compatibility.
    """
    id: str = Field(..., description="Unique track ID")
    title: str = Field(..., description="Track title")
    duration: Optional[int] = Field(None, description="Duration in seconds")
    artist: Optional[str] = Field(None, description="Artist name")
    album: Optional[str] = Field(None, description="Album name")
    track: Optional[int] = Field(None, description="Track number")
    year: Optional[int] = Field(None, description="Release year")
    albumId: Optional[str] = Field(None, description="Album ID")
    artistId: Optional[str] = Field(None, description="Artist ID")

    class Config:
        extra = "allow"  # Allow additional fields from Subsonic API


class AlbumInfo(BaseModel):
    """Album info response model from Subsonic API.
    
    Represents detailed album metadata. Allows extra fields for API compatibility.
    """
    id: str = Field(..., description="Unique album ID")
    name: Optional[str] = Field(None, description="Album name")
    artist: Optional[str] = Field(None, description="Artist name")
    artistId: Optional[str] = Field(None, description="Artist ID")
    coverArt: Optional[str] = Field(None, description="Cover art ID")
    year: Optional[int] = Field(None, description="Release year")
    genre: Optional[str] = Field(None, description="Genre")

    class Config:
        extra = "allow"  # Allow additional fields from Subsonic API
