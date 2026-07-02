"""
Tests for the audio-source provider abstraction (Phase A).

Network is never touched: the YouTube provider is a thin adapter over
get_check_enhance_song, which is patched here.
"""
from unittest.mock import patch

from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.controllers.song_aquisition.providers.registry import (
    COMPLIANT_MODE,
    YOUTUBE_MODE,
    acquire_track,
    providers_for_mode,
)
from app.controllers.song_aquisition.providers.youtube import YouTubeProvider
from app.models.exceptions import DownloadError


class TestYouTubeProvider:
    def test_is_a_provider(self):
        assert isinstance(YouTubeProvider(), AudioSourceProvider)
        assert YouTubeProvider().name == "youtube"

    @patch("app.controllers.song_aquisition.providers.youtube.get_check_enhance_song")
    def test_hit_returns_result(self, mock_get):
        expected = SongDownloadResult("/tmp/song.mp3", {"album_name": "A"})
        mock_get.return_value = expected

        result = YouTubeProvider().acquire("Queen", "Bohemian Rhapsody", None, "/tmp")

        assert result is expected
        assert mock_get.call_args.kwargs["artist_name"] == "Queen"
        assert mock_get.call_args.kwargs["song_name"] == "Bohemian Rhapsody"

    @patch("app.controllers.song_aquisition.providers.youtube.get_check_enhance_song")
    def test_download_error_is_a_miss(self, mock_get):
        """An exhausted YouTube search is a clean miss (None), not an error."""
        mock_get.side_effect = DownloadError("All attempts exhausted")

        assert YouTubeProvider().acquire("Queen", "Bohemian Rhapsody", None, "/tmp") is None


class TestRegistry:
    def test_youtube_mode_uses_youtube_provider(self):
        providers = providers_for_mode(YOUTUBE_MODE)
        assert len(providers) == 1
        assert isinstance(providers[0], YouTubeProvider)

    def test_unknown_mode_defaults_to_youtube(self):
        assert isinstance(providers_for_mode("nonsense")[0], YouTubeProvider)

    def test_compliant_mode_has_no_youtube_provider(self):
        assert not any(isinstance(p, YouTubeProvider) for p in providers_for_mode(COMPLIANT_MODE))


class TestAcquireTrack:
    @patch("app.controllers.song_aquisition.providers.youtube.get_check_enhance_song")
    def test_hit_returns_result_and_source(self, mock_get):
        expected = SongDownloadResult("/tmp/song.mp3", {"album_name": "A"})
        mock_get.return_value = expected

        result, source = acquire_track("Queen", "Bohemian Rhapsody", None, "/tmp", mode=YOUTUBE_MODE)

        assert result is expected
        assert source == "youtube"

    @patch("app.controllers.song_aquisition.providers.youtube.get_check_enhance_song")
    def test_miss_returns_none_none(self, mock_get):
        mock_get.side_effect = DownloadError("nope")

        result, source = acquire_track("Queen", "X", None, "/tmp", mode=YOUTUBE_MODE)

        assert result is None
        assert source is None

    def test_all_providers_miss_returns_none_none(self):
        """When every provider in the chain misses, acquire_track reports a clean miss."""
        with patch(
            "app.controllers.song_aquisition.providers.registry.providers_for_mode",
            return_value=[],
        ):
            result, source = acquire_track(
                "Queen", "Bohemian Rhapsody", None, "/tmp", mode=COMPLIANT_MODE
            )
        assert result is None
        assert source is None
