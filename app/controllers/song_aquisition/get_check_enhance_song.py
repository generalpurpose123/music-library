import os
import asyncio
from typing import Any, NamedTuple

import yt_dlp

from app.tools.make_logger import simple_logger
from app.tools.track_matching import artists_match, titles_match
from app.controllers.song_aquisition.youtube.yt_dlp_downloader import download_audio_from_youtube
from app.controllers.song_recognition.get_metadata import gather_song_info
from app.controllers.song_file_controller.metadata_attacher import attach_id3_metadata
from app.models.exceptions import DownloadError

logger = simple_logger(__name__)


class SongDownloadResult(NamedTuple):
    """A verified download: file path, Shazam metadata, optional tagging error."""
    path: str
    metadata: dict[str, Any]
    tag_error: str | None = None


def search_youtube_via_yt_dlp(
    artist_name: str,
    song_name: str,
    max_results: int = 5,
    add_lyrics_to_query: bool = True
) -> list[str]:
    """
    Search YouTube for top video results matching "artist_name + song_name (+ lyrics)" using yt-dlp.

    :param artist_name: The artist name to query.
    :param song_name: The track name to query.
    :param max_results: How many search results to retrieve.
    :param add_lyrics_to_query: If True, adds "lyrics" to the query (more likely to find an audio/lyric video).
    :return: A list of YouTube URLs for the top results.
    """
    query = f"{artist_name} {song_name}"
    if add_lyrics_to_query:
        query += " lyrics"

    logger.debug(f"Performing YT search via yt-dlp for: {query}")

    # Construct a ytsearch query: "ytsearchN:" where N is max_results
    ydl_search_query = f"ytsearch{max_results}:{query}"
    urls = []

    ydl_opts = {
        'quiet': True,
        'logger': logger,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(ydl_search_query, download=False)
            entries = info.get('entries', [])
            for entry in entries:
                if entry:
                    webpage_url = entry.get('webpage_url')
                    if webpage_url:
                        urls.append(webpage_url)
    except Exception as e:
        logger.error(f"yt-dlp search request failed: {e}")
        return []

    logger.debug(f"Found {len(urls)} YouTube results using yt-dlp search.")
    return urls


def get_check_enhance_song(
    artist_name: str,
    song_name: str,
    output_directory: str,
    output_filename: str | None = None,
    max_retry: int = 3
) -> SongDownloadResult:
    """
    Search YouTube for the given artist and song using yt-dlp (no API key), download as MP3, verify metadata via Shazam,
    and if correct, attach ID3 tags.

    This function:
      1) Searches YouTube for the query "artist_name song_name lyrics" via yt-dlp.
      2) Iterates through the top results (up to max_retry times).
      3) For each candidate, downloads the audio and extracts metadata via Shazam.
      4) If Shazam recognizes the track as the desired (by matching artist and title), ID3 metadata is attached.
      5) If the track is not recognized correctly, it's deleted and the next candidate is tried.

    :param artist_name: Artist name to query.
    :param song_name: Song name to query.
    :param output_directory: Where to store the downloaded MP3.
    :param output_filename: Optional desired base filename (sans extension). If not given, a name is auto-generated.
    :param max_retry: How many different search results to try before giving up.
    :return: SongDownloadResult with the file path, the Shazam metadata used for
        verification, and tag_error set if ID3 tagging failed.
    :raises DownloadError: If all retry attempts are exhausted without a successful match.
    """
    # 1) Search YouTube (via yt-dlp search)
    youtube_urls = search_youtube_via_yt_dlp(artist_name, song_name, max_results=max_retry)
    if not youtube_urls:
        logger.error("No YouTube results found.")
        raise DownloadError(f"No YouTube results found for: {artist_name} - {song_name}")

    # 2) Iterate over the results, up to max_retry.
    attempts = 0

    for url in youtube_urls:
        if attempts >= max_retry:
            logger.warning("Reached max retries. Aborting...")
            break

        attempts += 1
        logger.info(f"Attempt #{attempts}: Downloading from URL: {url}")

        try:
            downloaded_path = download_audio_from_youtube(url, output_directory, output_filename)
        except Exception as e:
            logger.error(f"Download failed for {url} with error: {e}")
            continue

        # 3) Gather metadata via Shazam.
        try:
            logger.debug(f"Gathering metadata for downloaded file: {downloaded_path}")
            metadata = asyncio.run(gather_song_info(downloaded_path))
        except Exception as e:
            logger.warning(f"Shazam recognition failed for {downloaded_path}, removing file. Error: {e}")
            if os.path.isfile(downloaded_path):
                os.remove(downloaded_path)
            continue

        recognized_artist = metadata.get("artist_name", "")
        recognized_title = metadata.get("song_name", "")

        # Decoration-aware matching: "(feat. X)" / "- Remastered 2020" noise and
        # multi-artist credits are tolerated, remix/live variants are not.
        if artists_match(artist_name, recognized_artist) and titles_match(song_name, recognized_title):
            # 4) Attach ID3 metadata.
            logger.info("Song recognized correctly. Attaching ID3 metadata...")
            tag_error = None
            try:
                attach_id3_metadata(downloaded_path, metadata)
            except Exception as e:
                tag_error = str(e)
                logger.error(f"Failed to attach ID3 metadata: {e}")
            logger.info("Success! Returning final path.")
            return SongDownloadResult(downloaded_path, metadata, tag_error)
        else:
            logger.warning(
                f"Recognized mismatch. Wanted: '{artist_name} - {song_name}', "
                f"Got: '{recognized_artist} - {recognized_title}'. Removing file..."
            )
            if os.path.isfile(downloaded_path):
                os.remove(downloaded_path)

    raise DownloadError(
        f"All {attempts} attempt(s) exhausted without recognizing: {artist_name} - {song_name}"
    )
