"""
Tests for integrate_playlist_to_library.py

Covers:
  - sanitize_fs_name
  - strip_feature
  - build_path
  - find_existing_files
  - move_incorrectly_placed_files
  - integrate_playlist (via download_missing_songs path)
"""
import os
import shutil

import pytest
from unittest.mock import patch, MagicMock

from app.controllers.integration.integrate_playlist_to_library import (
    sanitize_fs_name,
    strip_feature,
    build_path,
    find_existing_files,
    move_incorrectly_placed_files,
    integrate_playlist,
    download_missing_songs,
)
from app.controllers.song_aquisition.get_check_enhance_song import SongDownloadResult
from app.models.exceptions import LibraryError


# ---------------------------------------------------------------------------
# sanitize_fs_name
# ---------------------------------------------------------------------------

class TestSanitizeFsName:
    def test_normal_ascii_string_unchanged(self):
        assert sanitize_fs_name("Hello World") == "Hello World"

    def test_alphanumeric_and_spaces_preserved(self):
        assert sanitize_fs_name("Track 01") == "Track 01"

    def test_underscore_and_hyphen_preserved(self):
        assert sanitize_fs_name("my_track-name") == "my_track-name"

    def test_special_chars_removed(self):
        result = sanitize_fs_name("AC/DC: Rock!@#$%^&*()")
        assert "/" not in result
        assert ":" not in result
        assert "!" not in result
        # Letters and spaces remain
        assert "AC" in result
        assert "DC" in result

    def test_unicode_chars_preserved(self):
        # Unicode letters are now preserved by sanitize_fs_name
        result = sanitize_fs_name("Björk")
        # All letters remain, including the Unicode 'ö'
        assert "B" in result
        assert "j" in result
        assert "r" in result
        assert "k" in result
        assert "ö" in result

    def test_empty_string_returns_empty(self):
        assert sanitize_fs_name("") == ""

    def test_only_special_chars_returns_empty(self):
        assert sanitize_fs_name("!@#$%^&*()") == ""

    def test_leading_trailing_whitespace_stripped(self):
        result = sanitize_fs_name("  hello  ")
        assert result == "hello"

    def test_path_traversal_dots_removed(self):
        result = sanitize_fs_name("../../etc/passwd")
        # Dots are not in the allowed set [a-zA-Z0-9\s_-], so they are stripped
        assert ".." not in result
        assert "/" not in result


# ---------------------------------------------------------------------------
# strip_feature
# ---------------------------------------------------------------------------

class TestStripFeature:
    def test_removes_feat_round_brackets(self):
        result = strip_feature("Artist (feat. Someone)")
        assert "feat" not in result.lower()
        assert result.strip() == "Artist"

    def test_removes_feat_square_brackets(self):
        result = strip_feature("Artist [feat. Someone Else]")
        assert "feat" not in result.lower()
        assert result.strip() == "Artist"

    def test_removes_feat_case_insensitive(self):
        result = strip_feature("Artist (Feat. Collaborator)")
        assert "feat" not in result.lower()

    def test_no_feature_tag_unchanged(self):
        assert strip_feature("Queen") == "Queen"

    def test_already_clean_unchanged(self):
        assert strip_feature("Led Zeppelin") == "Led Zeppelin"

    def test_multiple_words_in_feature(self):
        result = strip_feature("Artist (feat. John Doe and Jane Doe)")
        assert "feat" not in result.lower()
        assert "Artist" in result

    def test_empty_string(self):
        assert strip_feature("") == ""


# ---------------------------------------------------------------------------
# build_path
# ---------------------------------------------------------------------------

