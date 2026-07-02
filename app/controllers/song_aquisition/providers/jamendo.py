"""
Jamendo audio-source provider.

Jamendo hosts Creative-Commons-licensed music with an official API that returns
a direct, legal download URL per track (when the artist allows downloads). We
search by artist+title, verify the candidate's own metadata, download the MP3,
and tag it (embedding the CC license URL).

API docs: https://developer.jamendo.com/v3.0/tracks
"""
import io
import os
import re

import requests

from app.config.local_config import get_jamendo_client_id
from app.controllers.song_file_controller.metadata_attacher import attach_id3_metadata
from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)
from app.tools.make_logger import simple_logger
from app.tools.track_matching import artists_match, titles_match

logger = simple_logger(__name__)

API_URL = "https://api.jamendo.com/v3.0/tracks/"
_TIMEOUT = 20


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s_-]", "", name, flags=re.UNICODE).strip() or "track"


class JamendoProvider(AudioSourceProvider):
    """Acquire Creative-Commons tracks from Jamendo's official API."""

    name = "jamendo"

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
        client_id = get_jamendo_client_id()
        if not client_id:
            logger.debug("Jamendo client_id not set — skipping Jamendo provider.")
            return None

        candidates = self._search(client_id, artist, title)
        for track in candidates:
            if not track.get("audiodownload_allowed"):
                continue
            download_url = track.get("audiodownload")
            if not download_url:
                continue
            if not (
                artists_match(artist, track.get("artist_name", ""))
                and titles_match(title, track.get("name", ""))
            ):
                continue

            dest = os.path.join(
                output_directory, f"{_safe_filename(output_filename or title)}.mp3"
            )
            try:
                self._download_file(download_url, dest)
            except Exception as exc:
                logger.warning(f"Jamendo download failed for '{artist} - {title}': {exc}")
                if os.path.isfile(dest):
                    os.remove(dest)
                continue

            metadata = self._build_metadata(track)
            tag_error = None
            try:
                attach_id3_metadata(dest, metadata)
            except Exception as exc:
                tag_error = str(exc)
                logger.error(f"Failed to attach ID3 metadata (Jamendo): {exc}")
            logger.info(f"Jamendo hit for '{artist} - {title}' -> {track.get('name')}")
            return SongDownloadResult(dest, metadata, tag_error)

        logger.info(f"Jamendo miss for '{artist} - {title}'")
        return None

    # -- internals -----------------------------------------------------------

    def _search(self, client_id: str, artist: str, title: str) -> list[dict]:
        params = {
            "client_id": client_id,
            "format": "json",
            "limit": self.limit,
            "search": f"{artist} {title}",
            "audioformat": "mp32",
            "include": "musicinfo licenses",
        }
        resp = requests.get(API_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _download_file(self, url: str, dest: str) -> None:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(dest) == 0:
            raise ValueError("Downloaded file is empty")

    def _fetch_art(self, url: str) -> io.BytesIO | None:
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return io.BytesIO(resp.content)
        except Exception as exc:
            logger.debug(f"Jamendo album-art fetch failed: {exc}")
            return None

    def _build_metadata(self, track: dict) -> dict:
        genres = (track.get("musicinfo", {}) or {}).get("tags", {}).get("genres") or []
        art_url = track.get("album_image") or track.get("image")
        return {
            "song_name": track.get("name"),
            "artist_name": track.get("artist_name"),
            "album_name": track.get("album_name") or "Unknown Album",
            "optional_metadata": {
                "year": track.get("releasedate", ""),
                "genre": genres[0] if genres else None,
            },
            "license_url": track.get("license_ccurl"),
            "album_art_file": self._fetch_art(art_url) if art_url else None,
        }
