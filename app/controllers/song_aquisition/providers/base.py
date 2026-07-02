"""Provider interface and the shared acquisition result type."""
from abc import ABC, abstractmethod

# SongDownloadResult stays defined in get_check_enhance_song for backward
# compatibility (existing imports/tests target it there); re-exported here so
# providers can depend on the interface module rather than the YouTube module.
from app.controllers.song_aquisition.get_check_enhance_song import SongDownloadResult

__all__ = ["AudioSourceProvider", "SongDownloadResult"]


class AudioSourceProvider(ABC):
    """
    A source that can acquire a single track as a tagged local MP3.

    `acquire` returns a SongDownloadResult on success, or None on a clean
    *miss* — nothing found, or a candidate that failed verification. It raises
    only on real errors (network failure, bad credentials, disk problems), so a
    miss (the common case for commercial tracks on free/CC sources) can fall
    through to the next provider without being treated as a failure.
    """

    #: short, stable identifier recorded on the job (e.g. "youtube", "jamendo")
    name: str = "base"

    @abstractmethod
    def acquire(
        self,
        artist: str,
        title: str,
        album: str | None,
        output_directory: str,
        output_filename: str | None = None,
    ) -> SongDownloadResult | None:
        """Acquire one track into output_directory, or return None on a miss."""
        raise NotImplementedError
