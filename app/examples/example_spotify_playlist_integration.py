import os

from app.controllers.playlist_aquisition.get_spotify_playlist import get_spotify_playlist
from app.controllers.integration.integrate_playlist_to_library import integrate_playlist
from app.tools.make_logger import simple_logger
from app.config.paths import EXAMPLE_FILES_FOLDER

logger = simple_logger(__name__)


def main():
    """
    Demonstrates how to use the Spotify playlist acquisition and integration features.

    1) Retrieve a playlist from Spotify (requires local_config.py with SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    2) Integrate the playlist into a local library structure using an organizing schema.
    """
    # Example: Spotify playlist URL
    playlist_url = "https://open.spotify.com/playlist/3eV0tu6uNXWTFVHcNDStDg"

    # Root folder where your music library is stored
    root_folder = EXAMPLE_FILES_FOLDER

    # Example organizing schema
    # We can skip 'album' if we only want artist-based hierarchy. We can also use 'wildcard'.
    organizing_schema = ["wildcard", "artist", "album"]

    # Retrieve the playlist data
    logger.info(f"Fetching playlist from: {playlist_url}")
    playlist_data = get_spotify_playlist(playlist_url)

    if not playlist_data:
        logger.error("No tracks found in the playlist or there was an error.")
        return

    logger.info(f"Retrieved {len(playlist_data)} tracks from Spotify.")

    # Integrate the playlist into the local library
    # e.g., put them in folders <root_folder>/<artist>/<album>/<artist> - <title>.mp3
    logger.info("Starting integration...")
    integrate_playlist(
        playlist=playlist_data,
        root_folder=root_folder,
        organizing_schema=organizing_schema,
        wildcard_value=None  # If your schema has 'wildcard', supply a folder name
    )
    logger.info("Integration complete.")


if __name__ == "__main__":
    main()
