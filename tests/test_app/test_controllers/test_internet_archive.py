"""Tests for the Internet Archive provider (Phase E). Network fully mocked."""
import os
from unittest.mock import MagicMock, patch

from app.controllers.song_aquisition.providers.internet_archive import InternetArchiveProvider


def _resp(json_data=None, content=b""):
    r = MagicMock()
    r.json.return_value = json_data if json_data is not None else {}
    r.content = content
    r.raise_for_status = MagicMock()
    return r


def _fake_get(docs, meta, audio=b"AUDIO"):
    def get(url, params=None, timeout=None, **kwargs):
        if url.startswith("https://archive.org/advancedsearch.php"):
            return _resp({"response": {"docs": docs}})
        if url.startswith("https://archive.org/metadata/"):
            return _resp(meta)
        return _resp(content=audio)  # download
    return get


class TestInternetArchiveProvider:
    @patch("app.controllers.song_aquisition.providers.internet_archive.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.providers.internet_archive.requests.get")
    def test_hit_downloads_and_tags(self, mock_get, mock_attach, tmp_path):
        docs = [{"identifier": "item1"}]
        meta = {
            "metadata": {"creator": "Live Band", "title": "Concert 1998", "licenseurl": "https://cc/by"},
            "files": [{"name": "01 - Free Song.mp3", "title": "Free Song", "artist": "Live Band"}],
        }
        mock_get.side_effect = _fake_get(docs, meta)

        result = InternetArchiveProvider().acquire("Live Band", "Free Song", None, str(tmp_path))

        assert result is not None
        assert os.path.isfile(result.path)
        assert result.metadata["artist_name"] == "Live Band"
        assert result.metadata["license_url"] == "https://cc/by"
        mock_attach.assert_called_once()

    @patch("app.controllers.song_aquisition.providers.internet_archive.requests.get")
    def test_no_matching_file_is_a_miss(self, mock_get, tmp_path):
        docs = [{"identifier": "item1"}]
        meta = {
            "metadata": {"creator": "Live Band", "title": "Concert"},
            "files": [{"name": "01 - Other Song.mp3", "title": "Other Song", "artist": "Live Band"}],
        }
        mock_get.side_effect = _fake_get(docs, meta)

        assert InternetArchiveProvider().acquire("Live Band", "Free Song", None, str(tmp_path)) is None

    @patch("app.controllers.song_aquisition.providers.internet_archive.requests.get")
    def test_no_audio_files_is_a_miss(self, mock_get, tmp_path):
        docs = [{"identifier": "item1"}]
        meta = {"metadata": {"creator": "Live Band"}, "files": [{"name": "cover.jpg"}]}
        mock_get.side_effect = _fake_get(docs, meta)

        assert InternetArchiveProvider().acquire("Live Band", "Free Song", None, str(tmp_path)) is None

    @patch("app.controllers.song_aquisition.providers.internet_archive.requests.get")
    def test_empty_search_is_a_miss(self, mock_get, tmp_path):
        mock_get.side_effect = _fake_get([], {})
        assert InternetArchiveProvider().acquire("X", "Y", None, str(tmp_path)) is None


class TestCompliantRegistryHasIA:
    def test_compliant_mode_includes_internet_archive(self):
        from app.controllers.song_aquisition.providers.registry import providers_for_mode
        names = [p.name for p in providers_for_mode("compliant")]
        assert "internet_archive" in names
        assert "local_import" in names
