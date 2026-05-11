import logging
import re

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from app.tools.make_logger import simple_logger
from app.config.local_config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
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


def get_spotify_playlist(playlist_url: str) -> list[dict[str, str]]:
    """
    Gather a list of songs (title and artist) from a Spotify playlist, given its URL.

    This version reads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from environment variables
    via app.config.local_config.

    :param playlist_url: The full URL of the Spotify playlist.
    :return: A list of dictionaries with 'title' and 'artist' for each track.
    :raises CredentialsError: If Spotify credentials are missing.
    :raises PlaylistFetchError: If the playlist cannot be retrieved.

    Usage example:
        tracks = get_spotify_playlist(
            playlist_url="https://open.spotify.com/playlist/123...",
        )
    """
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        raise CredentialsError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set. See local_config.py.example."
        )

    playlist_id = extract_playlist_id(playlist_url)
    if not playlist_id:
        raise PlaylistFetchError("Could not parse a valid playlist ID from the given URL.")

    logger.debug(f"Attempting to retrieve tracks for playlist: {playlist_id}")

    # Authenticate with Spotify using credentials loaded from environment
    client_credentials_manager = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
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
                fields="items(track(name,artists(name))),next"
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

                if track_name and artist_names:
                    tracks_data.append({
                        "title": track_name,
                        "artist": artist_names
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
    except Exception as e:
        logger.exception(f"Error retrieving Spotify playlist: {e}")
        raise PlaylistFetchError(f"Failed to retrieve Spotify playlist '{playlist_id}': {e}") from e
