"""Mode → provider-chain selection and the acquisition orchestrator."""
from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.controllers.song_aquisition.providers.youtube import YouTubeProvider
from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)

YOUTUBE_MODE = "youtube"
COMPLIANT_MODE = "compliant"
VALID_MODES = (YOUTUBE_MODE, COMPLIANT_MODE)
DEFAULT_MODE = COMPLIANT_MODE


def _compliant_providers() -> list[AudioSourceProvider]:
    """
    Providers used by compliant mode, in priority order.

    Populated across phases: JamendoProvider (Phase C), InternetArchiveProvider
    (Phase E). Until then compliant mode always misses, so every track flows to
    the purchase manifest — which is the honest result for commercial catalogs.
    """
    providers: list[AudioSourceProvider] = []
    try:
        from app.controllers.song_aquisition.providers.jamendo import JamendoProvider
        providers.append(JamendoProvider())
    except ImportError:
        pass
    return providers


def providers_for_mode(mode: str) -> list[AudioSourceProvider]:
    """Return the ordered provider chain for the given acquisition mode."""
    if mode == COMPLIANT_MODE:
        return _compliant_providers()
    return [YouTubeProvider()]


def acquire_track(
    artist: str,
    title: str,
    album: str | None,
    output_directory: str,
    mode: str = DEFAULT_MODE,
    output_filename: str | None = None,
) -> tuple[SongDownloadResult | None, str | None]:
    """
    Try each provider for `mode` and return (result, source_name) for the first
    hit, or (None, None) if every provider misses.
    """
    for provider in providers_for_mode(mode):
        try:
            result = provider.acquire(artist, title, album, output_directory, output_filename)
        except Exception as exc:
            # A provider error should not abort the chain — log and try the next.
            logger.error(f"Provider {provider.name} errored on '{artist} - {title}': {exc}")
            continue
        if result is not None:
            return result, provider.name
    return None, None
