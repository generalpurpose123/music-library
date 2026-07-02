"""Load Spotify credentials from environment variables or a .env file."""
import os
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def get_spotify_credentials() -> tuple[str, str]:
    """
    Read the Spotify credentials at call time, so changes made after import
    (e.g. via the Settings page, which updates os.environ) take effect
    without a restart.
    """
    return (
        os.environ.get("SPOTIFY_CLIENT_ID", SPOTIFY_CLIENT_ID),
        os.environ.get("SPOTIFY_CLIENT_SECRET", SPOTIFY_CLIENT_SECRET),
    )
