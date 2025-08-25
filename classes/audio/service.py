from __future__ import annotations

from classes.event.service import EventService
from classes.playlist.service import PlaylistService
from classes.config.service import ConfigService

from classes.playlist.playlist import Playlist
from classes.playlist.track import PlaylistTrack
from classes.thread.service import ThreadService

from just_playback import Playback

import logging
import pathlib
import os
import asyncio

# manages various audio functions.
class AudioService():
    def __init__(self, eventService:EventService, playlistService:PlaylistService, configService:ConfigService, threadService:ThreadService):
        
        # logging
        self.logger = logging.getLogger(__name__)
        
        # dependencies
        self.eventService = eventService
        self.playlistService = playlistService
        self.configService = configService
        self.threadService = threadService
        
        # status vars
        self._paused = False
        self._trackLoaded = False
        self._currentTrack: PlaylistTrack|None = None
        self._tempPause = False # primarly used with the scroll. meant to keep track of if the track was paused before the scroll was done
        self._stopAudioEvent = False # signals the stopping of the audio manager.
        self._loop = False
        self._volume = 1
        self._muted = False
        self._currentIndex: int = -1 # used in the audio manager
        
        # options
        self.volume = 1
        
        # playlist caching
        self._playlist: Playlist|None = None
        self._currentPlayback: Playback|None = None
        
        # caching options
        self._currentOutputDirectory: str = ""
    
    # start the service
    def start(self):
        self.logger.info("Starting audio service.")
        options = self.configService.getOtherOptions()
        self._currentOutputDirectory = options["outputFolder"]
        self._outputExtension = options["outputConversionExtension"]
        # register events
        ts = self.threadService
        self._skipAudioEvent = ts.createAsyncioEvent("AUDIO_SKIP")
        self._shuffleAudioEvent = ts.createAsyncioEvent("AUDIO_SHUFFLE")
        self._previousAudioEvent = ts.createAsyncioEvent("AUDIO_PREVIOUS")
        # indicates if a specific index has been selected, and what the new index is.
        self._selectTrackEvent = ts.createAsyncioEvent("AUDIO_SELECT")
        self._selectedTrackIndex = -1
        
        # subscribing to events
        self.eventService.subscribeToEvent("AUDIO_STOP", self._eventAudioStop)

    # File Management
    def getFilePathFromName(self, name:str):
        outputDir = self._currentOutputDirectory
        playlist = self.getCurrentPlaylist()
        if not playlist:
            self.logger.warning(f"Failed to get file from name '{name}': no playlist is loaded into the AudioService")
            return ""
        return os.path.join(outputDir, playlist.getName(), "music", name + self._outputExtension)
    
    # Event Management
    
    def invokeSkipEvent(self):
        self._skipAudioEvent.set()
        
    def invokeShuffleEvent(self):
        self._shuffleAudioEvent.set()
    
    def invokePreviousEvent(self):
        self._previousAudioEvent.set()
    
    def invokeSelectEvent(self, selectedIndex:int):
        self._selectedTrackIndex = selectedIndex
        self._selectTrackEvent.set()
    
    def _eventAudioStop(self):
        self._stopAudioEvent = True
        # if any audio is playing, stop it
        if self.getTrackLoaded():
            self.unloadTrack()
    
    # Internal Management
    
    # functions as the main coroutine to listen for anything interesting that happens to the audio
    async def _managePlaylist(self):
        firstTrack = True # makes the first track not automatically play
        playlist = self.getCurrentPlaylist()
        tracks = playlist.getTracks()
        length = playlist.getLength()
        skipEvent = self._skipAudioEvent
        shuffleEvent = self._shuffleAudioEvent
        previousEvent = self._previousAudioEvent
        selectEvent = self._selectTrackEvent
        while True:
            # iterate through each track in the playlist n play it (imitating a for loop, but not doing one b/c no previous abilities)
            self._currentIndex = -1
            while True:
                self._currentIndex += 1
                # if the index is out of bounds, signal the finish of the playlist
                if self._currentIndex == length:
                    break
                # clamp index
                if self._currentIndex < 0: self._currentIndex = 0
                track = tracks[self._currentIndex]
                # skipping ignored tracks
                if track.getIgnored(): continue
                self.setCurrentTrack(track)
                # check to see if anything's downloading
                if not track.getDownloaded():
                    # track isn't downloaded, either skip it or wait
                    if self.playlistService.getCurrentDownloadingPlaylist() or firstTrack:
                        # wait for the download
                        self.logger.info(f"Track '{track.getDisplayName()}' isn't downloaded yet. Waiting for finish.")
                        self.eventService.triggerEvent("AUDIO_TRACK_START", track, playlist, self._currentIndex)
                        while (not tracks[self._currentIndex].getDownloaded()) and (not (shuffleEvent.is_set() or self._stopAudioEvent or selectEvent.is_set())):
                            await asyncio.sleep(0.02)
                        if (shuffleEvent.is_set() or self._stopAudioEvent):
                            # break and restart the playlist
                            break
                        elif selectEvent.is_set():
                            # if the select event was set, change the index
                            self.threadService.resetAsyncioEvent("AUDIO_SELECT")
                            self._currentIndex = self._selectedTrackIndex - 1
                            self.logger.debug(f"Selecting track with index {self._currentIndex + 1} in the audio manager.")
                            continue
                        else:
                            self.logger.info(f"Download for track '{track.getDisplayName()}' complete.")
                        # update the current track object just incase it changed
                        track = tracks[self._currentIndex]
                    else:
                        # skip this track
                        self.logger.info(f"Skipping undownloaded track '{track.getDisplayName()}'.")
                        continue
                else:
                    self.eventService.triggerEvent("AUDIO_TRACK_START", track, playlist, self._currentIndex)
                self.logger.info(f"Now playing: {self._currentIndex + 1}. {track.getDisplayName()}")
                # loading and playing audio
                # if the current track is marked as paused, unpause it (occurs from manually selecting a track)
                if self.getPaused():
                    self.setPaused(False)
                    self.eventService.triggerEvent("AUDIO_TRACK_RESUME", track)
                playback = self.loadTrack(track, pause=firstTrack)
                # if the playback did not load, then continue
                if not playback:
                    self.logger.warning(f"Skipping track with name '{track.getName()}' due to an unexpected error")
                    continue
                # set the current volume
                playback.set_volume(self.getVolume())
                trackLength = playback.duration
                firstTrack = False
                # wait for it to finish
                while (playback.active) and (not (skipEvent.is_set() or shuffleEvent.is_set() or previousEvent.is_set() or self._stopAudioEvent or selectEvent.is_set())):
                    if not self.getPaused():
                        # set the progress bar progress
                        progress = playback.curr_pos / playback.duration
                        self.eventService.triggerEvent("AUDIO_TRACK_PROGRESS", progress, trackLength)
                    await asyncio.sleep(0.02)
                if self._stopAudioEvent:
                    break # stop the loop without doing anything else
                self.logger.info(f"Track '{track.getDisplayName()}' finished.")
                # reset the looping variable
                self.setLoop(False)
                self.unloadTrack()
                self.eventService.triggerEvent("AUDIO_TRACK_END", track, self._currentIndex)
                # if the request to shuffle was made, reset the playlist playing
                if shuffleEvent.is_set():
                    self.logger.info(f"Restarting (shuffled) playlist from beginning.")
                    break
                # if the previous event was set, go to the previous track
                if previousEvent.is_set():
                    self.logger.info(f"Going to previous track.")
                    self.threadService.resetAsyncioEvent("AUDIO_PREVIOUS")
                    self._currentIndex -= 2 # go back 2 b/c every new track index increases by one
                # reset the skip event if it was set
                if skipEvent.is_set():
                    self.threadService.resetAsyncioEvent("AUDIO_SKIP")
                    # unpause the audio to prevent weird bugs
                    self.setPaused(False)
                # if the select event was set, change the index
                if selectEvent.is_set():
                    self.threadService.resetAsyncioEvent("AUDIO_SELECT")
                    self._currentIndex = self._selectedTrackIndex - 1
            # if the request to shuffle was made, restart the playlist
            if shuffleEvent.is_set():
                self.threadService.resetAsyncioEvent("AUDIO_SHUFFLE")
            else:
                break
        if not self._stopAudioEvent:
            self.logger.info(f"Playlist {playlist.getDisplayName()} done.")
        self.logger.info("Playlist manager stopping.")
        if self.getCurrentPlaylist(): self.unloadPlaylist()
        self._currentIndex = -1
        self.eventService.triggerEvent("AUDIO_MANAGER_END")
                
    # actual audio work
    
    # sets the absolute position of the audio.
    def setAudioPosition(self, pos:float):
        playback = self.getCurrentPlayback()
        playback.seek(pos)
    
    def pauseAudio(self):
        playback = self.getCurrentPlayback()
        # to reduce weird audio pops
        # playback.set_volume(0)
        playback.pause()
        self.setPaused(True)
        self.eventService.triggerEvent("AUDIO_TRACK_PAUSE", self._currentTrack)
    
    def resumeAudio(self):
        playback = self.getCurrentPlayback()
        # to reduce weird audio pops
        # playback.set_volume(self.volume)
        playback.resume()
        self.setPaused(False)
        self.eventService.triggerEvent("AUDIO_TRACK_RESUME", self._currentTrack)
    
    # loads the specified track.
    def loadTrack(self, track:PlaylistTrack, pause:bool=None):
        if not pause: pause = False
        name = track.getName()
        # get the file path
        path = self.getFilePathFromName(name)
        if self.getTrackLoaded():
            self.logger.warning(f"Track was already loaded when loading track '{name}'. Loading anyway")
            self.unloadTrack()
        # load the track
        playback = Playback()
        # cache the playback
        self.setCurrentPlayback(playback)
        # attempt to load the file
        try:
            playback.load_file(path)
        except Exception as e:
            self.logger.error(f"An unexpected error occured while loading the track '{track.getName()}': {e}")
            self.setCurrentPlayback(None)
            return None
        playback.play() # actually make it so it can be played
        if pause: 
            self.pauseAudio()
            playback.seek(0)
        # set necessary variables
        self.setTrackLoaded(True)
        return playback
    
    # unloads the current track.
    def unloadTrack(self):
        if not self.getTrackLoaded():
            self.logger.warning("Attempted to unload track when no track was loaded")
            return
        self.getCurrentPlayback().stop()
        self.setCurrentPlayback(None)
        self.setTrackLoaded(False)
        self.setCurrentTrack(None)
        self.setTempPause(False)
    
    # unloads the current playlist.
    def unloadPlaylist(self):
        if self.getCurrentPlaylist():
            self._playlist = None
        else:
            self.logger.warning(f"Failed to unload playlist: no playlist was loaded")
    
    # sets up the audio handler for the current playlist.
    def loadPlaylist(self, playlist:Playlist):
        # check to see if there's already a playlist loaded
        if self.getCurrentPlaylist():
            self.logger.warning(f"Attempted to load playlist '{playlist.getName()}' when the playlist '{self.getCurrentPlaylist().getName()}' was already loaded")
            return
        self._playlist = playlist
        self._stopAudioEvent = False
        # setup a task to manage the playlist
        self.threadService.createTask(self._managePlaylist(), "Playlist Manager")
    
    # getting / setting
    
    def getCurrentIndex(self):
        return self._currentIndex
    
    def getLoop(self):
        return self._loop
    
    def setLoop(self, loop:bool):
        playback = self.getCurrentPlayback()
        if not playback:
            self.logger.warning("Attempted to set loop when playback wasn't loaded")
            return
        playback.loop_at_end(loop)
        self._loop = loop
    
        # sets the internal variable for volume and updates the current playback's volume if it is loaded.
        
    def getMuted(self):
        return self._muted

    def setVolume(self, volume:float):
        self._muted = volume == 0
        self._volume = volume
        playback = self.getCurrentPlayback()
        if playback:
            playback.set_volume(volume)
    
    def getVolume(self):
        return self._volume
    
    def setTempPause(self, pause:bool):
        self._tempPause = pause
    
    def getTempPause(self):
        return self._tempPause
    
    def getCurrentPlayback(self):
        return self._currentPlayback
    
    def setCurrentPlayback(self, playback:Playback|None):
        self._currentPlayback = playback
    
    def setTrackLoaded(self, loaded:bool):
        self._trackLoaded = loaded
        
    def getTrackLoaded(self):
        return self._trackLoaded
    
    def setPaused(self, paused:bool):
        self._paused = paused
        
    def getPaused(self):
        return self._paused
    
    def setCurrentTrack(self, track:PlaylistTrack|None):
        self._currentTrack = track
        
    def getCurrentTrack(self):
        return self._currentTrack
    
    def getCurrentPlaylist(self):
        return self._playlist
    
    