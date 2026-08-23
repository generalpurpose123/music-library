"""
Tests for get_metadata.py (gather_song_info) and metadata_attacher.py (attach_id3_metadata).

All async tests use pytest-asyncio. All network calls (Shazam, requests) are mocked.
"""
import io
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from mutagen import MutagenError

from app.controllers.song_recognition.get_metadata import gather_song_info
from app.controllers.song_file_controller.metadata_attacher import attach_id3_metadata
from app.models.exceptions import RecognitionError


# ---------------------------------------------------------------------------
# gather_song_info (async)
# ---------------------------------------------------------------------------

def _build_shazam_response(
    title="Test Song",
    artist="Test Artist",
    album="Test Album",
    year="2020",
    lyrics_lines=None,
    cover_url="http://example.com/cover.jpg",
):
    response = {
        "track": {
            "title": title,
            "subtitle": artist,
            "images": {"coverarthq": cover_url} if cover_url else {},
            "sections": [],
        }
    }
    song_metadata = [{"title": "Album", "text": album}]
    if year:
        song_metadata.append({"title": "Released", "text": year})
    response["track"]["sections"].append({"type": "SONG", "metadata": song_metadata})
    if lyrics_lines is not None:
        response["track"]["sections"].append({"type": "LYRICS", "text": lyrics_lines})
    return response


