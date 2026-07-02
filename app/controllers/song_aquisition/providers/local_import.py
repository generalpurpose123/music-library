"""
Local-import audio-source provider.

For music you already own: point MUSIC_IMPORT_FOLDER at a folder of purchased /
ripped MP3s and compliant mode will match tracks there (by ID3 tags), copy the
matching file into the library, and organise it — no download at all.
"""
import os
import shutil

from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)


class LocalImportProvider(AudioSourceProvider):
    """Import a matching track from a folder of files the owner already has."""

    name = "local_import"

    def __init__(self, source_folder: str | None = None):
        self.source_folder = (
            source_folder if source_folder is not None
            else os.environ.get("MUSIC_IMPORT_FOLDER", "")
        )

    def acquire(
        self,
        artist: str,
        title: str,
        album: str | None,
        output_directory: str,
        output_filename: str | None = None,
    ) -> SongDownloadResult | None:
        if not self.source_folder or not os.path.isdir(self.source_folder):
            return None

        from app.controllers.integration.duplicate_detector import (
            scan_library,
            find_existing_in_library,
        )

        files = scan_library(self.source_folder)
        # exact_only: never import the wrong file on a fuzzy near-match.
        match = find_existing_in_library(title, artist, files, exact_only=True)
        if match is None:
            return None

        dest = os.path.join(output_directory, os.path.basename(match.path))
        try:
            shutil.copy2(match.path, dest)
        except OSError as exc:
            logger.warning(f"Local import copy failed for '{artist} - {title}': {exc}")
            return None

        metadata = {
            "song_name": match.title or title,
            "artist_name": match.artist or artist,
            "album_name": album or self._read_album(match.path) or "Unknown Album",
        }
        logger.info(f"Local import for '{artist} - {title}' <- {match.path}")
        return SongDownloadResult(dest, metadata)

    @staticmethod
    def _read_album(path: str) -> str | None:
        try:
            from mutagen.id3 import ID3
            return str(ID3(path).get("TALB", "")).strip() or None
        except Exception:
            return None
