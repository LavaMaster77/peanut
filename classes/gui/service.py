from __future__ import annotations
from PySide6.QtCore import Qt, Slot, QMetaObject
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget, QSizePolicy

from classes.generatedui.mainwindow_ui import Ui_MainWindow
from classes.event.service import EventService
from classes.playlist.playlist import Playlist
from classes.playlist.track import PlaylistTrack
from classes.config.service import ConfigService
from classes.thread.service import ThreadService

from customwidgets.trackframe.trackframe import TrackFrame
from customwidgets.loadwidget.loadwidget import LoadWidget

from .handler_mainwindow import Window

import os
import logging
import resources_rc

class GuiService():
    
    def __init__(self, mainWindow:Ui_MainWindow, eventService:EventService, configService:ConfigService, threadService:ThreadService):
        
        self.logger = logging.getLogger(__name__)
        
        self._mainWindow = mainWindow
        self.eventService = eventService
        self.configService = configService
        self.threadService = threadService
        
        self._closing = False
        
        # caches all existing track widgets
        self._trackWidgets: list[TrackFrame] = []
        
        # caches the currently playing track + playlist for album cover purposes
        self._currentTrack: PlaylistTrack|None = None
        self._currentTrackWidget: TrackFrame|None = None
        
        # connect() connections
        self._connections: dict[str, QMetaObject.Connection] = {}
    
    # GUI HANDLING
    def setPlaylistURLBoxText(self, text:str):
        # retrieve the box
        textBox = self.getMainWindow().ui.input_playlistURL
        textBox.setText(text)
    
    def setLoadingState(self, loading:bool):
        widget: LoadWidget = self.getMainWindow().ui.info_loading
        if loading:
            widget.startAnimation()
            widget.showWidget()
        else:
            widget.stopAnimation()
            widget.hideWidget()
    
    def setPlaylistDataText(self, playlistName:str, currentTrackIndex:int, totalTracks:int):
        box = self.getMainWindow().ui.info_playlistData
        box.setText(f"{playlistName} • {currentTrackIndex}/{totalTracks}")
    
    def setArtistDataText(self, artist:str, albumName:str):
        self._window.ui.info_artistAlbum.setText(f"{artist} • {albumName}")
    
    def setCurrentTrackTimeText(self, text:str):
        self._window.ui.info_trackCurrentTime.setText(text)
        
    def setTotalTrackTimeText(self, text:str):
        self._window.ui.info_trackTotalTime.setText(text)
        
    def setTrackNameBoxText(self, text:str):
        self._window.ui.info_trackName.setText(text)
    
    def setProgressBarProgress(self, progress:float):
        bar = self.getMainWindow().ui.info_progressBar
        bar.setProgress(progress)
    
    def setVolumeBarProgress(self, progress:float):
        self.getMainWindow().ui.input_volumeBar.setProgress(progress)
    
    def getVolumeBarProgress(self):
        return self.getMainWindow().ui.input_volumeBar.getProgress()
    
    def setLoopButtonActivated(self, activated:bool):
        loopbutton = self.getMainWindow().ui.action_loop
        loopbutton.setActivatedState(activated)
    
    def setMainWindowTitle(self, title:str):
        self._window.setWindowTitle(title)
    
    def setAlbumCoverImage(self, imgPath:str):
        pixmap = QPixmap(imgPath)
        self._window.ui.info_albumCover.setPixmap(pixmap)
    
    # scrolls the track scroll area to position the current widget at the top, if possible.
    def scrollToWidget(self, widget):
        scrollArea = self.getMainWindow().ui.container_nextList
        childWidget = scrollArea.widget()
        scrollBar = scrollArea.verticalScrollBar()
        scrollBar.setValue(widget.pos().y() - childWidget.layout().spacing())
    
    # updates the given track gui element from track data and index.
    def updateTrackWidget(self, track:PlaylistTrack, index:int):
        # retrieve the widget, if it exists
        widgetList = self.getTrackWidgetList()
        if index >= len(widgetList):
            self.logger.warning(f"Attempted to update the track widget list with an index ({index}) out of bounds of the widget list.")
            return
        widget = widgetList[index]
        # set the text
        widget.setTitleText(track.getDisplayName())
        widget.setArtistText(track.getArtistName())
        widget.setDownloadedState(track.getDownloaded())
    
    # generic method to set the main stack widget's page
    def setMainWindowPage(self, pageWidget:QWidget):
        stackedWidget = self._window.ui.container_stackedWidget
        stackedWidget.setCurrentWidget(pageWidget)
    
    # sets the title text box's text
    def setTitleTextBoxText(self, text:str):
        self._window.ui.info_pageTitle.setText(text)
    
    # loads the audio player page and changes the title text accordingly
    def loadPageAudioPlayer(self):
        self.setMainWindowPage(self._window.ui.page_audioPlayer)
        self.setTitleTextBoxText("Player")
        
    def loadPagePlaylistSelector(self):
        self.setMainWindowPage(self._window.ui.page_playlistSelector)
        self.setTitleTextBoxText("Playlist Selector")
        
    # element that contains the playlist selection options
    def getPlaylistSelectorElement(self):
        return self._window.ui.container_playlistSelectorScrollArea
    
    # returns the widget that stores all of the upcoming widgets
    def getNextListScrollArea(self):
        return self._window.ui.container_nextListScrollArea
    
    # removes all current track widgets in the list box.
    def removeTrackWidgets(self):
        # gets the layout for the next list scroll area
        layout = self.getNextListScrollArea().layout()
        for widget in self.getTrackWidgetList():
            layout.removeWidget(widget)
            widget.deleteLater()
        # removes the cache for all the track widgets
        self._trackWidgets = []
        self._currentTrackWidget = None
    
    # populates the next list scroll area with the current playlist's track widgets.
    def populateNextListScrollArea(self, playlist:Playlist):
        # collecting information
        scrollArea = self.getNextListScrollArea()
        layout = scrollArea.layout()
        
        # defining function to run when the buttons are clicked
        @Slot(GuiService, int)
        def buttonActivated(self, buttonIndex:int):
            self.eventService.triggerEvent("AUDIO_SELECT", buttonIndex)
        
        for index, track in enumerate(playlist.getTracks()):
            button = TrackFrame(scrollArea)
            
            # customizing button
            button.setTitleText(track.getDisplayName())
            button.setArtistText(track.getArtistName())
            button.setDownloadedState(track.getDownloaded())
            
            button.clicked.connect(lambda i=index: buttonActivated(self, i)) # checked singal is always sent
            layout.insertWidget(index, button)
            self.addTrackWidgetToList(button)
    
    # button changing
    
    def setDownloadButtonState(self, downloadState:bool):
        button = self._window.ui.action_download
        if downloadState:
            # replace the button icon with a stop button
            button.setIcon(QIcon(":/buttons/resources/white/stop.png"))
        else:
            # replace the button icon with a download button
            button.setIcon(QIcon(":/buttons/resources/white/download.png"))
            
    def setPlayButtonState(self, playingState:bool):
        button = self._window.ui.action_play
        if playingState:
            # replace the button icon with a pause button
            button.setIcon(QIcon(":/buttons/resources/white/pause.png"))
            # change the button padding ratio
            button.setPaddingPercentage(0, 0, 0, 0)
        else:
            # replace the button icon with a play button
            button.setIcon(QIcon(":/buttons/resources/white/play.png"))
            # change the button padding ratio
            button.setPaddingPercentage(0, 0, 0, 0.07142857142)
    
    def setMuteButtonState(self, mutedState:bool):
        button = self.getMainWindow().ui.action_mute
        if mutedState:
            # replace the button icon with a muted button
            button.setIcon(QIcon(":/buttons/resources/white/mute.png"))
        else:
            # replace the button icon with an unmuted button
            button.setIcon(QIcon(":/buttons/resources/white/volume.png"))
    
    # INTERIOR MANAGEMENT
    
    def getMainApplication(self):
        return self._QApplication
    
    def getMainWindow(self):
        return self._window
    
    def getConnections(self):
        return self._connections
    
    def removeConnection(self, name:str):
        connections = self.getConnections()
        if name in connections:
            try:
                connections[name].disconnect()
                del connections[name]
            except Exception as e:
                self.logger.error(f"An error occured while removing the connection '{name}': {e}")
        else:
            self.logger.warning(f"Failed to remove connection '{name}': connection does not exist")
    
    def addConnection(self, name:str, connection:QMetaObject.Connection):
        connections = self.getConnections()
        if name in connections:
            self.logger.warning(f"Failed to add connection '{name}': connection already exists")
            return
        connections[name] = connection
    
    def getTrackWidgetList(self):
        return self._trackWidgets
    
    def addTrackWidgetToList(self, widget:QWidget):
        self.getTrackWidgetList().append(widget)
    
    # resets all of the audio player widgets to their default settings
    def resetAudioPlayerGUI(self):
        # reset the album image
        self.setAlbumCoverImage(":/unsorted/resources/placeholder.png")
        self.setPlaylistDataText("no playlist", 1, 0)
        self.setArtistDataText("no artist", "no album")
        self.setTrackNameBoxText("no track loaded")
        self.setCurrentTrackTimeText("0:00")
        self.setTotalTrackTimeText("0:00")
        self.setProgressBarProgress(0)
        self.removeTrackWidgets()
        self.setLoopButtonActivated(False)
    
    # EVENTS
    
    def _eventCurrentPlaylistChange(self, newPlaylist:Playlist|None):
        # update the playlist data text box
        currentPlaylist = newPlaylist
        if currentPlaylist:
            self.setLoadingState(True)
            self.resetAudioPlayerGUI() # cleanup the menu
            self.setPlaylistDataText(newPlaylist.getDisplayName(), 1, newPlaylist.getLength())
            # populate the track list
            self.populateNextListScrollArea(newPlaylist)
            # signal the finish
            self.eventService.triggerEvent("GUI_LOAD_AUDIO_PLAYER_FINISH")
            self.setLoadingState(False) # reset the loading state
        else:
            # reset the cache
            self._currentTrackWidget = None
            self._currentTrack = None
    
    # runs when an initialization process starts.
    def _eventPlaylistInitializationStart(self):
        self.setLoadingState(True)
    
    # runs when a playlist finishes initalizing and gets its data
    def _eventPlaylistInitialized(self, playlist:Playlist):
        if self._closing: return
        # get data
        box = self.getPlaylistSelectorElement()
        layout = box.layout()
        name = playlist.getName()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        # create a playlist selector
        button = QPushButton(playlist.getDisplayName(), box)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # add to the layout
        layout.addWidget(button)
        # subscribe clicks to events
        @Slot()
        def onButtonPress():
            # trigger the request
            self.eventService.triggerEvent("PLAYLIST_SELECT_REQUEST", playlist)
        connection = button.clicked.connect(onButtonPress)
        # add the conection
        self.addConnection(f"Playlist Select Request Connection: {name}", connection)
        self.setLoadingState(False)
    
    def _eventAudioTrackStart(self, track:PlaylistTrack, playlist:Playlist, index:int):
        # update the current track name box
        self.setTrackNameBoxText(track.getDisplayName())
        # update the playlist data
        self.setPlaylistDataText(playlist.getDisplayName(), index + 1, playlist.getLength())
        # update the author / album data
        self.setArtistDataText(track.getArtistName() or "unknown artist", track.getAlbumDisplayName() or "unknown album")
        # set the total track time
        m, s = divmod(int(track.getLength()), 60)
        self.setTotalTrackTimeText(f"{m:02d}:{s:02d}")
        # set the album cover image
        albumName = track.getAlbumName()
        if albumName:
            self.setAlbumCoverImage(os.path.join(self.configService.getOtherOptions()["outputFolder"], playlist.getName(), "images", f"album_{albumName}.jpg"))
        else:
            self.setAlbumCoverImage(":/unsorted/resources/placeholder.png")
        # cache the current track
        self._currentTrack = track
        # set the scroll
        widgetList = self.getTrackWidgetList()
        if widgetList:
            trackWidget = widgetList[index]
            # if a current track is already selected, then deselect it (primarly happens when the previous track was not downloaded)
            previousTrackWidget = self._currentTrackWidget
            if previousTrackWidget and (not previousTrackWidget is trackWidget):
                previousTrackWidget.setSelectedState(False)
            self._currentTrackWidget = trackWidget
            
            self.scrollToWidget(trackWidget)
            # set the status
            trackWidget.setSelectedState(True)
    
    def _eventAudioTrackPause(self, track:PlaylistTrack):
        # change the play button state
        self.setPlayButtonState(False)
    
    def _eventAudioTrackResume(self, track:PlaylistTrack):
        self.setPlayButtonState(True)
    
    def _eventAudioTrackEnd(self, track:PlaylistTrack, index:int):
        self._currentTrack = None
        widgetList = self.getTrackWidgetList()
        if widgetList:
            trackWidget = widgetList[index]
            self.scrollToWidget(trackWidget)
            # set the status
            trackWidget.setSelectedState(False)
        # disable the looping
        self.setLoopButtonActivated(False)
    
    def _eventDownloadStartRequest(self):
        self.setDownloadButtonState(True)
        self.setMainWindowTitle("peanut [Downloading]")
        self.setLoadingState(True)
    
    def _eventDownloadStop(self):
        self.setDownloadButtonState(False)
        self.setMainWindowTitle("peanut")
        self.setLoadingState(False)
    
    def _eventProgramClose(self):
        # set the title of the window
        self._window.setWindowTitle("peanut [Closing]")
        self._closing = True
    
    def _eventGuiMuteAudio(self):
        self.setMuteButtonState(True)
    
    def _eventGuiUnmuteAudio(self):
        self.setMuteButtonState(False)
    
    def _eventPlaylistTrackDownload(self, playlist:Playlist, track:PlaylistTrack, trackIndex:int, success:bool):
        if self._closing: return
        trackList = self.getTrackWidgetList()
        trackWidget = trackList[trackIndex]
        if trackList:
            if success:
                # update the track data for the specific gui element
                self.updateTrackWidget(track, trackIndex)
                if (track.getName() == self._currentTrack.getName()) and (track.getAlbumName()):
                    # update the album image
                    self.setAlbumCoverImage(os.path.join(self.configService.getOtherOptions()["outputFolder"], playlist.getName(), "images", f"album_{track.getAlbumName()}.jpg"))
                    # update the relevant information
                    self.setTrackNameBoxText(track.getDisplayName())
                    # update the author / album data
                    self.setArtistDataText(track.getArtistName() or "unknown artist", track.getAlbumDisplayName() or "unknown album")
        # set the track as no longer downloading
        trackWidget.setDownloading(False)
            
    
    # runs when a playlist track starts downloading
    def _eventPlaylistTrackDownloadStart(self, track:PlaylistTrack, playlist:Playlist, trackIndex:int):
        # get the current track widget
        trackList = self.getTrackWidgetList()
        if trackList:
            trackWidget = trackList[trackIndex]
            trackWidget.setDownloading(True)
    
    # runs when the audio progress changes (updated ~2/sec)
    def _eventAudioTrackProgress(self, progress:float, totalTime:float):
        self.setProgressBarProgress(progress)
        
        # update the seconds counter
        seconds = int(progress * totalTime)
        m, s = divmod(seconds, 60)
        self.setCurrentTrackTimeText(f"{m:02d}:{s:02d}")
    
    def start(self):
        self.logger.info("Starting gui service.")
        # setup event listeners
        self.eventService.subscribeToEvent("PLAYLIST_INITIALIZATION_START", self._eventPlaylistInitializationStart)
        self.eventService.subscribeToEvent("PLAYLIST_INITALIZATION_FINISH", self._eventPlaylistInitialized)
        self.eventService.subscribeToEvent("PLAYLIST_CURRENT_CHANGE", self._eventCurrentPlaylistChange)
        self.eventService.subscribeToEvent("AUDIO_TRACK_START", self._eventAudioTrackStart)
        self.eventService.subscribeToEvent("AUDIO_TRACK_PAUSE", self._eventAudioTrackPause)
        self.eventService.subscribeToEvent("AUDIO_TRACK_RESUME", self._eventAudioTrackResume)
        self.eventService.subscribeToEvent("AUDIO_TRACK_END", self._eventAudioTrackEnd)
        self.eventService.subscribeToEvent("AUDIO_TRACK_PROGRESS", self._eventAudioTrackProgress)
        self.eventService.subscribeToEvent("DOWNLOAD_START_REQUEST", self._eventDownloadStartRequest)
        self.eventService.subscribeToEvent("DOWNLOAD_STOP", self._eventDownloadStop)
        self.eventService.subscribeToEvent("PROGRAM_CLOSE", self._eventProgramClose)
        self.eventService.subscribeToEvent("GUI_MUTE_AUDIO", self._eventGuiMuteAudio)
        self.eventService.subscribeToEvent("GUI_UNMUTE_AUDIO", self._eventGuiUnmuteAudio)
        self.eventService.subscribeToEvent("PLAYLIST_TRACK_DOWNLOAD", self._eventPlaylistTrackDownload)
        self.eventService.subscribeToEvent("PLAYLIST_TRACK_DOWNLOAD_START", self._eventPlaylistTrackDownloadStart)
        # starting up QApplication
        self._QApplication = QApplication([])
        # booting up main window
        self._window = Window(self._mainWindow, self.eventService, self.threadService)

        # setting default volume
        self.setVolumeBarProgress(1)
        
        # stop the loading widget
        self.setLoadingState(False)

        # customizing buttons
        self.setPlayButtonState(True)
        
        # set the default page on startup
        self.loadPagePlaylistSelector()
        
        # show the window
        self._window.show()