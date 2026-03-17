import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.album import AlbumModel, Base

logger = logging.getLogger(__name__)

class AlbumDatabase:

    def create_empty_album_entry(self, rfid: str):
        """
        Create a new entry with the given RFID and an empty album_id, or update existing entry to have an empty album_id.
        """
        session = self.SessionLocal()
        try:
            album = session.query(AlbumModel).filter(AlbumModel.rfid == rfid).first()
            if album:
                album.album_id = None
                logger.info(f"Updated RFID {rfid} to have empty album_id.")
            else:
                album = AlbumModel(rfid=rfid, album_id=None)
                session.add(album)
                logger.info(f"Created new RFID {rfid} with empty album_id.")
            session.commit()
        finally:
            session.close()
            return True

        
    def __init__(self, config):
        self.config = config
        database_url = config.get_database_url()
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)



    def update_rfid_from_album_id(self, new_rfid: str, album_id: str):
        """
        Update the RFID for a given album_id. If the album_id exists, update its RFID; otherwise, create a new mapping.
        """
        session = self.SessionLocal()
        try:
            album = session.query(AlbumModel).filter(AlbumModel.album_id == album_id).first()
            if album:
                # Remove old mapping if another RFID is mapped to this album_id
                old_rfid = album.rfid
                album.rfid = new_rfid
                logger.info(f"Updated RFID for album_id {album_id}: {old_rfid} -> {new_rfid}")
            else:
                album = AlbumModel(rfid=new_rfid, album_id=album_id)
                session.add(album)
                logger.info(f"Created mapping: {new_rfid} -> {album_id}")
            session.commit()
        finally:
            session.close()

    def update_album_id_from_rfid(self, rfid: str, new_album_id: str):
        """
        Update the album_id for a given RFID. If the RFID exists, update its album_id; otherwise, create a new mapping.
        """
        self.set_album_mapping(rfid, new_album_id)


    def set_album_mapping(self, rfid: str, album_id: str):
        session = self.SessionLocal()
        try:
            album = session.query(AlbumModel).filter(AlbumModel.rfid == rfid).first()
            if album:
                album.album_id = album_id
                logger.info(f"Updated mapping: {rfid} -> {album_id}")
            else:
                album = AlbumModel(rfid=rfid, album_id=album_id)
                session.add(album)
                logger.info(f"Created mapping: {rfid} -> {album_id}")
            session.commit()
        finally:
            session.close()


    def get_album_id_by_rfid(self, rfid: str):
        session = self.SessionLocal()
        try:
            album = session.query(AlbumModel).filter(AlbumModel.rfid == rfid).first()
            return album.album_id if album else None
        finally:
            session.close()

    def delete_mapping(self, rfid: str):
        session = self.SessionLocal()
        try:
            album = session.query(AlbumModel).filter(AlbumModel.rfid == rfid).first()
            if album:
                session.delete(album)
                session.commit()
                logger.info(f"Deleted mapping for RFID: {rfid}")
        finally:
            session.close()



    def list_all(self):
        session = self.SessionLocal()
        try:
            albums = session.query(AlbumModel).all()
            return [(album.rfid, album.album_id) for album in albums]
        finally:
            session.close()

# Export for import *
__all__ = ["AlbumDatabase"]
