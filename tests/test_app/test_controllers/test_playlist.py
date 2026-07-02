"""
Tests for get_spotify_playlist.py

Covers:
  - extract_playlist_id
  - get_spotify_playlist (paginated fetch, empty playlist, API error)
"""
import pytest
from unittest.mock import patch, MagicMock

from app.controllers.playlist_aquisition.get_spotify_playlist import (
    extract_playlist_id,
    get_spotify_playlist,
)
from app.models.exceptions import CredentialsError, PlaylistFetchError

# Convenience: patch the call-time credential getter so the guard at the top
# of get_spotify_playlist doesn't fire (avoids arg injection via new=).
_FAKE_CREDS_PATCH = (
    "app.controllers.playlist_aquisition.get_spotify_playlist.get_spotify_credentials"
)


# ---------------------------------------------------------------------------
# extract_playlist_id
# ---------------------------------------------------------------------------

class TestExtractPlaylistId:
    def test_valid_https_url(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DX4sWSpwq3LiO"
        result = extract_playlist_id(url)
        assert result == "37i9dQZF1DX4sWSpwq3LiO"

    def test_playlist_uri(self):
        uri = "spotify:playlist:37i9dQZF1DX4sWSpwq3LiO"
        result = extract_playlist_id(uri)
        assert result == "37i9dQZF1DX4sWSpwq3LiO"

    def test_url_with_query_params(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DX4sWSpwq3LiO?si=abc123"
        result = extract_playlist_id(url)
        # The regex stops at ? or end of alphanumeric chars
        assert result == "37i9dQZF1DX4sWSpwq3LiO"

    def test_invalid_url_returns_none(self):
        assert extract_playlist_id("https://example.com/not-a-playlist") is None

    def test_empty_string_returns_none(self):
        assert extract_playlist_id("") is None

    def test_url_without_playlist_keyword_returns_none(self):
        assert extract_playlist_id("https://open.spotify.com/track/abc123") is None

    def test_mixed_case_playlist_keyword(self):
        # The URL as actually produced by Spotify always uses lowercase; test the regex
        url = "https://open.spotify.com/playlist/ABCDEF123456"
        result = extract_playlist_id(url)
        assert result == "ABCDEF123456"


# ---------------------------------------------------------------------------
# get_spotify_playlist
# ---------------------------------------------------------------------------

def _make_item(name, artist_names, album="Some Album"):
    """Helper to build a Spotify playlist item dict."""
    return {
        "track": {
            "name": name,
            "artists": [{"name": a} for a in artist_names],
            "album": {"name": album} if album is not None else None,
        }
    }


class TestGetSpotifyPlaylist:
    def _build_mock_spotify(self, pages):
        """
        pages: list of (items, has_next) tuples.
        Returns a mock spotipy.Spotify instance whose playlist_items
        cycles through the pages.
        """
        responses = []
        for i, (items, has_next) in enumerate(pages):
            responses.append({
                "items": items,
                "next": "https://next" if has_next else None,
            })
        mock_sp = MagicMock()
        mock_sp.playlist_items.side_effect = responses
        return mock_sp

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_successful_single_page_fetch(self, mock_spotify_cls, mock_creds):
        items = [
            _make_item("Song A", ["Artist A"]),
            _make_item("Song B", ["Artist B"]),
        ]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/abc123")

        assert len(result) == 2
        assert result[0] == {"title": "Song A", "artist": "Artist A", "album": "Some Album"}
        assert result[1] == {"title": "Song B", "artist": "Artist B", "album": "Some Album"}

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_paginated_two_pages(self, mock_spotify_cls, mock_creds):
        page1 = [_make_item(f"Song {i}", ["Artist"]) for i in range(3)]
        page2 = [_make_item(f"Song {i}", ["Artist"]) for i in range(3, 5)]
        mock_sp = self._build_mock_spotify([
            (page1, True),   # first page has next
            (page2, False),  # second page is last
        ])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/xyz789")

        assert len(result) == 5
        # playlist_items should have been called twice (two pages)
        assert mock_sp.playlist_items.call_count == 2

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_pagination_stops_when_next_is_none(self, mock_spotify_cls, mock_creds):
        page1 = [_make_item("Only Song", ["Only Artist"])]
        mock_sp = self._build_mock_spotify([(page1, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/onepage")

        assert mock_sp.playlist_items.call_count == 1
        assert len(result) == 1

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_empty_playlist_returns_empty_list(self, mock_spotify_cls, mock_creds):
        mock_sp = self._build_mock_spotify([([], False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/empty")

        assert result == []

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_spotify_api_error_raises_playlist_fetch_error(self, mock_spotify_cls, mock_creds):
        """Unexpected Spotify API errors are wrapped in PlaylistFetchError."""
        mock_sp = MagicMock()
        mock_sp.playlist_items.side_effect = Exception("Spotify API error")
        mock_spotify_cls.return_value = mock_sp

        with pytest.raises(PlaylistFetchError):
            get_spotify_playlist("https://open.spotify.com/playlist/abc123")

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_multiple_artists_joined_with_comma(self, mock_spotify_cls, mock_creds):
        items = [_make_item("Collab", ["Artist A", "Artist B"])]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/abc123")

        assert len(result) == 1
        assert result[0]["artist"] == "Artist A, Artist B"

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_tracks_without_name_or_artist_skipped(self, mock_spotify_cls, mock_creds):
        items = [
            {"track": None},                         # null track (podcast episode etc.)
            _make_item("Good Song", ["Artist"]),
        ]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/mixed")

        assert len(result) == 1
        assert result[0]["title"] == "Good Song"

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_album_name_extracted(self, mock_spotify_cls, mock_creds):
        """Regression (B2): the album must be fetched so library paths are stable."""
        items = [_make_item("Song", ["Artist"], album="The Album")]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/abc123")

        assert result[0]["album"] == "The Album"

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_missing_album_yields_none(self, mock_spotify_cls, mock_creds):
        items = [_make_item("Local File", ["Artist"], album=None)]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        result = get_spotify_playlist("https://open.spotify.com/playlist/abc123")

        assert result[0]["album"] is None

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    def test_fields_param_requests_album(self, mock_spotify_cls, mock_creds):
        items = [_make_item("Song", ["Artist"])]
        mock_sp = self._build_mock_spotify([(items, False)])
        mock_spotify_cls.return_value = mock_sp

        get_spotify_playlist("https://open.spotify.com/playlist/abc123")

        fields = mock_sp.playlist_items.call_args.kwargs["fields"]
        assert "album(name)" in fields

    def test_invalid_url_raises_playlist_fetch_error(self):
        """Invalid URL (no playlist ID parsable) raises PlaylistFetchError."""
        with patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret")):
            with pytest.raises(PlaylistFetchError):
                get_spotify_playlist("not-a-real-url")

    def test_missing_credentials_raises_credentials_error(self):
        """Missing Spotify credentials raise CredentialsError."""
        with patch(_FAKE_CREDS_PATCH, new=lambda: ("", "")):
            with pytest.raises(CredentialsError):
                get_spotify_playlist("https://open.spotify.com/playlist/abc123")

    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    def test_credentials_read_at_call_time(self, mock_spotify_cls, mock_creds, monkeypatch):
        """Regression (frontend A): credentials changed via Settings must apply without restart."""
        items = [_make_item("Song", ["Artist"])]
        mock_sp = MagicMock()
        mock_sp.playlist_items.return_value = {"items": items, "next": None}
        mock_spotify_cls.return_value = mock_sp

        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id_one")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "sec_one")
        get_spotify_playlist("https://open.spotify.com/playlist/abc123")
        assert mock_creds.call_args.kwargs["client_id"] == "id_one"

        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id_two")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "sec_two")
        get_spotify_playlist("https://open.spotify.com/playlist/abc123")
        assert mock_creds.call_args.kwargs["client_id"] == "id_two"

    @patch(_FAKE_CREDS_PATCH, new=lambda: ("fake_id", "fake_secret"))
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.SpotifyClientCredentials")
    @patch("app.controllers.playlist_aquisition.get_spotify_playlist.spotipy.Spotify")
    def test_private_playlist_raises_clear_message(self, mock_spotify_cls, mock_creds):
        """Regression (B7): 404 on private/editorial playlists gives an actionable error."""
        from spotipy.exceptions import SpotifyException

        mock_sp = MagicMock()
        mock_sp.playlist_items.side_effect = SpotifyException(404, -1, "Not found")
        mock_spotify_cls.return_value = mock_sp

        with pytest.raises(PlaylistFetchError, match="Client Credentials"):
            get_spotify_playlist("https://open.spotify.com/playlist/abc123")
