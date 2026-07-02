"""YouTube audio-source provider (yt-dlp search + download + Shazam verify)."""
from app.controllers.song_aquisition.get_check_enhance_song import get_check_enhance_song
from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.models.exceptions import DownloadError
from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)


class YouTubeProvider(AudioSourceProvider):
    """
    Acquire audio by searching YouTube and downloading via yt-dlp.

    Thin adapter over get_check_enhance_song: an exhausted search (DownloadError)
    is a miss (None) here, so the provider chain can fall through. The heavy
    logic and its tests remain in get_check_enhance_song.
    """

    name = "youtube"

    def __init__(self, max_retry: int = 3):
        self.max_retry = max_retry

    def acquire(
        self,
        artist: str,
        title: str,
        album: str | None,
        output_directory: str,
        output_filename: str | None = None,
    ) -> SongDownloadResult | None:
        try:
            return get_check_enhance_song(
                artist_name=artist,
                song_name=title,
                output_directory=output_directory,
                output_filename=output_filename,
                max_retry=self.max_retry,
            )
        except DownloadError as exc:
            logger.info(f"YouTube miss for '{artist} - {title}': {exc}")
            return None
