import dataclasses
import os
from typing import Any
import io

from mutagen.id3 import ID3, ID3NoHeaderError


@dataclasses.dataclass
class Song:
    title: str
    artist: str
    album: str
    _file: Any = dataclasses.field(default_factory=lambda: io.BytesIO(b""))

    def save(self, target_path: str):
        with open(target_path, "wb") as out_file:
            with self._file as write_file:
                out_file.write(write_file.read())


@dataclasses.dataclass
class Library:
    songs: list[Song]

    def save_library(self, master_folder_path: str, folder_pattern: callable):
        for song in self.songs:
            target_path = os.path.join(master_folder_path, folder_pattern(song))
            song.save(target_path)

    def load_song_from_file(self, file_path: str) -> Song:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        title = None
        artist = None
        album = None

        try:
            tags = ID3(file_path)
            if "TIT2" in tags:
                title = str(tags["TIT2"])
            if "TPE1" in tags:
                artist = str(tags["TPE1"])
            if "TALB" in tags:
                album = str(tags["TALB"])
        except ID3NoHeaderError:
            pass

        if not title or not artist or not album:
            basename = os.path.basename(file_path)
            name_without_ext = os.path.splitext(basename)[0]
            parts = name_without_ext.split(" - ", 2)
            if len(parts) == 3:
                parsed_artist, parsed_album, parsed_title = parts
            elif len(parts) == 2:
                parsed_artist, parsed_title = parts
                parsed_album = ""
            else:
                parsed_artist = ""
                parsed_album = ""
                parsed_title = name_without_ext

            if not title:
                title = parsed_title
            if not artist:
                artist = parsed_artist
            if not album:
                album = parsed_album

        song = Song(
            title=title,
            artist=artist,
            album=album,
            _file=io.BytesIO(file_bytes),
        )
        self.songs.append(song)
        return song

    def load_songs_from_folder(self, file_path: str) -> list[Song]:
        loaded = []
        for root, _dirs, files in os.walk(file_path):
            for filename in files:
                if filename.lower().endswith(".mp3"):
                    full_path = os.path.join(root, filename)
                    loaded.append(self.load_song_from_file(full_path))
        return loaded

    def deduplicate_by(self, deduplication_criterion: callable) -> "Library":
        seen = {}
        unique_songs = []
        for song in self.songs:
            key = deduplication_criterion(song)
            if key not in seen:
                seen[key] = True
                unique_songs.append(song)
        self.songs = unique_songs
        return self


def artist_album_pattern_mp3(song: Song):
    file_name = f"{song.artist} - {song.title}.mp3"
    file_path = os.path.join(
        song.artist,
        song.album,
        file_name
    )
    full_path = "".join(filter(str.isascii, file_path))
    return full_path
