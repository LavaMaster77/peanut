from __future__ import annotations

import json
import os
import random
import yt_dlp
import re
import unicodedata
import logging

from .track import PlaylistTrack
import traceback

# import yt-dlp's sanitation
from yt_dlp import utils as yt_dlp_utils

def sanitizeFilename(name: str) -> str:
    # i think it's restricted
    return yt_dlp_utils._utils.sanitize_filename(name, restricted=True)

# logger for logging purposes
logger = logging.getLogger(__name__)

# helper method to safely retrieve a key from a dict without throwing an error
def getSafeKey(dict:dict, key:any, fallback:any):
    try:
        return dict[key]
    except KeyError:
        return fallback

class Playlist():
    
    # supports both using a playlist url and a file location
    def __init__(self, playlistURL: str = None, fileLocation: str = None):
        if not fileLocation:
            # set basic information
            self._tracks: list[PlaylistTrack] = []
            self._name: str = "Untitled"
            self._displayName: str = "Untitled"
            self._length: int = 0
            self._playlistURL: str = playlistURL
            self._downloaded = False
            self._thumbnailURL = ""
            self._thumbnailDownloaded = False
            self._albums: dict[str, list[str]] = {} 
        else:
            if not os.path.isfile(fileLocation):
                raise FileNotFoundError(f"File with location {fileLocation} not found.")   
            with open(fileLocation) as file:
                data = json.loads(file.read())
                try:
                    self._tracks = [PlaylistTrack(videoURL=trackData["video url"], name=trackData["name"], 
                                                  displayName=trackData["display name"], index=trackData["index"], 
                                                  downloaded=trackData["downloaded"], albumName=trackData["album name"],
                                                  length=trackData["length"],
                                                  albumDisplayName=trackData["album display name"], 
                                                  artistName=trackData["artist name"], ignored=getSafeKey(trackData, "ignored", False)) for trackData in data["tracks"]]
                    self._name = data["name"]
                    self._length = data["length"]
                    self._playlistURL = data["playlistURL"]
                    self._displayName = data["displayName"]
                    self._downloaded = data["downloaded"]
                    self._thumbnailURL = data["thumbnailURL"]
                    self._thumbnailDownloaded = data["thumbnailDownloaded"]
                    self._albums = data["albums"]
                except KeyError as e:
                    logger.warning("One or more elements is missing from the file. returning nothing")
            
    def addTrack(self, track:PlaylistTrack):
        self._tracks.append(track)
        
    def getTracks(self):
        return self._tracks
    
    def setName(self, name:str):
        self._name = name

    def getName(self):
        return self._name
    
    def setLength(self, length:int):
        self._length = length
    
    def getLength(self):
        return self._length
    
    def getTrack(self, trackIndex:int):
        return self._tracks[trackIndex]
    
    def getAbsoluteTrackIndex(self, index:int):
        return self._tracks[index]["index"]
        
    def dumpToFile(self, fileLocation:str):
        # verify file exists
        if not os.path.isfile(fileLocation):
            logger.info("File not found when dumping to file. Creating file.")
            directory = os.path.dirname(fileLocation)
            os.makedirs(directory, exist_ok=True)
            open(fileLocation, "x").close()
            
        jsonString = json.dumps({
            "name": self._name, 
            "displayName": self._displayName, 
            "playlistURL": self._playlistURL, 
            "length": self._length, 
            "downloaded": self._downloaded,
            "thumbnailURL": self._thumbnailURL,
            "thumbnailDownloaded": self._thumbnailDownloaded,
            "albums": self._albums,
            "tracks": [track.toDict() for track in self._tracks],
            }, indent=4)
        with open(fileLocation, "w") as file:
            file.write(jsonString)
    
    def setTracks(self, tracks:list[PlaylistTrack]):
        self._tracks = tracks        
    
    def setDownloaded(self, downloaded:bool):
        self._downloaded = downloaded
        
    def getDownloaded(self):
        return self._downloaded
    
    def setDisplayName(self, name:str):
        self._displayName = name
    
    def getDisplayName(self):
        return self._displayName
    
    def getPlaylistURL(self):
        return self._playlistURL
    
    def getThumbnailURL(self):
        return self._thumbnailURL
    
    def setThumbnailURL(self, url:str):
        self._thumbnailURL = url
    
    def setThumbnailDownloaded(self, downloaded:bool):
        self._thumbnailDownloaded = downloaded
        
    def getThumbnailDownloaded(self):
        return self._thumbnailDownloaded
    
    def randomize(self):
        random.shuffle(self._tracks)
    
    # adds an album entry to the playlist. mostly for download caching.
    def addAlbumEntry(self, name:str, entry):
        self._albums[name] = entry
        
    def getAlbums(self):
        return self._albums
    
    def setAlbums(self, albums):
        self._albums = albums
    
    # searches through the track list, removing the track that was previously in the new track's place (effectively updating it)
    def updateTrack(self, track:PlaylistTrack):
        index = track.getIndex()
        tracks = self.getTracks()
        for i, t in enumerate(tracks):
            if t.getIndex() == index:
                # this is the track, replace it
                tracks[i] = track
                break