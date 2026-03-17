from sqlalchemy import Column, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class AlbumModel(Base):
    __tablename__ = "albums"
    rfid = Column(String(64), primary_key=True, index=True)
    album_id = Column(String(64), nullable=False)
