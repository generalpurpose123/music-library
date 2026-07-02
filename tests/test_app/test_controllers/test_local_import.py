"""Tests for the local-import provider (Phase E). No network."""
import os

from mutagen.id3 import ID3, TIT2, TPE1, TALB

from app.controllers.song_aquisition.providers.local_import import LocalImportProvider


def _make_tagged_mp3(folder, fname, title, artist, album="Owned Album"):
    path = os.path.join(folder, fname)
    with open(path, "wb") as f:
        f.write(b"\xff\xfb\x90\x00" * 64)
    tags = ID3()
    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags["TPE1"] = TPE1(encoding=3, text=artist)
    tags["TALB"] = TALB(encoding=3, text=album)
    tags.save(path, v2_version=3)
    return path


class TestLocalImportProvider:
    def test_no_source_folder_is_a_miss(self, tmp_path):
        assert LocalImportProvider(source_folder="").acquire("A", "B", None, str(tmp_path)) is None

    def test_match_is_copied(self, tmp_path):
        src = tmp_path / "owned"
        src.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        _make_tagged_mp3(str(src), "song.mp3", "Bohemian Rhapsody", "Queen")

        result = LocalImportProvider(source_folder=str(src)).acquire(
            "Queen", "Bohemian Rhapsody", None, str(out)
        )

        assert result is not None
        assert os.path.isfile(result.path)
        assert os.path.dirname(result.path) == str(out)  # copied into output dir
        assert os.path.isfile(os.path.join(str(src), "song.mp3"))  # original untouched
        assert result.metadata["album_name"] == "Owned Album"

    def test_decorated_request_matches_owned_file(self, tmp_path):
        src = tmp_path / "owned"
        src.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        _make_tagged_mp3(str(src), "song.mp3", "Blinding Lights", "The Weeknd")

        result = LocalImportProvider(source_folder=str(src)).acquire(
            "The Weeknd", "Blinding Lights - Remastered 2020", None, str(out)
        )
        assert result is not None

    def test_no_match_is_a_miss(self, tmp_path):
        src = tmp_path / "owned"
        src.mkdir()
        out = tmp_path / "out"
        out.mkdir()
        _make_tagged_mp3(str(src), "song.mp3", "Some Other Song", "Other Artist")

        result = LocalImportProvider(source_folder=str(src)).acquire(
            "Queen", "Bohemian Rhapsody", None, str(out)
        )
        assert result is None
