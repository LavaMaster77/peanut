from __future__ import annotations

from .playlist import Playlist
from .downloader import PlaylistDownloader

from classes.event.service import EventService
from classes.config.service import ConfigService
from classes.thread.service import ThreadService
from classes.log.service import LoggingService

import multiprocessing
from multiprocessing.synchronize import Event

import logging
import os
import time
import sys
import queue

# run in different process. handles downloading logic.
def _downloaderProcessManager(loggingQueue:multiprocessing.Queue, downloadQueue:multiprocessing.Queue, responseQueue:multiprocessing.Queue, stopEvent:Event):
    logger = logging.getLogger(f"{multiprocessing.current_process().name}")
    # clear any existing queue handlers
    logger.handlers.clear()
    queueHandler = logging.handlers.QueueHandler(loggingQueue)
    logger.addHandler(queueHandler)
    logger.propagate = False
    
    # setup downloader
    downloader = PlaylistDownloader(logger)
    logger.info("Playlist downloader process setup.") # yes, it actually works
    
    # listen for a download request
    while True:
        data = downloadQueue.get()
        if not data:
            # request to close this process
            responseQueue.put(None)
            break
        # send information communicating that the data was recieved
        responseQueue.put({"action": "DATA_RECIEVED"})
        playlist: Playlist = data["playlist"]
        match data["action"]:
            case "INITIALIZE":
                try:
                    downloader.initalizePlaylist(playlist)
                    # signal finish
                    responseQueue.put({"action": "INITIALIZE_DONE", "playlist": playlist})
                except Exception as e:
                    logger.error(f"An error occured while initializing the playlist {playlist.getName()}: {e}")
                    responseQueue.put({"action": "INITIALIZE_DONE", "playlist": None})
            case "DOWNLOAD":
                try:
                    # do the download. "data": necessary args for doing all the fun stuff
                    downloader.downloadPlaylist(playlist=data["playlist"], **data["data"], stopEvent=stopEvent, responseQueue=responseQueue)
                    # signal finish (only give back name of playlist)
                    responseQueue.put({"action": "PLAYLIST_DOWNLOAD_DONE", "playlistName": playlist.getName(), 
                                       "downloaded": playlist.getDownloaded(), "albums": playlist.getAlbums(), "queueEmpty": downloadQueue.empty(), "thumbnailDownloaded": playlist.getThumbnailDownloaded()})
                except Exception as e:
                    logger.error(f"An error occured while downloading the playlist {playlist.getName()}: {e}")
                    responseQueue.put({"action": "PLAYLIST_DOWNLOAD_DONE", "playlistName": None})
        # reset stop event just in case it was set
        if stopEvent.is_set(): stopEvent.clear()
    logger.info("Closing playlist downloader process.")

