"""Load Spotify/Jamendo credentials from environment variables or a .env file."""
import os
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
JAMENDO_CLIENT_ID = os.environ.get("JAMENDO_CLIENT_ID", "")


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


def get_jamendo_client_id() -> str:
    """Read the Jamendo API client_id at call time (see get_spotify_credentials)."""
    return os.environ.get("JAMENDO_CLIENT_ID", JAMENDO_CLIENT_ID)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def get_ytdlp_throttle_opts() -> dict:
    """
    yt-dlp options that keep YouTube requests polite and resilient, so a normal
    residential IP is less likely to be flagged as a bot. Read at call time so
    the Settings page can change them without a restart. Deliberately does NOT
    use proxies/Tor (datacenter and Tor exit IPs are flagged harder by YouTube).
    """
    opts: dict = {
        "sleep_interval": _env_float("YTDLP_SLEEP_INTERVAL", 1.0),
        "max_sleep_interval": _env_float("YTDLP_MAX_SLEEP_INTERVAL", 5.0),
        "sleep_interval_requests": _env_int("YTDLP_SLEEP_REQUESTS", 1),
        "retries": _env_int("YTDLP_RETRIES", 10),
        "extractor_retries": _env_int("YTDLP_EXTRACTOR_RETRIES", 3),
    }
    ratelimit = _env_int("YTDLP_RATELIMIT", 0)  # bytes/sec; 0 = unlimited
    if ratelimit > 0:
        opts["ratelimit"] = ratelimit
    return opts
