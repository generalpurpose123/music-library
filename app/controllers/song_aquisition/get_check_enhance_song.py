import os
import asyncio

import yt_dlp

from app.tools.make_logger import simple_logger
from app.controllers.song_aquisition.youtube.yt_dlp_downloader import download_audio_from_youtube
from app.controllers.song_recognition.get_metadata import gather_song_info
from app.controllers.song_file_controller.metadata_attacher import attach_id3_metadata

logger = simple_logger(__name__)


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
) -> str | None:
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
    :return: The path to the successfully recognized and tagged MP3 file, or None if unsuccessful.
    """
    # 1) Search YouTube (via yt-dlp search)
    youtube_urls = search_youtube_via_yt_dlp(artist_name, song_name, max_results=max_retry)
    if not youtube_urls:
        logger.error("No YouTube results found.")
        return None

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

        recognized_artist = metadata.get("artist_name", "").lower()
        recognized_title = metadata.get("song_name", "").lower()

        # Check if recognized artist and title match what we want.
        # For demonstration, we do a simple "in" check.

        if (artist_name.lower() in recognized_artist) and (song_name.lower() in recognized_title):
            # 4) Attach ID3 metadata.
            logger.info("Song recognized correctly. Attaching ID3 metadata...")
            try:
                attach_id3_metadata(downloaded_path, metadata)
            except Exception as e:
                logger.error(f"Failed to attach ID3 metadata: {e}")
            logger.info("Success! Returning final path.")
            return downloaded_path
        else:
            logger.warning(
                f"Recognized mismatch. Wanted: '{artist_name} - {song_name}', "
                f"Got: '{recognized_artist} - {recognized_title}'. Removing file..."
            )
            if os.path.isfile(downloaded_path):
                os.remove(downloaded_path)

    logger.error("All attempts exhausted or failed. No successful recognition.")
    return None
