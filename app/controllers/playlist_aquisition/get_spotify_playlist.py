import logging
import re

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

from app.tools.make_logger import simple_logger
from app.config.local_config import get_spotify_credentials
from app.models.exceptions import CredentialsError, PlaylistFetchError

logger = simple_logger(__name__)


def extract_playlist_id(playlist_url: str) -> str | None:
    """
    Extracts the Spotify playlist ID from a typical playlist URL.
    e.g. https://open.spotify.com/playlist/12345ABCD => 12345ABCD

    :param playlist_url: The full playlist URL.
    :return: The extracted playlist ID, or None if it cannot be parsed.
    """
    # A simple regex to capture the part after "playlist/" or "playlist:" until we find ? or / or end of string
    pattern = r"playlist[/:]([A-Za-z0-9]+)"  # Basic, might want to expand for advanced cases.
    match = re.search(pattern, playlist_url)
    if match:
        return match.group(1)
    return None


def get_spotify_playlist(playlist_url: str) -> list[dict[str, str | None]]:
    """
    Gather a list of songs (title, artist, album) from a Spotify playlist, given its URL.

    This version reads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from environment variables
    via app.config.local_config.

    :param playlist_url: The full URL of the Spotify playlist.
    :return: A list of dictionaries with 'title', 'artist' and 'album' (album may be None)
        for each track.
    :raises CredentialsError: If Spotify credentials are missing.
    :raises PlaylistFetchError: If the playlist cannot be retrieved.

    Usage example:
        tracks = get_spotify_playlist(
            playlist_url="https://open.spotify.com/playlist/123...",
        )
    """
    client_id, client_secret = get_spotify_credentials()
    if not client_id or not client_secret:
        raise CredentialsError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set — add them to .env "
            "at the project root or enter them on the Settings page."
        )

    playlist_id = extract_playlist_id(playlist_url)
    if not playlist_id:
        raise PlaylistFetchError("Could not parse a valid playlist ID from the given URL.")

    logger.debug(f"Attempting to retrieve tracks for playlist: {playlist_id}")

    # Authenticate with Spotify using credentials loaded from environment
    client_credentials_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    )
    sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

    tracks_data = []
    try:
        # Spotify pagination: We'll fetch in batches of up to 100.
        offset = 0
        limit = 100

        while True:
            response = sp.playlist_items(
                playlist_id=playlist_id,
                offset=offset,
                limit=limit,
                fields="items(track(name,artists(name),album(name))),next"
            )

            items = response.get("items", [])
            for item in items:
                track = item.get("track")
                if not track:
                    continue
                track_name = track.get("name")
                artists = track.get("artists", [])
                # Join multiple artist names if necessary
                artist_names = ", ".join([artist.get("name", "") for artist in artists])
                album_name = (track.get("album") or {}).get("name") or None

                if track_name and artist_names:
                    tracks_data.append({
                        "title": track_name,
                        "artist": artist_names,
                        "album": album_name,
                    })

            # Check if there's another page
            # 'next' is None if there's no more results
            if response.get("next"):
                offset += limit
            else:
                break

        logger.info(f"Found {len(tracks_data)} tracks in the playlist.")
        return tracks_data
    except (CredentialsError, PlaylistFetchError):
        raise
    except SpotifyException as e:
        logger.exception(f"Spotify API error retrieving playlist: {e}")
        if e.http_status in (401, 403, 404):
            raise PlaylistFetchError(
                f"Spotify refused access to this playlist (HTTP {e.http_status}). This app "
                "uses the Client Credentials flow, which cannot read private, collaborative, "
                "or Spotify-generated (editorial) playlists — make the playlist public or "
                "pick a different one."
            ) from e
        raise PlaylistFetchError(f"Failed to retrieve Spotify playlist '{playlist_id}': {e}") from e
    except Exception as e:
        logger.exception(f"Error retrieving Spotify playlist: {e}")
        raise PlaylistFetchError(f"Failed to retrieve Spotify playlist '{playlist_id}': {e}") from e