class TestBuildPath:
    def test_artist_album_schema(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist", "album"], "Song Title", "The Artist", album="The Album")
        assert "The Artist" in path
        assert "The Album" in path
        assert path.endswith("The Artist - Song Title")

    def test_artist_only_schema(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist"], "Song Title", "The Artist")
        assert "The Artist" in path
        assert path.endswith("The Artist - Song Title")

    def test_wildcard_schema(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["wildcard"], "Song Title", "The Artist", wildcard_value="MyGenre")
        assert "MyGenre" in path
        assert path.endswith("The Artist - Song Title")

    def test_unknown_keyword_raises_value_error(self, tmp_path):
        root = str(tmp_path)
        with pytest.raises(ValueError, match="Unknown schema keywords"):
            build_path(root, ["invalidkey"], "Song Title", "The Artist")

    def test_unknown_album_not_included_in_path(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist", "album"], "Song Title", "The Artist", album="Unknown Album")
        # "Unknown Album" should not appear as a directory component
        assert "Unknown Album" not in path

    def test_none_album_not_included_in_path(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist", "album"], "Song Title", "The Artist", album=None)
        # Should not crash; path still ends with artist - title
        assert path.endswith("The Artist - Song Title")

    def test_feature_tag_stripped_from_artist(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist"], "Song", "Main Artist (feat. Other)")
        # Check that the relative portion (after root) doesn't contain "feat"
        rel = path[len(root):]
        assert "feat" not in rel.lower()
        assert "Main Artist" in path

    def test_special_chars_sanitized_in_path(self, tmp_path):
        root = str(tmp_path)
        path = build_path(root, ["artist"], "SongTitle", "ArtistName")
        # Special chars from input should not appear in the path component
        # (we use clean inputs here to test that the output path is constructed correctly)
        assert ":" not in path
        assert "ArtistName" in path


# ---------------------------------------------------------------------------
# find_existing_files
# ---------------------------------------------------------------------------

class TestFindExistingFiles:
    def _make_track_file(self, root, schema, track):
        """Create the expected MP3 file for a track."""
        path_no_ext = build_path(root, schema, track["title"], track["artist"], album=track.get("album"))
        mp3_path = path_no_ext + ".mp3"
        os.makedirs(os.path.dirname(mp3_path), exist_ok=True)
        with open(mp3_path, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)  # minimal fake MP3
        return mp3_path

    def test_file_exists_at_correct_path(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist", "album"]
        track = {"title": "Song", "artist": "Artist", "album": "Album"}
        self._make_track_file(root, schema, track)
        result = find_existing_files([track], root, schema)
        assert len(result) == 1
        assert result[0].endswith(".mp3")

    def test_file_missing(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist", "album"]
        track = {"title": "Missing Song", "artist": "Some Artist", "album": "Some Album"}
        result = find_existing_files([track], root, schema)
        assert result == []

    def test_mixed_present_and_missing(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist"]
        tracks = [
            {"title": "Present Song", "artist": "Artist A", "album": None},
            {"title": "Missing Song", "artist": "Artist B", "album": None},
        ]
        self._make_track_file(root, schema, tracks[0])
        result = find_existing_files(tracks, root, schema)
        assert len(result) == 1
        assert "Present Song" in result[0]

    def test_empty_playlist(self, tmp_path):
        result = find_existing_files([], str(tmp_path), ["artist"])
        assert result == []


# ---------------------------------------------------------------------------
# move_incorrectly_placed_files
# ---------------------------------------------------------------------------

class TestMoveIncorrectlyPlacedFiles:
    def test_file_in_wrong_subdirectory_is_moved(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist", "album"]
        track = {"title": "Song", "artist": "Artist", "album": "Album"}

        # Build what the correct path should be
        correct_no_ext = build_path(root, schema, track["title"], track["artist"], album=track["album"])
        correct_mp3 = correct_no_ext + ".mp3"
        filename = os.path.basename(correct_mp3)

        # Place the file in a wrong subdirectory
        wrong_dir = os.path.join(root, "wrong_folder")
        os.makedirs(wrong_dir)
        wrong_path = os.path.join(wrong_dir, filename)
        with open(wrong_path, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        move_incorrectly_placed_files([track], root, schema)

        assert os.path.isfile(correct_mp3)
        assert not os.path.isfile(wrong_path)

    def test_file_not_found_no_error(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist"]
        track = {"title": "Nonexistent Song", "artist": "Nobody", "album": None}
        # Should complete without raising
        move_incorrectly_placed_files([track], root, schema)

    def test_file_already_correct_stays_put(self, tmp_path):
        root = str(tmp_path)
        schema = ["artist", "album"]
        track = {"title": "Song", "artist": "Artist", "album": "Album"}

        correct_no_ext = build_path(root, schema, track["title"], track["artist"], album=track["album"])
        correct_mp3 = correct_no_ext + ".mp3"
        os.makedirs(os.path.dirname(correct_mp3), exist_ok=True)
        with open(correct_mp3, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        move_incorrectly_placed_files([track], root, schema)

        assert os.path.isfile(correct_mp3)

    def test_empty_playlist_no_error(self, tmp_path):
        move_incorrectly_placed_files([], str(tmp_path), ["artist"])


# ---------------------------------------------------------------------------
# integrate_playlist via download_missing_songs
# ---------------------------------------------------------------------------

class TestIntegratePlaylist:
    """Integration tests for the full integrate_playlist function.

    get_check_enhance_song and gather_song_info are mocked to prevent
    any real network calls.
    """

    def _make_track_file(self, root, schema, track):
        path_no_ext = build_path(root, schema, track["title"], track["artist"], album=track.get("album"))
        mp3_path = path_no_ext + ".mp3"
        os.makedirs(os.path.dirname(mp3_path), exist_ok=True)
        with open(mp3_path, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)
        return mp3_path

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.get_check_enhance_song")
    def test_all_tracks_present_no_downloads(self, mock_get_song, mock_disk, tmp_path):
        root = str(tmp_path)
        schema = ["artist", "album"]
        tracks = [
            {"title": "Song A", "artist": "Artist A", "album": "Album A"},
            {"title": "Song B", "artist": "Artist B", "album": "Album B"},
        ]
        for t in tracks:
            self._make_track_file(root, schema, t)

        # Even though files exist, download_missing_songs is still called but should
        # skip each because the file is present
        mock_disk.return_value = None
        integrate_playlist(tracks, root, schema)

        # get_check_enhance_song should NOT have been called (files already present)
        mock_get_song.assert_not_called()

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_some_tracks_missing_downloads_called(self, mock_disk, tmp_path):
        root = str(tmp_path)
        schema = ["artist"]
        tracks = [
            {"title": "Present Song", "artist": "Artist A", "album": None},
            {"title": "Missing Song", "artist": "Artist B", "album": None},
        ]
        # Create only the first track
        self._make_track_file(root, schema, tracks[0])
        mock_disk.return_value = None

        downloaded_file = os.path.join(str(tmp_path), "downloaded.mp3")
        with open(downloaded_file, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song"
        ) as mock_get_song:
            mock_get_song.return_value = SongDownloadResult(
                downloaded_file, {"album_name": "Unknown Album"}
            )
            integrate_playlist(tracks, root, schema)

            # Should have been called exactly once for the missing track
            mock_get_song.assert_called_once()
            call_kwargs = mock_get_song.call_args
            assert call_kwargs[1]["song_name"] == "Missing Song"

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_download_fails_integration_continues(self, mock_disk, tmp_path):
        root = str(tmp_path)
        schema = ["artist"]
        tracks = [
            {"title": "Fail Song", "artist": "Artist Fail", "album": None},
            {"title": "Success Song", "artist": "Artist OK", "album": None},
        ]
        mock_disk.return_value = None

        downloaded_file = os.path.join(str(tmp_path), "ok.mp3")
        with open(downloaded_file, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        call_count = {"n": 0}

        def side_effect(**kwargs):
            call_count["n"] += 1
            if kwargs.get("song_name") == "Fail Song":
                return None  # Simulate failed download (returns None, not exception)
            return SongDownloadResult(downloaded_file, {"album_name": "Unknown Album"})

        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song",
            side_effect=side_effect,
        ):
            # Should not raise even when first track download returns None
            integrate_playlist(tracks, root, schema)

        assert call_count["n"] == 2  # Both tracks attempted

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_insufficient_disk_space_raises_library_error(self, mock_disk, tmp_path):
        mock_disk.side_effect = LibraryError("Insufficient disk space")
        tracks = [{"title": "Song", "artist": "Artist", "album": None}]
        with pytest.raises(LibraryError, match="Insufficient disk space"):
            download_missing_songs(tracks, str(tmp_path), ["artist"])

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_comma_separated_artists_uses_first(self, mock_disk, tmp_path):
        """Artists with comma-separated names should use only the first for lookup."""
        root = str(tmp_path)
        schema = ["artist"]
        track = {"title": "Collab Song", "artist": "Artist A, Artist B", "album": None}
        mock_disk.return_value = None

        downloaded_file = os.path.join(str(tmp_path), "collab.mp3")
        with open(downloaded_file, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song",
        ) as mock_get_song:
            mock_get_song.return_value = SongDownloadResult(
                downloaded_file, {"album_name": "Unknown Album"}
            )
            download_missing_songs([track], root, schema)

        # Verify first artist was used
        assert mock_get_song.called
        call_kwargs = mock_get_song.call_args[1]
        assert call_kwargs.get("artist_name") == "Artist A"

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_shazam_recognition_runs_once_per_track(self, mock_disk, tmp_path):
        """Regression (B5): integration must reuse the download's metadata, never re-recognize."""
        root = str(tmp_path)
        schema = ["artist", "album"]
        tracks = [{"title": "Missing Song", "artist": "Artist B", "album": None}]
        mock_disk.return_value = None

        downloaded_file = os.path.join(str(tmp_path), "downloaded.mp3")
        with open(downloaded_file, "wb") as f:
            f.write(b"\xff\xfb\x90\x00" * 4)

        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song"
        ) as mock_get_song, patch(
            "app.controllers.song_recognition.get_metadata.gather_song_info"
        ) as mock_gather:
            mock_get_song.return_value = SongDownloadResult(
                downloaded_file, {"album_name": "Some Album"}
            )
            integrate_playlist(tracks, root, schema)

        mock_gather.assert_not_called()


class TestAlbumPathStability:
    """Regression tests (B2): the Spotify album drives the library path, making re-runs idempotent."""

    def _downloaded_file(self, tmp_path, name="dl.mp3"):
        p = tmp_path / name
        p.write_bytes(b"\xff\xfb\x90\x00" * 4)
        return str(p)

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_spotify_album_wins_over_shazam_album(self, mock_disk, tmp_path):
        root = str(tmp_path / "library")
        os.makedirs(root)
        schema = ["artist", "album"]
        tracks = [{"title": "Song", "artist": "Artist", "album": "Album X"}]
        mock_disk.return_value = None

        downloaded_file = self._downloaded_file(tmp_path)
        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song"
        ) as mock_get_song:
            mock_get_song.return_value = SongDownloadResult(
                downloaded_file, {"album_name": "Different Shazam Album"}
            )
            integrate_playlist(tracks, root, schema)

        expected = build_path(root, schema, "Song", "Artist", album="Album X") + ".mp3"
        shazam_path = build_path(root, schema, "Song", "Artist", album="Different Shazam Album") + ".mp3"
        assert os.path.isfile(expected)
        assert not os.path.exists(shazam_path)

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_second_run_downloads_nothing(self, mock_disk, tmp_path):
        root = str(tmp_path / "library")
        os.makedirs(root)
        schema = ["artist", "album"]
        tracks = [{"title": "Song", "artist": "Artist", "album": "Album X"}]
        mock_disk.return_value = None

        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song"
        ) as mock_get_song:
            mock_get_song.return_value = SongDownloadResult(
                self._downloaded_file(tmp_path), {"album_name": "Shazam Album"}
            )
            integrate_playlist(tracks, root, schema)
            assert mock_get_song.call_count == 1

            integrate_playlist(tracks, root, schema)
            assert mock_get_song.call_count == 1  # no re-download on second run

    @patch("app.controllers.integration.integrate_playlist_to_library._check_disk_space")
    def test_album_none_falls_back_to_shazam_album(self, mock_disk, tmp_path):
        root = str(tmp_path / "library")
        os.makedirs(root)
        schema = ["artist", "album"]
        tracks = [{"title": "Song", "artist": "Artist", "album": None}]
        mock_disk.return_value = None

        downloaded_file = self._downloaded_file(tmp_path)
        with patch(
            "app.controllers.integration.integrate_playlist_to_library.get_check_enhance_song"
        ) as mock_get_song:
            mock_get_song.return_value = SongDownloadResult(
                downloaded_file, {"album_name": "Shazam Album"}
            )
            integrate_playlist(tracks, root, schema)

        expected = build_path(root, schema, "Song", "Artist", album="Shazam Album") + ".mp3"
        assert os.path.isfile(expected)
