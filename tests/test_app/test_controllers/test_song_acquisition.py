"""
Tests for get_check_enhance_song.py and yt_dlp_downloader.py

All network calls are mocked — no real YouTube requests are made.
"""
import os
import pytest
from unittest.mock import patch, MagicMock, call

from app.controllers.song_aquisition.get_check_enhance_song import (
    search_youtube_via_yt_dlp,
    get_check_enhance_song,
)
from app.controllers.song_aquisition.youtube.yt_dlp_downloader import (
    download_audio_from_youtube,
)
from app.models.exceptions import DownloadError


# ---------------------------------------------------------------------------
# search_youtube_via_yt_dlp
# ---------------------------------------------------------------------------

class TestSearchYoutubeViaYtDlp:
    def _make_entry(self, url):
        return {"webpage_url": url}

    @patch("app.controllers.song_aquisition.get_check_enhance_song.yt_dlp.YoutubeDL")
    def test_returns_list_of_urls(self, mock_ydl_cls):
        entries = [
            self._make_entry("https://youtube.com/watch?v=aaa"),
            self._make_entry("https://youtube.com/watch?v=bbb"),
        ]
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": entries}
        mock_ydl_cls.return_value = mock_ydl

        result = search_youtube_via_yt_dlp("Artist", "Song")

        assert result == [
            "https://youtube.com/watch?v=aaa",
            "https://youtube.com/watch?v=bbb",
        ]

    @patch("app.controllers.song_aquisition.get_check_enhance_song.yt_dlp.YoutubeDL")
    def test_empty_entries_returns_empty_list(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl_cls.return_value = mock_ydl

        result = search_youtube_via_yt_dlp("Artist", "Song")

        assert result == []

    @patch("app.controllers.song_aquisition.get_check_enhance_song.yt_dlp.YoutubeDL")
    def test_yt_dlp_exception_returns_empty_list(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("Network timeout")
        mock_ydl_cls.return_value = mock_ydl

        result = search_youtube_via_yt_dlp("Artist", "Song")

        assert result == []

    @patch("app.controllers.song_aquisition.get_check_enhance_song.yt_dlp.YoutubeDL")
    def test_entries_with_none_url_are_skipped(self, mock_ydl_cls):
        entries = [
            {"webpage_url": None},
            {"webpage_url": "https://youtube.com/watch?v=good"},
        ]
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": entries}
        mock_ydl_cls.return_value = mock_ydl

        result = search_youtube_via_yt_dlp("Artist", "Song")

        assert result == ["https://youtube.com/watch?v=good"]

    @patch("app.controllers.song_aquisition.get_check_enhance_song.yt_dlp.YoutubeDL")
    def test_lyrics_added_to_query_by_default(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl_cls.return_value = mock_ydl

        search_youtube_via_yt_dlp("Queen", "Bohemian Rhapsody")

        call_args = mock_ydl.extract_info.call_args[0][0]
        assert "lyrics" in call_args.lower()
        assert "Queen" in call_args
        assert "Bohemian Rhapsody" in call_args


# ---------------------------------------------------------------------------
# get_check_enhance_song
# ---------------------------------------------------------------------------

class TestGetCheckEnhanceSong:
    def _make_dummy_mp3(self, tmp_path, name="track.mp3"):
        p = tmp_path / name
        p.write_bytes(b"\xff\xfb\x90\x00" * 4)
        return str(p)

    @patch("app.controllers.song_aquisition.get_check_enhance_song.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.asyncio.run")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.download_audio_from_youtube")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_success_path_returns_file_path(
        self, mock_search, mock_download, mock_run, mock_attach, tmp_path
    ):
        mp3_path = self._make_dummy_mp3(tmp_path)
        mock_search.return_value = ["https://youtube.com/watch?v=aaa"]
        mock_download.return_value = mp3_path
        mock_run.return_value = {
            "artist_name": "Queen",
            "song_name": "Bohemian Rhapsody",
            "album_name": "A Night at the Opera",
        }

        result = get_check_enhance_song(
            artist_name="Queen",
            song_name="Bohemian Rhapsody",
            output_directory=str(tmp_path),
        )

        expected = str(tmp_path / "Queen - Bohemian Rhapsody.mp3")
        assert result == expected
        assert not os.path.isfile(mp3_path)  # renamed to canonical form
        mock_attach.assert_called_once()

    @patch("app.controllers.song_aquisition.get_check_enhance_song.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.asyncio.run")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.download_audio_from_youtube")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_wrong_recognition_first_url_retries_second(
        self, mock_search, mock_download, mock_run, mock_attach, tmp_path
    ):
        mp3_wrong = self._make_dummy_mp3(tmp_path, "wrong.mp3")
        mp3_right = self._make_dummy_mp3(tmp_path, "right.mp3")

        mock_search.return_value = [
            "https://youtube.com/watch?v=wrong",
            "https://youtube.com/watch?v=right",
        ]
        mock_download.side_effect = [mp3_wrong, mp3_right]
        mock_run.side_effect = [
            # First call: wrong track
            {"artist_name": "Wrong Artist", "song_name": "Wrong Song"},
            # Second call: correct track
            {"artist_name": "Queen", "song_name": "Bohemian Rhapsody"},
        ]

        result = get_check_enhance_song(
            artist_name="Queen",
            song_name="Bohemian Rhapsody",
            output_directory=str(tmp_path),
            max_retry=3,
        )

        expected = str(tmp_path / "Queen - Bohemian Rhapsody.mp3")
        assert result == expected
        assert not os.path.isfile(mp3_wrong)  # Wrong file was deleted

    @patch("app.controllers.song_aquisition.get_check_enhance_song.asyncio.run")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.download_audio_from_youtube")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_all_urls_fail_recognition_raises_download_error(
        self, mock_search, mock_download, mock_run, tmp_path
    ):
        mp3_path = self._make_dummy_mp3(tmp_path, "bad.mp3")
        mock_search.return_value = ["https://youtube.com/watch?v=a"] * 3
        mock_download.return_value = mp3_path
        mock_run.return_value = {
            "artist_name": "Wrong Artist",
            "song_name": "Wrong Song",
        }

        with pytest.raises(DownloadError):
            get_check_enhance_song(
                artist_name="Queen",
                song_name="Bohemian Rhapsody",
                output_directory=str(tmp_path),
                max_retry=3,
            )

    @patch("app.controllers.song_aquisition.get_check_enhance_song.asyncio.run")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.download_audio_from_youtube")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_download_exception_skips_to_next_url(
        self, mock_search, mock_download, mock_run, tmp_path
    ):
        mp3_good = self._make_dummy_mp3(tmp_path, "good.mp3")
        mock_search.return_value = [
            "https://youtube.com/watch?v=fail",
            "https://youtube.com/watch?v=good",
        ]
        mock_download.side_effect = [Exception("Download failed"), mp3_good]
        mock_run.return_value = {
            "artist_name": "Queen",
            "song_name": "Bohemian Rhapsody",
        }

        with patch("app.controllers.song_aquisition.get_check_enhance_song.attach_id3_metadata"):
            result = get_check_enhance_song(
                artist_name="Queen",
                song_name="Bohemian Rhapsody",
                output_directory=str(tmp_path),
                max_retry=3,
            )

        expected = str(tmp_path / "Queen - Bohemian Rhapsody.mp3")
        assert result == expected

    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_no_youtube_results_raises_download_error(self, mock_search, tmp_path):
        mock_search.return_value = []

        with pytest.raises(DownloadError, match="No YouTube results found"):
            get_check_enhance_song(
                artist_name="Unknown",
                song_name="Unknown",
                output_directory=str(tmp_path),
            )

    @patch("app.controllers.song_aquisition.get_check_enhance_song.asyncio.run")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.download_audio_from_youtube")
    @patch("app.controllers.song_aquisition.get_check_enhance_song.search_youtube_via_yt_dlp")
    def test_shazam_exception_skips_to_next_url(
        self, mock_search, mock_download, mock_run, tmp_path
    ):
        mp3_a = self._make_dummy_mp3(tmp_path, "a.mp3")
        mp3_b = self._make_dummy_mp3(tmp_path, "b.mp3")
        mock_search.return_value = [
            "https://youtube.com/watch?v=a",
            "https://youtube.com/watch?v=b",
        ]
        mock_download.side_effect = [mp3_a, mp3_b]
        mock_run.side_effect = [
            Exception("Shazam down"),
            {"artist_name": "Queen", "song_name": "Bohemian Rhapsody"},
        ]

        with patch("app.controllers.song_aquisition.get_check_enhance_song.attach_id3_metadata"):
            result = get_check_enhance_song(
                artist_name="Queen",
                song_name="Bohemian Rhapsody",
                output_directory=str(tmp_path),
                max_retry=3,
            )

        expected = str(tmp_path / "Queen - Bohemian Rhapsody.mp3")
        assert result == expected


