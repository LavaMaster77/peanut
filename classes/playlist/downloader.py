from __future__ import annotations

import logging
import yt_dlp
import asyncio
from pathlib import Path
import os
import subprocess
import requests
from multiprocessing.synchronize import Event
from multiprocessing import Queue
from ytmusicapi import YTMusic
from PIL import Image

# import yt-dlp's sanitation
from yt_dlp import utils as yt_dlp_utils

from .playlist import Playlist
from .track import PlaylistTrack

# downloader class for playlists
class PlaylistDownloader():
    
    def __init__(self, logger):
        # initalize download options
       self.downloadOptions = {
        'extract_flat': True,  # Extract only basic information to make it faster
        'force_generic_extractor': True,
        'dump_single_json': True, # Request the data in JSON format
        'flat_playlist': True, # Extract only video IDs and titles from the playlist
        }
       # get logger
       self.logger = logger
       self.ytmusic = YTMusic()
    
    # utility
    
    # sanitize names using yt-dlp's method
    def _sanitizeFilename(self, txt:str):
        return yt_dlp_utils._utils.sanitize_filename(txt, restricted=True)
    
    # file handling
    
    # squares an image. used to turn thumbnails into album covers.
    def _squareImage(self, filePath:str):
        img = Image.open(filePath)
        width, height = img.size
        minDim = min(width, height)
        
        left = (width - minDim) / 2
        top = (height - minDim) / 2
        right = (width + minDim) / 2
        bottom = (height + minDim) / 2

        box = (left, top, right, bottom)
        cropimg = img.crop(box)
        cropimg.save(filePath)
    
    # downloading
    
    def _downloadThumbnail(self, url:str, outputLocation:str):
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(outputLocation, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    
    # download a given video.
    def _downloadVideo(self, ydl: yt_dlp.YoutubeDL, url:str):
        info = ydl.extract_info(url, download=True)
        return info
    
    # converts an audio file to the desired extension (unused, handled by yt-dlp)
    # def _convertAudioFile(self, filePath:str, newPath:str, ffmpegPath:str):
    #     # making new path with extension. extension must have dot
    #     args = [ffmpegPath, "-i", filePath, "-vn", "-y", "-ar", str(44100), "-ac", str(2), "-b:a", "192k", newPath]
    #     result = subprocess.run(args, text=True, check=True, capture_output=True)
    #     # delete old file
    #     os.remove(filePath)
    
    # searches yt music for album data for the given track.
    def _getAlbumData(self, searchTerm:str, trackLength:float, maxVariation:float, playlist:Playlist, imageDownloadFolder:str):
        results = self.ytmusic.search(searchTerm, "songs", None, limit=1, ignore_spelling=True)
        if trackLength == 0:
            self.logger.warning("Track length is 0 seconds, this probably is not correct")
    
        if results:
            mainResult = results[0]
            # if no album, return
            if not mainResult["album"]: self.logger.debug(f"Album Data Request failed for term '{searchTerm}': No album entry present"); return None, None, None, None
            # if this wasn't the artist's own upload, return
            if not mainResult["videoType"] == "MUSIC_VIDEO_TYPE_ATV": self.logger.debug(f"Album Data Request failed for term '{searchTerm}': no videoType entry present"); return None, None, None, None, None
            # if the track length is more than <maxVariation> seconds different than the yt video, return
            if abs(mainResult["duration_seconds"] - trackLength) > maxVariation: 
                self.logger.debug(f"Album Data Request failed for term '{searchTerm}': track lengths do not match up ({mainResult['duration_seconds']}s on yt music vs. {trackLength}, with max variation of {maxVariation}s)"); return None, None, None, None
            albumName = self._sanitizeFilename(mainResult["album"]["name"])
            albumDisplayName = mainResult["album"]["name"]
            albumID = mainResult["album"]["id"]
            artistName = None # will be assigned shortly
            # check to see if the album art is already downloaded
            albums = playlist.getAlbums()
            if not albumName in albums:
                albumData = self.ytmusic.get_album(albumID)
                imageURL = albumData["thumbnails"][-1]["url"]
                # download go brrrrrrrrrr
                self.logger.debug(f"Downloading album image for album '{albumDisplayName}' via youtube music search.")
                self._downloadThumbnail(imageURL, os.path.join(imageDownloadFolder, f"album_{albumName}.jpg"))
                artistName = ", ".join(d["name"] for d in albumData["artists"])
                # save the album to prevent redownloading
                playlist.addAlbumEntry(albumName, {"artist": artistName, "display name:": albumDisplayName})
            else:
                artistName = albums[albumName]["artist"]
            return albumName, albumDisplayName, artistName, mainResult["title"]
        else:
            self.logger.debug(f"Album Data Request failed for term '{searchTerm}': no results found with search term"); return None, None, None, None
    
    # converts an audio file to the desired extension and gets the length of the file. (unused)
    # def _processAudioFile(self, filePath:str, extension:str, track:PlaylistTrack, ffmpegPath:str):
    #     self.logger.info(f"Processing {filePath}...")
    #     # get new path
    #     newPath = str(Path(filePath).with_suffix(extension))
    #     # convert
    #     self._convertAudioFile(filePath, newPath, ffmpegPath)
    #     self.logger.info(f"Finished processing {filePath}")
    #     # mark entry as finished
    #     track.setDownloaded(True)
    
    # downloads the given playlist. should be run in a thread as to not block the main gui.
    def downloadPlaylist(self, playlist:Playlist, downloadOptions, outputExtension:str, 
                         stopEvent:Event, responseQueue:Queue, thumbnailOutput:str, playlistThumbnailLocation:str, useYoutubeMusicAlbums:bool, maxVariation:int, 
                         startIndex:int, maxDownloadAttempts:int):
        name = playlist.getName()
        self.logger.debug(f"Start index: {startIndex}")
        # cache if this download was successful or not
        downloadPlaylistSuccess = True
        stopDownloading = False
        # make the images directory
        os.makedirs(thumbnailOutput, exist_ok=True)
        # replace playlist name with actual name
        downloadOptions["outtmpl"] = downloadOptions["outtmpl"].replace("%(playlist_title)s", name)
        if not playlist.getThumbnailDownloaded():
            self._downloadThumbnail(playlist.getThumbnailURL(), playlistThumbnailLocation)
            playlist.setThumbnailDownloaded(True)
        with yt_dlp.YoutubeDL(downloadOptions) as ydl:
            while not stopDownloading:
                for index, track in enumerate(playlist.getTracks()):
                    # if the index is not the requested start index, skip until it is
                    if index < startIndex: continue
                    
                    # if the current track is ignored, don't try to download it
                    if track.getIgnored(): continue
                    
                    if stopEvent.is_set():
                        stopDownloading = True
                        break
                    if track.getDownloaded():
                        continue
                    
                    # download + processing
                    self.logger.info(f"Downloading video '{track.getDisplayName()}'. Downloaded: {track.getDownloaded()}")
                    responseQueue.put({"action": "TRACK_DOWNLOAD_START", "track": track, "playlistName": playlist.getName(), "downloadIndex": index})
                    
                    # attempt to download video. will try multiple times. if max attempts is -1, then it will try indefinitely.
                    attemptCount = 0
                    info: dict|None = None
                    success = True
                    while True:
                        if (attemptCount == maxDownloadAttempts) and (maxDownloadAttempts != -1):
                            # ran out of attempts
                            success = False
                            break
                        try:
                            info = self._downloadVideo(ydl, track.getVideoURL())
                            if not info:
                                # attempt failed, try again
                                attemptCount += 1
                            else:
                                # attempt succeeded, break
                                break
                        except Exception as e:
                            self.logger.error(f"An unknown error occured while attempting to download the track '{track.getName()}': {e}")
                            downloadPlaylistSuccess = False # mark the playlist as not being fully downloaded
                            attemptCount += 1
                    if not success:
                        self.logger.error(f"Failed to download track '{track.getName()}': ran out of attempts")
                        responseQueue.put({"action": "TRACK_DOWNLOAD_DONE", "track": track, "playlistName": name, "downloadIndex": index, "success": False})
                        continue        
                    
                    # path = ydl.prepare_filename(info)
                    # convert file to specified format (not getting the track length atm)
                    # self._processAudioFile(path, outputExtension, track, ffmpegPath=ffmpegPath)
                    
                    # attempt to get music data
                    autogenVideo = True # whether or not the album data was handled via auto-generated video
                    try:
                        albumName = self._sanitizeFilename(info["album"])
                        albumDisplayName = info["album"]
                        artistName = ", ".join(info["artists"])
                        # check to see if the album was already downloaded
                        if not albumName in playlist.getAlbums():
                            albumImageURL = info["thumbnails"][-1]["url"]
                            self.logger.debug(f"Downloading album image for track '{albumDisplayName}' via auto-generated video.")
                            imgPath = os.path.join(thumbnailOutput, f"album_{albumName}.jpg")
                            self._downloadThumbnail(albumImageURL, imgPath)
                            self._squareImage(imgPath)
                            # square the image
                        track.setAlbumName(albumName)
                        track.setAlbumDisplayName(albumDisplayName)
                        track.setArtistName(artistName)
                    except KeyError:
                        autogenVideo = False
                    
                    if not autogenVideo:
                        # try to get an album cover from youtube music
                        # self.logger.debug(f"Info: {track.toDict()}")
                        trackLength = track.getLength()
                        if trackLength == 0:
                            self.logger.warning(f"track length directly from track is 0. Why? Track dict: {track.toDict()}")
                        albumName, albumDisplayName, artistName, trackName = self._getAlbumData(searchTerm=track.getDisplayName(), trackLength=trackLength, maxVariation=maxVariation, playlist=playlist, imageDownloadFolder=thumbnailOutput)
                        if albumName:
                            track.setAlbumName(albumName)
                            track.setAlbumDisplayName(albumDisplayName)
                            track.setArtistName(artistName)
                            track.setDisplayName(trackName)
                    
                    # mark the track as being downloaded
                    track.setDownloaded(True)
                    # signal the completion of the track download
                    responseQueue.put({"action": "TRACK_DOWNLOAD_DONE", "track": track, "playlistName": name, "downloadIndex": index, "success": True})
                if not stopEvent.is_set():
                    if downloadPlaylistSuccess:
                        # verify download
                        undownloaded = False
                        for track in playlist.getTracks():
                            if not track.getDownloaded():
                                undownloaded = True
                                break
                        if not undownloaded:
                            self.logger.info("Done downloading playlist.")
                            playlist.setDownloaded(True)
                            stopDownloading = True
                        else:
                            startIndex = 0
                    else:
                        # restart the playlist download process
                        downloadPlaylistSuccess = True
    
    # downloads the information for each track in the playlist. NOT supported by async functions.
    def initalizePlaylist(self, playlist:Playlist):
        playlistURL = playlist.getPlaylistURL()
        with yt_dlp.YoutubeDL(self.downloadOptions) as ydl:
            tracks = []
            info_dict = ydl.extract_info(playlistURL, download=False)
            playlist.setName(self._sanitizeFilename(info_dict["title"]))
            playlist.setDisplayName(info_dict["title"])
            if 'entries' in info_dict:
                index = 0
                for track in info_dict['entries']:
                    if track and 'url' in track:
                        index += 1
                        duration = track["duration"]
                        if duration == 0:
                            self.logger.warning(f"Track duration for {track['title']} is 0s which probably is not correct")
                        deleted = track["title"] == "[Deleted video]"
                        playlistTrack = PlaylistTrack(videoURL=track["url"], name=self._sanitizeFilename(track["title"]), displayName=track["title"],
                                                      index=index, length=duration, ignored=deleted)
                        tracks.append(playlistTrack)
            playlist.setTracks(tracks)
            playlist.setLength(len(tracks))
            playlist.setDownloaded(False)
            playlist.setThumbnailURL(info_dict["thumbnails"][-1]["url"])
            self.logger.info(f"Successfully finished initalizing playlist '{playlist.getDisplayName()}'")