# playlist service class
class PlaylistService():
    
    def __init__(self, eventService:EventService, configService:ConfigService, threadService:ThreadService, loggingService:LoggingService):
        # setup logger
        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting playlist service.")
        
        # dependencies
        self.eventService = eventService
        self.configService = configService
        self.threadService = threadService
        self.loggingService = loggingService
        
        # keep track of all the current playlists
        self._playlists: dict[str, Playlist] = {}
        
        # keep track of downloading state
        self._initializingPlaylist: str = ""
        self._downloadingPlaylist: Playlist|None = None
        self._downloadQueueEmpty = True
        
        # current playlist
        self._currentPlaylist: Playlist | None = None
        
        # keep track of the name of a playlist and its url (to avoid downloading the same thing twice)
        self._playlistURLDict: dict[str, str] = {}
        
        # sets the playlist to download next after the current downloading one finishes
        self._nextPlaylist: str = ""
        self._nextPlaylistIndex: int = -1 # used to store the index that the next playlist should start at (only used for selecting tracks)
    
    # start the service.
    def start(self):
        # create necessary queues / listeners 
        self._downloadQueue = self.threadService.createProcessQueue("Download Queue")
        self._responseQueue = self.threadService.createProcessQueue("Download Response Queue")
        self._stopEvent = self.threadService.createProcessEvent("Playlist Downloader Stop Event")
        self._cancelEvent = self.threadService.createProcessEvent("Playlist Downloader Cancel Event")
        
        # create the playlist downloader process
        self._downloaderProcess = self.threadService.createProcess(_downloaderProcessManager, "Playlist Downloader", start=True, 
                                                                   loggingQueue=self.loggingService.getLoggingQueue(), downloadQueue=self._downloadQueue, 
                                                                   responseQueue=self._responseQueue, stopEvent=self._stopEvent)
        # create the response listener thread
        self.threadService.createThread(self._playlistDownloadListener, "Playlist Download Listener")
        self.threadService.createThreadEvent("Playlist Downloader Close")
        
        # listen for the program close event
        self.eventService.subscribeToEvent("PROGRAM_CLOSE", self._eventCloseProgram)
        
    # LISTENERS
    
    # listens for responses from the playlist downloader process.
    def _playlistDownloadListener(self):
        # get the response queue
        responseQueue = self._responseQueue
        while True:
            response = responseQueue.get()
            if not response:
                # request to close this thread
                break
            match response["action"]:
                case "DATA_RECIEVED": # the downloader recieved the request
                    self.setDownloadQueueEmpty(True)
                case "INITIALIZE_DONE": # playlist initialization finished
                    playlist: Playlist|None = response["playlist"]
                    if not playlist: continue
                    name = playlist.getName()
                    self.addPlaylist(playlist)
                    # save the file
                    self.savePlaylistFile(name)
                    # mark the download as being complete
                    self.setCurrentInitializatingPlaylist("")
                    self.eventService.triggerEvent("DOWNLOAD_STOP")
                case "TRACK_DOWNLOAD_DONE": # a singular track finished downloading (or failed downloading)
                    playlistName = response["playlistName"]
                    # mark it as downloaded
                    track = response["track"]
                    playlist = self.getPlaylist(playlistName)
                    if response["success"]:
                        playlist.updateTrack(track)
                        self.logger.debug(f"Marking track '{track.getDisplayName()}' as finished in the playlist service.")
                        # save the file. if this gets to be too cpu intensive, then stop doing this
                        self.savePlaylistFile(playlistName)
                        # trigger the download finish event for gui purposes
                        # sends the track itself plus the index the track is in the playlist
                    self.eventService.triggerEvent("PLAYLIST_TRACK_DOWNLOAD", playlist, track, response["downloadIndex"], response["success"])
                case "PLAYLIST_DOWNLOAD_DONE": # playlist download finished (or stopped)
                    playlistName = response["playlistName"]
                    if not playlistName: continue
                    # get the current playlist object
                    playlist = self.getPlaylist(playlistName)
                    self.logger.debug("Playlist downloader stopped.")
                    # set the downloaded state
                    playlist.setDownloaded(response["downloaded"])
                    playlist.setThumbnailDownloaded(response["thumbnailDownloaded"])
                    # set albums
                    playlist.setAlbums(response["albums"])
                    self.savePlaylistFile(playlist.getName())
                    # if there was a request to download another playlist after this, do that
                    nextPlaylist = self.getNextPlaylist()
                    if nextPlaylist:
                        self.downloadPlaylist(nextPlaylist, self._nextPlaylistIndex)
                        self.setNextPlaylist()
                        self._nextPlaylistIndex = -1
                    else:
                        self.logger.debug("Setting current downloading playlist to be None")
                        self.setCurrentDownloadingPlaylist(None)
                        self.setDownloadQueueEmpty(True)
                case "TRACK_DOWNLOAD_START":
                    # signal the start of the track download for the current playlist. mainly for gui updating
                    self.eventService.triggerEvent("PLAYLIST_TRACK_DOWNLOAD_START", response["track"], self.getPlaylist(response["playlistName"]), response["downloadIndex"])
        self.logger.info("Closing Playlist Download Listener.")
        # close the queues
        responseQueue.close()
        self._downloadQueue.close()
        self.threadService.setThreadEvent("Playlist Downloader Close")
            
     # for playlist downloader
    
    # EVENTS
    
    # stops any relevant playlist functions.
    def _eventCloseProgram(self):
        self.closeDownloaderProcess()
    
    # FILE HANDLING
    def savePlaylistFile(self, name:str):
        outputDirectory = self.configService.getOtherOptions()["outputFolder"]
        self.getPlaylist(name).dumpToFile(os.path.join(outputDirectory, name, "data.peanut"))
    
    # loads a playlist object from a given file path.
    def importPlaylistFromFile(self, filePath:str):
        playlist = Playlist(fileLocation=filePath)
        self.addPlaylist(playlist)
    
    # MANAGEMENT
    
    def setDownloadQueueEmpty(self, empty:bool):
        self._downloadQueueEmpty = empty
    
    def getDownloadQueueEmpty(self):
        return self._downloadQueueEmpty
    
    # sends a request to close the playlist downloader process.
    def closeDownloaderProcess(self):
        isDownloading = self.getCurrentDownloadingPlaylist() or self.getCurrentInitializatingPlaylist()
        if isDownloading:
            self.stopDownloadingPlaylist() # stop downloading first
        self._downloadQueue.put(None) # singal stop
    
    # signals to stop downloading the current playlist.
    def stopDownloadingPlaylist(self):
        self._stopEvent.set()
        # if there is stuff in the queue, clear it
        if not self.getDownloadQueueEmpty():
            self.logger.debug("Setting downloader cancel event.")
    
    def setCurrentInitializatingPlaylist(self, name:str):
        self._initializingPlaylist = name
        return
    
    def getCurrentInitializatingPlaylist(self):
        return self._initializingPlaylist
    
    def setCurrentDownloadingPlaylist(self, playlist:Playlist):
        self._downloadingPlaylist = playlist
        return
    
    def getCurrentDownloadingPlaylist(self):
        return self._downloadingPlaylist
    
    def addPlaylist(self, playlist:Playlist):
        name = playlist.getName()
        playlists = self.getPlaylists()
        # make sure the playlist is not already there
        if name in playlists:
            self.logger.warning(f"Failed to add playlist '{name}' to list: playlist already exists in list")
            return
        playlists[name] = playlist
        # add url to the url dict
        self.addPlaylistURLDictEntry(playlist.getPlaylistURL(), name)
        # trigger the init finish event
        self.eventService.triggerEvent("PLAYLIST_INITALIZATION_FINISH", playlist)
        
    def getPlaylists(self):
        return self._playlists
    
    def getPlaylist(self, name:str):
        playlists = self.getPlaylists()
        if not name in playlists:
            self.logger.warning(f"Playlist with name '{name}' not found in the playlist list.")
            return
        else:
            return playlists[name]
    
    def getDownloaderProcess(self):
        return self._downloaderProcess
  
    # bandaid solution for emptying the download queue. try not to use lol
    # def emptyDownloadQueue(self):
    #     q = self._downloadQueue
    #     count = 0
    #     try:
    #         while q.get_nowait():
    #             count += 1
    #     except queue.Empty:
    #         pass
    #     self.logger.debug(f"Download queue emptied. Cleared {count} entries.")
    #     self.setDownloadQueueEmpty(True)
    
    # starts downloading a given playlist from its name. blocks the current thread/coroutine until it finishes.
    def downloadPlaylist(self, name:str, startIndex:int = None):
        if not startIndex: startIndex = 0
        self.logger.debug("Downloading playlist")
        if self.getCurrentDownloadingPlaylist():
            self.logger.debug(f"Playlist downloader queue is empty; adding playlist '{name}' to download immediately after + stopping current download")
            self.setNextPlaylist(name)
            self.stopDownloadingPlaylist()
            self._nextPlaylistIndex = startIndex
        # retrieve the playlist
        playlist = self.getPlaylist(name)
        if not playlist: return
        # create a stop event so it can be interrupted
        if not name in self.threadService.getAsyncioEvents():
            # create the event
            self.threadService.createAsyncioEvent(name)
        # get download options
        options = self.configService.getOtherOptions()
        downloadOptions = options["downloadOptions"]
        outputExtension = options["outputConversionExtension"]
        # package the data together
        data = {"downloadOptions": downloadOptions, "outputExtension": outputExtension, 
                "thumbnailOutput": os.path.join(options["outputFolder"], name, "images"), 
            "playlistThumbnailLocation": os.path.join(options["outputFolder"], name, "thumbnail.jpg"), 
            "useYoutubeMusicAlbums": True, "maxVariation": 600, "startIndex": startIndex, "maxDownloadAttempts": 1}
        # request the download
        # self.logger.info(f"Size of playlist '{playlist.getDisplayName()}': {sys.getsizeof(playlist)} bytes; size of data: {sys.getsizeof(data)}")
        self.setCurrentDownloadingPlaylist(playlist)
        self._downloadQueue.put({"action": "DOWNLOAD", "playlist": playlist, "data": data})
        self.setDownloadQueueEmpty(False)
        self.logger.debug(f"Current downloading playlist: {self.getCurrentDownloadingPlaylist()}")
    
    # creates and initalizes a playlist object. blocks the current thread/coroutine until it finishes. 
    def createPlaylistFromURL(self, url:str):
        playlist = Playlist(playlistURL=url)
        # send into process to ..process
        self.setCurrentInitializatingPlaylist(url)
        self._downloadQueue.put({"action": "INITIALIZE", "playlist": playlist})
        self.setDownloadQueueEmpty(False)
    
    def getPlaylistURLDict(self):
        return self._playlistURLDict
    
    def removePlaylistURLDictEntry(self, url:str):
        urldict = self.getPlaylistURLDict()
        if url in urldict:
            del urldict[url]
        else:
            self.logger.warning(f"Failed to remove url '{url}' from the playlist url dict: entry does not exist")
    
    def addPlaylistURLDictEntry(self, url:str, name:str):
        urldict = self.getPlaylistURLDict()
        if url in urldict:
            self.logger.warning(f"Failed to add url '{url}' to the playlist url dict: entry already exists")
            return
        urldict[url] = name
    
    # checks to see if a playlist url already has an associated entry. if so, it returns the playlist name.
    def getPlaylistNameFromURL(self, url:str):
        urldict = self.getPlaylistURLDict()
        if url in urldict:
            return urldict[url]
        return None
    
    def getNextPlaylist(self):
        return self._nextPlaylist
    
    def setNextPlaylist(self, playlist:str|None=None):
        if not playlist: playlist = ""
        self._nextPlaylist = playlist
    