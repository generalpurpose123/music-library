import asyncio
import io
import logging
import time
from typing import Any

import requests
from shazamio import Shazam

from app.tools.make_logger import simple_logger
from app.models.exceptions import RecognitionError

logger = simple_logger(__name__)


def fetch_lyrics_from_lyrics_ovh(artist: str, title: str) -> str | None:
    """
    Attempt to fetch lyrics from the lyrics.ovh public API.

    :param artist: Artist name
    :param title: Song title
    :return: The lyrics string if found, else None
    """
    endpoint = f"https://api.lyrics.ovh/v1/{artist}/{title}"
    try:
        response = requests.get(endpoint, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("lyrics")
        logger.debug(f"lyrics.ovh has no lyrics for {artist} - {title} (HTTP {response.status_code})")
    except Exception as e:
        logger.debug(f"Failed to fetch lyrics from lyrics.ovh: {e}")
    return None


def fetch_lyrics_second_source(artist: str, title: str) -> str | None:
    """
    Fetch lyrics from LRCLIB (lrclib.net) — free, no API key required.

    Uses the search endpoint rather than exact-match /api/get, since Shazam's
    recognised artist/title strings rarely match LRCLIB's catalogue verbatim.
    Prefers plain lyrics over time-synced ones for the USLT tag.

    :param artist: Artist name
    :param title: Song title
    :return: The lyrics string if found, else None
    """
    try:
        response = requests.get(
            "https://lrclib.net/api/search",
            params={"artist_name": artist, "track_name": title},
            headers={"User-Agent": "music-library/0.1.0 (https://github.com/generalpurpose123/music-library)"},
            timeout=10,
        )
        if response.status_code != 200:
            logger.debug(f"LRCLIB search failed for {artist} - {title} (HTTP {response.status_code})")
            return None
        for result in response.json():
            lyrics = result.get("plainLyrics") or result.get("syncedLyrics")
            if lyrics:
                return lyrics
        logger.debug(f"LRCLIB has no lyrics for {artist} - {title}")
    except Exception as e:
        logger.debug(f"Failed to fetch lyrics from LRCLIB: {e}")
    return None


async def _recognize_with_retry(shazam: Shazam, file_path: str, max_attempts: int = 3) -> dict:
    """Call shazam.recognize() with exponential backoff.

    Shazam's API can return transient errors under load; backing off 2^attempt
    seconds gives the service time to recover without hammering it.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return await shazam.recognize(file_path)
        except Exception as exc:
            if attempt == max_attempts:
                raise RecognitionError(
                    f"Shazam recognition failed after {max_attempts} attempts: {exc}"
                ) from exc
            wait = 2 ** attempt
            logger.warning(f"Shazam attempt {attempt} failed, retrying in {wait}s: {exc}")
            await asyncio.sleep(wait)


async def gather_song_info(file_path: str) -> dict[str, Any]:
    """
    Recognize a local audio file using Shazam, extract relevant metadata, and return it.

    This function will:
      a) Extract required metadata (song name, artist name). If these fail, raises RecognitionError.
      b) Attempt to retrieve the album name. If unavailable, it is set to "Unknown Album".
      c) Acquire optional metadata (e.g., year, genre, label, ISRC, etc.).
      d) Acquire album art and store as a file-like (BytesIO). If none found, store None.
      e) Attempt to acquire lyrics from Shazam. If Shazam is missing lyrics, try alternative sources.

    :param file_path: Path to the local audio file
    :return: A dictionary containing the gathered metadata
    :raises RecognitionError: If required metadata is not found or Shazam fails all retries
    """
    logger.debug(f"Initializing Shazam for file: {file_path}")
    shazam = Shazam()

    logger.debug("Attempting to recognize song...")
    result = await _recognize_with_retry(shazam, file_path)
    track_info = result.get("track", {})
    logger.debug("Song recognition result obtained.")

    # ------------------------------------------------
    # a) Extract required metadata (song name, artist)
    # ------------------------------------------------
    title = track_info.get("title")
    artist = track_info.get("subtitle")

    if not title or not artist:
        error_message = f"Unable to find required metadata (title/artist) for file: {file_path}"
        logger.error(error_message)
        raise RecognitionError(error_message)

    # ------------------------------------------------
    # b) Album name (if unavailable, "Unknown Album")
    # ------------------------------------------------
    album = "Unknown Album"
    for section in track_info.get("sections", []):
        if section.get("type") == "SONG":
            for meta_item in section.get("metadata", []):
                if meta_item.get("title", "").lower() == "album":
                    album = meta_item.get("text", "Unknown Album")
                    break

    # ------------------------------------------------
    # c) Acquire optional metadata (more common fields)
    # ------------------------------------------------
    optional_metadata = {}

    # We'll parse the 'sections' to find items like year, or anything else.
    for section in track_info.get("sections", []):
        if section.get("type") == "SONG":
            for meta_item in section.get("metadata", []):
                title_key = meta_item.get("title", "").lower()
                text_val = meta_item.get("text", "")

                if title_key == "released":
                    optional_metadata["year"] = text_val
                elif title_key == "genre":
                    optional_metadata["genre"] = text_val
                elif title_key == "label":
                    optional_metadata["label"] = text_val
                elif title_key == "composer":
                    optional_metadata["composer"] = text_val
                elif title_key == "key":
                    optional_metadata["key"] = text_val
                elif title_key == "bpm":
                    optional_metadata["bpm"] = text_val

    # Some fields might be at the top level of track_info
    if "isrc" in track_info:
        optional_metadata["isrc"] = track_info["isrc"]
    if "genres" in track_info and isinstance(track_info["genres"], dict):
        optional_metadata["genre"] = track_info["genres"].get("primary", optional_metadata.get("genre"))
    if "label" in track_info:
        optional_metadata["label"] = track_info["label"]

    # ------------------------------------------------
    # d) Acquire album art as a file-like object
    # ------------------------------------------------
    images = track_info.get("images", {})
    cover_art_url = images.get("coverarthq") or images.get("coverart")
    album_art_file: io.BytesIO | None = None

    if cover_art_url:
        logger.debug(f"Attempting to download album art from: {cover_art_url}")
        try:
            response = requests.get(cover_art_url, timeout=10)
            response.raise_for_status()
            album_art_file = io.BytesIO(response.content)
            album_art_file.seek(0)
            logger.debug("Successfully downloaded album art.")
        except (requests.RequestException, IOError) as e:
            logger.warning(f"Failed to download album art: {e}")

    # ------------------------------------------------
    # e) Acquire lyrics via Shazam
    # ------------------------------------------------
    lyrics = None
    for section in track_info.get("sections", []):
        if section.get("type") == "LYRICS":
            # Shazam may store lyrics in "text" (list of lines) or another format
            # We'll assume it's a list of lines and join them.
            text_data = section.get("text", [])
            if isinstance(text_data, list):
                lyrics = "\n".join(text_data)
            elif isinstance(text_data, str):
                lyrics = text_data
            else:
                lyrics = None
            break

    # ------------------------------------------------
    # If Shazam didn't provide lyrics, try alternatives
    # ------------------------------------------------
    if not lyrics:
        logger.debug("Shazam lyrics not found, attempting external sources...")
        # 1) Try lyrics.ovh
        alternative_lyrics = fetch_lyrics_from_lyrics_ovh(artist, title)
        if alternative_lyrics:
            lyrics = alternative_lyrics
        else:
            # 2) Try second source
            alternative_lyrics_2 = fetch_lyrics_second_source(artist, title)
            if alternative_lyrics_2:
                lyrics = alternative_lyrics_2

    # ---------------------------------------------
    # Collect and return all extracted information
    # ---------------------------------------------
    metadata = {
        "song_name": title,
        "artist_name": artist,
        "album_name": album,
        "optional_metadata": optional_metadata,  # e.g., year, genre, label, isrc, composer, etc.
        "album_art_file": album_art_file,        # BytesIO or None
        "lyrics": lyrics,
    }
    logger.debug("Metadata collection complete.")
    return metadata


def example_main() -> None:
    """
    Example usage of the gather_song_info function.
    Shows how one might provide a file path,
    then handle the returned metadata.
    """
    # Example local file path (adjust to your environment)
    example_file_path = "path/to/your_song.mp3"

    # We run our async function in a blocking manner for the example
    try:
        metadata = asyncio.run(gather_song_info(example_file_path))
        logger.info(f"Successfully gathered metadata: {metadata.keys()}")
    except RecognitionError as ve:
        logger.error(f"Metadata gathering failed: {ve}")
    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")


if __name__ == "__main__":
    example_main()