# ---------------------------------------------------------------------------
# download_audio_from_youtube
# ---------------------------------------------------------------------------

class TestDownloadAudioFromYoutube:
    @patch("app.controllers.song_aquisition.youtube.yt_dlp_downloader.yt_dlp.YoutubeDL")
    def test_successful_download_returns_mp3_path(self, mock_ydl_cls, tmp_path):
        output_dir = str(tmp_path)
        expected_mp3 = os.path.join(output_dir, "My Video.mp3")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"title": "My Video", "ext": "webm"}
        mock_ydl.prepare_filename.return_value = os.path.join(output_dir, "My Video.webm")
        mock_ydl_cls.return_value = mock_ydl

        result = download_audio_from_youtube("https://youtube.com/watch?v=abc", output_dir)

        assert result == expected_mp3

    @patch("app.controllers.song_aquisition.youtube.yt_dlp_downloader.yt_dlp.YoutubeDL")
    def test_custom_filename_used_in_outtmpl(self, mock_ydl_cls, tmp_path):
        output_dir = str(tmp_path)
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {}
        mock_ydl.prepare_filename.return_value = os.path.join(output_dir, "custom_name.webm")
        mock_ydl_cls.return_value = mock_ydl

        result = download_audio_from_youtube(
            "https://youtube.com/watch?v=abc", output_dir, output_filename="custom_name"
        )

        assert result == os.path.join(output_dir, "custom_name.mp3")
        # Check outtmpl contains custom_name
        ydl_opts_used = mock_ydl_cls.call_args[0][0]
        assert "custom_name" in ydl_opts_used["outtmpl"]

    def test_missing_output_directory_raises_file_not_found(self, tmp_path):
        nonexistent_dir = str(tmp_path / "does_not_exist")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            download_audio_from_youtube("https://youtube.com/watch?v=abc", nonexistent_dir)

    @patch("app.controllers.song_aquisition.youtube.yt_dlp_downloader.yt_dlp.YoutubeDL")
    def test_yt_dlp_exception_propagates(self, mock_ydl_cls, tmp_path):
        output_dir = str(tmp_path)
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("yt-dlp internal error")
        mock_ydl_cls.return_value = mock_ydl

        with pytest.raises(Exception, match="yt-dlp internal error"):
            download_audio_from_youtube("https://youtube.com/watch?v=abc", output_dir)