class TestGatherSongInfo:
    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_success_extracts_all_fields(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(
            lyrics_lines=["Line 1", "Line 2"],
            cover_url="http://example.com/art.jpg",
        )
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam

        cover_response = MagicMock()
        cover_response.content = b"\x89PNG\r\n\x1a\n"  # Fake PNG bytes
        cover_response.raise_for_status = MagicMock()
        mock_requests_get.return_value = cover_response

        result = await gather_song_info("/fake/path.mp3")

        assert result["song_name"] == "Test Song"
        assert result["artist_name"] == "Test Artist"
        assert result["album_name"] == "Test Album"
        assert result["optional_metadata"]["year"] == "2020"
        assert result["lyrics"] == "Line 1\nLine 2"
        assert isinstance(result["album_art_file"], io.BytesIO)

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_missing_title_raises_recognition_error(self, mock_shazam_cls):
        resp = {"track": {"subtitle": "Artist", "sections": []}}
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = resp
        mock_shazam_cls.return_value = mock_shazam

        with pytest.raises(RecognitionError, match="required metadata"):
            await gather_song_info("/fake/path.mp3")

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_missing_artist_raises_recognition_error(self, mock_shazam_cls):
        resp = {"track": {"title": "Song", "sections": []}}
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = resp
        mock_shazam_cls.return_value = mock_shazam

        with pytest.raises(RecognitionError, match="required metadata"):
            await gather_song_info("/fake/path.mp3")

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_album_missing_falls_back_to_unknown(self, mock_shazam_cls, mock_requests_get):
        # No album in sections
        resp = {
            "track": {
                "title": "Song",
                "subtitle": "Artist",
                "images": {},
                "sections": [{"type": "SONG", "metadata": []}],
            }
        }
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = resp
        mock_shazam_cls.return_value = mock_shazam
        mock_requests_get.return_value = MagicMock(content=b"", raise_for_status=MagicMock())

        result = await gather_song_info("/fake/path.mp3")

        assert result["album_name"] == "Unknown Album"

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_lyrics_from_shazam_used_directly(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(lyrics_lines=["Shazam Line 1", "Shazam Line 2"])
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam
        mock_requests_get.return_value = MagicMock(content=b"", raise_for_status=MagicMock())

        result = await gather_song_info("/fake/path.mp3")

        assert result["lyrics"] == "Shazam Line 1\nShazam Line 2"

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.fetch_lyrics_from_lyrics_ovh")
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_lyrics_fallback_to_lyrics_ovh(
        self, mock_shazam_cls, mock_requests_get, mock_fetch_ovh
    ):
        # Shazam has no LYRICS section
        shazam_resp = _build_shazam_response(lyrics_lines=None)
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam
        mock_requests_get.return_value = MagicMock(content=b"", raise_for_status=MagicMock())
        mock_fetch_ovh.return_value = "Fallback lyrics from ovh"

        result = await gather_song_info("/fake/path.mp3")

        assert result["lyrics"] == "Fallback lyrics from ovh"
        mock_fetch_ovh.assert_called_once_with("Test Artist", "Test Song")

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.fetch_lyrics_second_source")
    @patch("app.controllers.song_recognition.get_metadata.fetch_lyrics_from_lyrics_ovh")
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_lyrics_none_when_all_sources_fail(
        self, mock_shazam_cls, mock_requests_get, mock_ovh, mock_second
    ):
        shazam_resp = _build_shazam_response(lyrics_lines=None)
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam
        mock_requests_get.return_value = MagicMock(content=b"", raise_for_status=MagicMock())
        mock_ovh.return_value = None
        mock_second.return_value = None

        result = await gather_song_info("/fake/path.mp3")

        assert result["lyrics"] is None

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_album_art_url_present_returns_bytes_io(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(cover_url="http://example.com/art.jpg")
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam

        img_bytes = b"\xff\xd8\xff"  # JPEG magic bytes
        art_response = MagicMock()
        art_response.content = img_bytes
        art_response.raise_for_status = MagicMock()
        mock_requests_get.return_value = art_response

        result = await gather_song_info("/fake/path.mp3")

        assert isinstance(result["album_art_file"], io.BytesIO)
        assert result["album_art_file"].read() == img_bytes

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_album_art_download_failure_returns_none(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(cover_url="http://example.com/art.jpg")
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam

        import requests as _requests
        mock_requests_get.side_effect = _requests.RequestException("Connection error")

        result = await gather_song_info("/fake/path.mp3")

        assert result["album_art_file"] is None

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_no_cover_url_album_art_is_none(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(cover_url=None)
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam
        # requests.get may be called for lyrics.ovh fallback, not for album art
        mock_requests_get.return_value = MagicMock(
            status_code=200, json=lambda: {"lyrics": None}
        )

        result = await gather_song_info("/fake/path.mp3")

        assert result["album_art_file"] is None

    @pytest.mark.asyncio
    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    @patch("app.controllers.song_recognition.get_metadata.Shazam")
    async def test_optional_metadata_year_extracted(self, mock_shazam_cls, mock_requests_get):
        shazam_resp = _build_shazam_response(year="2019")
        mock_shazam = AsyncMock()
        mock_shazam.recognize.return_value = shazam_resp
        mock_shazam_cls.return_value = mock_shazam
        mock_requests_get.return_value = MagicMock(content=b"", raise_for_status=MagicMock())

        result = await gather_song_info("/fake/path.mp3")

        assert result["optional_metadata"]["year"] == "2019"


# ---------------------------------------------------------------------------
# attach_id3_metadata
# ---------------------------------------------------------------------------

class TestAttachId3Metadata:
    def _minimal_metadata(self, **overrides):
        base = {
            "song_name": "Test Song",
            "artist_name": "Test Artist",
            "album_name": "Test Album",
            "optional_metadata": {},
            "album_art_file": None,
            "lyrics": None,
        }
        base.update(overrides)
        return base

    def test_attaches_required_tags_and_reads_back(self, minimal_mp3):
        metadata = self._minimal_metadata(song_name="My Song", artist_name="My Artist", album_name="My Album")
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        assert str(tags["TIT2"]) == "My Song"
        assert str(tags["TPE1"]) == "My Artist"
        assert str(tags["TALB"]) == "My Album"

    def test_missing_song_name_raises_value_error(self, minimal_mp3):
        metadata = self._minimal_metadata(song_name="")
        with pytest.raises(ValueError, match="Missing required"):
            attach_id3_metadata(minimal_mp3, metadata)

    def test_missing_artist_name_raises_value_error(self, minimal_mp3):
        metadata = self._minimal_metadata(artist_name="")
        with pytest.raises(ValueError, match="Missing required"):
            attach_id3_metadata(minimal_mp3, metadata)

    def test_none_song_name_raises_value_error(self, minimal_mp3):
        metadata = self._minimal_metadata(song_name=None)
        with pytest.raises(ValueError):
            attach_id3_metadata(minimal_mp3, metadata)

    def test_file_not_found_raises_error(self, tmp_path):
        """attach_id3_metadata raises when file doesn't exist.

        Mutagen wraps FileNotFoundError in MutagenError when the path is
        completely absent — both are subclasses of Exception. We accept
        either FileNotFoundError or MutagenError.
        """
        bad_path = str(tmp_path / "nonexistent.mp3")
        metadata = self._minimal_metadata()
        with pytest.raises((FileNotFoundError, MutagenError)):
            attach_id3_metadata(bad_path, metadata)

    def test_year_attached_when_present(self, minimal_mp3):
        metadata = self._minimal_metadata(optional_metadata={"year": "2021"})
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        # Mutagen upgrades TYER (ID3v2.3) to TDRC (ID3v2.4) on load; check either.
        year_present = "TYER" in tags or "TDRC" in tags
        assert year_present
        year_value = str(tags.get("TYER") or tags.get("TDRC"))
        assert "2021" in year_value

    def test_year_skipped_when_absent(self, minimal_mp3):
        metadata = self._minimal_metadata(optional_metadata={})
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        assert "TYER" not in tags and "TDRC" not in tags

    def test_lyrics_attached_when_present(self, minimal_mp3):
        metadata = self._minimal_metadata(lyrics="Line 1\nLine 2")
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        assert "USLT::Lyrics" in tags or any(k.startswith("USLT") for k in tags.keys())

    def test_lyrics_skipped_when_none(self, minimal_mp3):
        metadata = self._minimal_metadata(lyrics=None)
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        uslt_keys = [k for k in tags.keys() if k.startswith("USLT")]
        assert uslt_keys == []

    def test_album_art_attached_when_present(self, minimal_mp3):
        fake_jpg = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        metadata = self._minimal_metadata(album_art_file=fake_jpg)
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        assert len(apic_keys) > 0

    def test_album_art_skipped_when_none(self, minimal_mp3):
        metadata = self._minimal_metadata(album_art_file=None)
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        assert apic_keys == []

    def test_album_defaults_to_unknown_when_not_provided(self, minimal_mp3):
        metadata = {
            "song_name": "Song",
            "artist_name": "Artist",
            # album_name absent — should default
            "optional_metadata": {},
            "album_art_file": None,
            "lyrics": None,
        }
        attach_id3_metadata(minimal_mp3, metadata)

        from mutagen.id3 import ID3
        tags = ID3(minimal_mp3)
        assert str(tags["TALB"]) == "Unknown Album"


class TestFetchLyricsSecondSource:
    """Unit tests for the LRCLIB-backed second lyrics source. Network mocked."""

    def _response(self, status_code=200, payload=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = payload if payload is not None else []
        return resp

    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    def test_returns_plain_lyrics_from_first_result(self, mock_get):
        from app.controllers.song_recognition.get_metadata import fetch_lyrics_second_source
        mock_get.return_value = self._response(payload=[
            {"plainLyrics": "Line 1\nLine 2", "syncedLyrics": "[00:01.00] Line 1"},
        ])
        assert fetch_lyrics_second_source("Artist", "Song") == "Line 1\nLine 2"
        assert mock_get.call_args.kwargs["params"] == {
            "artist_name": "Artist", "track_name": "Song",
        }

    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    def test_falls_back_to_synced_lyrics_and_skips_empty_results(self, mock_get):
        from app.controllers.song_recognition.get_metadata import fetch_lyrics_second_source
        mock_get.return_value = self._response(payload=[
            {"plainLyrics": None, "syncedLyrics": None},
            {"plainLyrics": None, "syncedLyrics": "[00:01.00] Synced line"},
        ])
        assert fetch_lyrics_second_source("Artist", "Song") == "[00:01.00] Synced line"

    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        from app.controllers.song_recognition.get_metadata import fetch_lyrics_second_source
        mock_get.return_value = self._response(status_code=500)
        assert fetch_lyrics_second_source("Artist", "Song") is None

    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    def test_returns_none_when_no_results(self, mock_get):
        from app.controllers.song_recognition.get_metadata import fetch_lyrics_second_source
        mock_get.return_value = self._response(payload=[])
        assert fetch_lyrics_second_source("Artist", "Song") is None

    @patch("app.controllers.song_recognition.get_metadata.requests.get")
    def test_returns_none_on_network_exception(self, mock_get):
        from app.controllers.song_recognition.get_metadata import fetch_lyrics_second_source
        mock_get.side_effect = ConnectionError("boom")
        assert fetch_lyrics_second_source("Artist", "Song") is None
