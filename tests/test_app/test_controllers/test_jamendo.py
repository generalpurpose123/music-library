"""
Tests for the Jamendo audio-source provider (Phase C). Network fully mocked.
"""
import os
from unittest.mock import MagicMock, patch

from app.controllers.song_aquisition.providers.jamendo import JamendoProvider


def _resp(*, json_data=None, content=b""):
    r = MagicMock()
    r.json.return_value = json_data or {}
    r.content = content
    r.raise_for_status = MagicMock()
    return r


def _track(**over):
    base = {
        "id": "1",
        "name": "Sunrise",
        "artist_name": "Free Artist",
        "album_name": "Free Album",
        "releasedate": "2019-05-03",
        "audiodownload": "https://prod.jamendo.com/download/track/1/mp32/",
        "audiodownload_allowed": True,
        "license_ccurl": "https://creativecommons.org/licenses/by/3.0/",
        "image": "https://usercontent.jamendo.com/art/1.jpg",
        "musicinfo": {"tags": {"genres": ["electronic"]}},
    }
    base.update(over)
    return base


def _fake_get_factory(tracks, audio=b"ID3AUDIO", art=b"JPEGDATA"):
    def fake_get(url, params=None, timeout=None, **kwargs):
        if url == "https://api.jamendo.com/v3.0/tracks/":
            return _resp(json_data={"results": tracks})
        if "download" in url:
            return _resp(content=audio)
        return _resp(content=art)  # album art
    return fake_get


class TestJamendoProvider:
    @patch("app.controllers.song_aquisition.providers.jamendo.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.providers.jamendo.get_jamendo_client_id", return_value="k")
    @patch("app.controllers.song_aquisition.providers.jamendo.requests.get")
    def test_hit_downloads_and_tags(self, mock_get, _cid, mock_attach, tmp_path):
        mock_get.side_effect = _fake_get_factory([_track(name="Sunrise", artist_name="Free Artist")])

        result = JamendoProvider().acquire("Free Artist", "Sunrise", None, str(tmp_path))

        assert result is not None
        assert os.path.isfile(result.path)
        assert result.metadata["song_name"] == "Sunrise"
        assert result.metadata["license_url"] == "https://creativecommons.org/licenses/by/3.0/"
        mock_attach.assert_called_once()

    @patch("app.controllers.song_aquisition.providers.jamendo.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.providers.jamendo.get_jamendo_client_id", return_value="k")
    @patch("app.controllers.song_aquisition.providers.jamendo.requests.get")
    def test_unrelated_result_is_a_miss(self, mock_get, _cid, _attach, tmp_path):
        # Jamendo returns a different artist/title -> verification rejects it.
        mock_get.side_effect = _fake_get_factory(
            [_track(name="Totally Different", artist_name="Someone Else")]
        )
        assert JamendoProvider().acquire("Coldplay", "Viva La Vida", None, str(tmp_path)) is None

    @patch("app.controllers.song_aquisition.providers.jamendo.get_jamendo_client_id", return_value="k")
    @patch("app.controllers.song_aquisition.providers.jamendo.requests.get")
    def test_download_not_allowed_skipped(self, mock_get, _cid, tmp_path):
        mock_get.side_effect = _fake_get_factory([_track(audiodownload_allowed=False)])
        assert JamendoProvider().acquire("Free Artist", "Sunrise", None, str(tmp_path)) is None

    @patch("app.controllers.song_aquisition.providers.jamendo.get_jamendo_client_id", return_value="")
    @patch("app.controllers.song_aquisition.providers.jamendo.requests.get")
    def test_no_client_id_is_a_miss_and_no_request(self, mock_get, _cid, tmp_path):
        assert JamendoProvider().acquire("Free Artist", "Sunrise", None, str(tmp_path)) is None
        mock_get.assert_not_called()

    @patch("app.controllers.song_aquisition.providers.jamendo.attach_id3_metadata")
    @patch("app.controllers.song_aquisition.providers.jamendo.get_jamendo_client_id", return_value="k")
    @patch("app.controllers.song_aquisition.providers.jamendo.requests.get")
    def test_remaster_decoration_still_matches(self, mock_get, _cid, _attach, tmp_path):
        mock_get.side_effect = _fake_get_factory([_track(name="Sunrise", artist_name="Free Artist")])
        result = JamendoProvider().acquire(
            "Free Artist", "Sunrise - Remastered 2019", None, str(tmp_path)
        )
        assert result is not None


class TestCompliantRegistry:
    def test_compliant_mode_includes_jamendo(self):
        from app.controllers.song_aquisition.providers.registry import providers_for_mode
        names = [p.name for p in providers_for_mode("compliant")]
        assert "jamendo" in names