# ---------------------------------------------------------------------------
# _rename_to_recognized
# ---------------------------------------------------------------------------

class TestRenameToRecognized:
    def test_renames_to_sanitized_canonical_name(self, tmp_path):
        from app.controllers.song_aquisition.get_check_enhance_song import _rename_to_recognized
        p = tmp_path / "Madonna - La Isla Bonita (Lyrics).mp3"
        p.write_bytes(b"\xff\xfb\x90\x00")

        result = _rename_to_recognized(str(p), "Madonna", "La Isla Bonita")

        assert result == str(tmp_path / "Madonna - La Isla Bonita.mp3")
        assert os.path.isfile(result)
        assert not p.exists()

    def test_strips_featured_artists_and_unsafe_chars(self, tmp_path):
        from app.controllers.song_aquisition.get_check_enhance_song import _rename_to_recognized
        p = tmp_path / "video title.mp3"
        p.write_bytes(b"\xff\xfb\x90\x00")

        result = _rename_to_recognized(
            str(p), "Kanye West (feat. Young Jeezy)", "Can't Tell Me Nothing?"
        )

        assert result == str(tmp_path / "Kanye West - Cant Tell Me Nothing.mp3")

    def test_noop_when_already_canonical(self, tmp_path):
        from app.controllers.song_aquisition.get_check_enhance_song import _rename_to_recognized
        p = tmp_path / "Queen - Bohemian Rhapsody.mp3"
        p.write_bytes(b"\xff\xfb\x90\x00")

        result = _rename_to_recognized(str(p), "Queen", "Bohemian Rhapsody")

        assert result == str(p)
        assert p.exists()

    def test_overwrites_existing_duplicate(self, tmp_path):
        from app.controllers.song_aquisition.get_check_enhance_song import _rename_to_recognized
        old = tmp_path / "Queen - Bohemian Rhapsody.mp3"
        old.write_bytes(b"old")
        fresh = tmp_path / "fresh download.mp3"
        fresh.write_bytes(b"fresh")

        result = _rename_to_recognized(str(fresh), "Queen", "Bohemian Rhapsody")

        assert result == str(old)
        assert old.read_bytes() == b"fresh"
        assert not fresh.exists()
