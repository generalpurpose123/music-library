import io
import os
import tempfile

import pytest
from mutagen.id3 import ID3, TIT2, TPE1, TALB

from app.models.application.library.library import Library, Song, artist_album_pattern_mp3
from app.models.application.music_file import MusicFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mp3_bytes(title: str, artist: str, album: str) -> bytes:
    """Return minimal MP3 file bytes containing ID3 tags but no audio data."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        tags.add(TALB(encoding=3, text=album))
        tags.save(tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# MusicFile tests
# ---------------------------------------------------------------------------

class TestMusicFileFileName:
    def test_simple_filename(self):
        mf = MusicFile("/some/path/song.mp3")
        assert mf.file_name == "song.mp3"

    def test_nested_path(self):
        mf = MusicFile("/a/b/c/d/track01.mp3")
        assert mf.file_name == "track01.mp3"

    def test_filename_only_no_directory(self):
        mf = MusicFile("song.mp3")
        assert mf.file_name == "song.mp3"

    def test_file_name_with_spaces(self):
        mf = MusicFile("/music/Artist - Album - Title.mp3")
        assert mf.file_name == "Artist - Album - Title.mp3"


# ---------------------------------------------------------------------------
# Library.deduplicate_by tests
# ---------------------------------------------------------------------------

class TestLibraryDeduplicateBy:
    def _make_library(self, songs):
        return Library(songs=list(songs))

    def test_deduplication_removes_duplicates_keeps_first(self):
        s1 = Song(title="Alpha", artist="X", album="Y")
        s2 = Song(title="Alpha", artist="Z", album="W")  # same title, different artist
        s3 = Song(title="Beta", artist="X", album="Y")
        lib = self._make_library([s1, s2, s3])

        lib.deduplicate_by(lambda song: song.title)

        assert len(lib.songs) == 2
        assert lib.songs[0] is s1
        assert lib.songs[1] is s3

    def test_deduplication_no_duplicates_unchanged(self):
        s1 = Song(title="Alpha", artist="X", album="Y")
        s2 = Song(title="Beta", artist="X", album="Y")
        lib = self._make_library([s1, s2])

        lib.deduplicate_by(lambda song: song.title)

        assert len(lib.songs) == 2

    def test_deduplication_returns_self(self):
        lib = Library(songs=[Song(title="A", artist="B", album="C")])
        result = lib.deduplicate_by(lambda song: song.title)
        assert result is lib

    def test_deduplication_by_artist(self):
        s1 = Song(title="T1", artist="Same", album="A")
        s2 = Song(title="T2", artist="Same", album="B")
        s3 = Song(title="T3", artist="Other", album="C")
        lib = self._make_library([s1, s2, s3])

        lib.deduplicate_by(lambda song: song.artist)

        assert len(lib.songs) == 2
        assert lib.songs[0] is s1
        assert lib.songs[1] is s3


# ---------------------------------------------------------------------------
# Library.load_song_from_file tests
# ---------------------------------------------------------------------------

class TestLibraryLoadSongFromFile:
    def _make_temp_mp3(self, title, artist, album):
        mp3_bytes = _make_mp3_bytes(title, artist, album)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(mp3_bytes)
        tmp.close()
        return tmp.name

    def test_loads_tags_correctly(self):
        tmp_path = self._make_temp_mp3("My Song", "My Artist", "My Album")
        try:
            lib = Library(songs=[])
            song = lib.load_song_from_file(tmp_path)

            assert song.title == "My Song"
            assert song.artist == "My Artist"
            assert song.album == "My Album"
        finally:
            os.unlink(tmp_path)

    def test_song_appended_to_library(self):
        tmp_path = self._make_temp_mp3("T", "A", "B")
        try:
            lib = Library(songs=[])
            song = lib.load_song_from_file(tmp_path)

            assert len(lib.songs) == 1
            assert lib.songs[0] is song
        finally:
            os.unlink(tmp_path)

    def test_returns_song_instance(self):
        tmp_path = self._make_temp_mp3("T", "A", "B")
        try:
            lib = Library(songs=[])
            result = lib.load_song_from_file(tmp_path)
            assert isinstance(result, Song)
        finally:
            os.unlink(tmp_path)

    def test_file_bytes_stored_in_song(self):
        mp3_bytes = _make_mp3_bytes("T", "A", "B")
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(mp3_bytes)
        tmp.close()
        try:
            lib = Library(songs=[])
            song = lib.load_song_from_file(tmp.name)
            stored = song._file.read()
            assert stored == mp3_bytes
        finally:
            os.unlink(tmp.name)

    def test_fallback_to_filename_when_no_id3(self):
        """An MP3 with no ID3 header should fall back to filename parsing."""
        # Write bare bytes (not a real ID3 file)
        mp3_bytes = b"\xff\xfb\x90\x00" * 10  # fake MPEG frame sync, no ID3
        tmp = tempfile.NamedTemporaryFile(
            suffix=".mp3", prefix="Artist - Album - Title - ", delete=False
        )
        tmp.write(mp3_bytes)
        tmp.close()
        try:
            lib = Library(songs=[])
            song = lib.load_song_from_file(tmp.name)
            # Should not crash; title should be derived from filename
            assert isinstance(song, Song)
            assert song.title is not None
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Existing smoke test (kept as-is)
# ---------------------------------------------------------------------------

def test_artist_album_pattern_mp3_smoke():
    test_data = Song(
        title="Test Title",
        artist="Test Artist",
        album="Test Album"
    )
    result = artist_album_pattern_mp3(test_data)
    assert test_data.album in result
    assert test_data.artist in result
    assert test_data.title in result
    assert result is not None
    assert result.count(".") == 1

    test_data = Song(
        title="Test Title123",
        artist="Test Artist",
        album="Test Album"
    )
    result = artist_album_pattern_mp3(test_data)
    assert result is not None
    assert result.count(".") == 1
    print("The result is ", result)
