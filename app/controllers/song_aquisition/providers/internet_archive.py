"""
Internet Archive audio-source provider.

archive.org hosts large amounts of public-domain, Creative-Commons, netlabel,
and legally-shareable live-concert audio, with an open API (no key). We search
for the track, inspect the item's files for a matching audio file, verify it,
download, and tag.

APIs: https://archive.org/advancedsearch.php · https://archive.org/metadata/<id>
"""
import io
import os
import re

import requests

from app.controllers.song_file_controller.metadata_attacher import attach_id3_metadata
from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.tools.make_logger import simple_logger
from app.tools.track_matching import artists_match, titles_match

logger = simple_logger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
_TIMEOUT = 20
_AUDIO_EXTS = (".mp3",)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s_.-]", "", name, flags=re.UNICODE).strip() or "track.mp3"


def _as_text(value) -> str:
    """IA metadata fields may be a string or a list of strings."""
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


class InternetArchiveProvider(AudioSourceProvider):
    """Acquire legally-shareable audio from the Internet Archive."""

    name = "internet_archive"

    def __init__(self, limit: int = 5):
        self.limit = limit

    def acquire(
        self,
        artist: str,
        title: str,
        album: str | None,
        output_directory: str,
        output_filename: str | None = None,
    ) -> SongDownloadResult | None:
        for doc in self._search(artist, title):
            identifier = doc.get("identifier")
            if not identifier:
                continue
            meta = self._metadata(identifier)
            if not meta:
                continue
            # Compliance guard: archive.org accepts community uploads, some of
            # which are infringing copies of commercial music. Only accept items
            # that declare an open license (Creative Commons / public domain).
            if not _as_text(meta.get("metadata", {}).get("licenseurl")):
                logger.debug(f"Skipping IA item {identifier}: no declared open license")
                continue
            picked = self._pick_audio_file(meta, artist, title)
            if not picked:
                continue

            file_name, file_title, file_artist = picked
            dest = os.path.join(output_directory, _safe_filename(output_filename or title) + ".mp3")
            url = DOWNLOAD_URL.format(identifier=identifier, filename=file_name)
            try:
                self._download_file(url, dest)
            except Exception as exc:
                logger.warning(f"Internet Archive download failed for '{artist} - {title}': {exc}")
                if os.path.isfile(dest):
                    os.remove(dest)
                continue

            item_meta = meta.get("metadata", {})
            metadata = {
                "song_name": file_title or title,
                "artist_name": file_artist or artist,
                "album_name": _as_text(item_meta.get("album")) or _as_text(item_meta.get("title")) or "Unknown Album",
                "optional_metadata": {"year": _as_text(item_meta.get("year") or item_meta.get("date"))},
                "license_url": _as_text(item_meta.get("licenseurl")),
            }
            tag_error = None
            try:
                attach_id3_metadata(dest, metadata)
            except Exception as exc:
                tag_error = str(exc)
                logger.error(f"Failed to attach ID3 metadata (Internet Archive): {exc}")
            logger.info(f"Internet Archive hit for '{artist} - {title}' -> {identifier}/{file_name}")
            return SongDownloadResult(dest, metadata, tag_error)

        logger.info(f"Internet Archive miss for '{artist} - {title}'")
        return None

    # -- internals -----------------------------------------------------------

    def _search(self, artist: str, title: str) -> list[dict]:
        params = {
            "q": f'title:("{title}") AND creator:("{artist}") AND mediatype:(audio)',
            "fl[]": "identifier",
            "rows": self.limit,
            "output": "json",
        }
        resp = requests.get(SEARCH_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("response", {}).get("docs", [])

    def _metadata(self, identifier: str) -> dict:
        resp = requests.get(METADATA_URL.format(identifier=identifier), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json() or {}

    def _pick_audio_file(self, meta: dict, artist: str, title: str) -> tuple[str, str, str] | None:
        """Return (file_name, file_title, file_artist) for the first verifying audio file."""
        item_creator = _as_text(meta.get("metadata", {}).get("creator"))
        for f in meta.get("files", []):
            name = f.get("name", "")
            if not name.lower().endswith(_AUDIO_EXTS):
                continue
            file_title = f.get("title") or os.path.splitext(name)[0]
            file_artist = f.get("artist") or item_creator
            if titles_match(title, file_title) and artists_match(artist, file_artist):
                return name, file_title, file_artist
        return None

    def _download_file(self, url: str, dest: str) -> None:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            fh.write(resp.content)
        if os.path.getsize(dest) == 0:
            raise ValueError("Downloaded file is empty")
