from __future__ import annotations

import logging

# logger for logging lol
logger = logging.getLogger(__name__)

# stores all data for a playlist track
class PlaylistTrack():
    
    def __init__(self, videoURL:str, name:str, displayName:str, index:int, length:float = None, downloaded:bool = None, albumName:str = None, albumDisplayName:str = None, artistName:str = None, ignored:bool = None):
        if not downloaded: downloaded = False
        if not ignored: ignored = False
        if not length: length = 0
        if not albumName: albumName = ""
        if not albumDisplayName: albumDisplayName = ""
        if not artistName: artistName = ""
        # set variables
        self._videoURL = videoURL
        self._name = name
        self._displayName = displayName
        self._index = index
        self._length = length
        self._downloaded = downloaded
        self._albumName = albumName
        self._albumDisplayName = albumDisplayName
        self._artistName = artistName
        self._ignored = ignored
        
    def getVideoURL(self):
        return self._videoURL
    
    def getName(self):
        return self._name
    
    def setDisplayName(self, name:str):
        self._displayName = name
    
    def getDisplayName(self):
        return self._displayName
    
    def getIndex(self):
        return self._index
    
    def setLength(self, length:float):
        self._length = length
    
    def getLength(self):
        return self._length
    
    def getDownloaded(self):
        return self._downloaded
    
    def setDownloaded(self, downloaded:bool):
        self._downloaded = downloaded

    def setAlbumName(self, name:str):
        self._albumName = name
        
    def getAlbumName(self):
        return self._albumName
    
    def setAlbumDisplayName(self, name:str):
        self._albumDisplayName = name
        
    def getAlbumDisplayName(self):
        return self._albumDisplayName
    
    def setArtistName(self, name:str):
        self._artistName = name
    
    def getArtistName(self):
        return self._artistName

    def getIgnored(self):
        return self._ignored
    
    def setIgnored(self, ignored:bool):
        self._ignored = ignored

    # returns the class in a dictionary form.
    def toDict(self):
        return {
            "video url": self._videoURL,
            "name": self._name,
            "display name": self._displayName,
            "index": self._index,
            "length": self._length,
            "downloaded": self._downloaded,
            "album name": self._albumName,
            "album display name": self._albumDisplayName,
            "artist name": self._artistName,
            "ignored": self._ignored,
        }