import os
import re
import shutil
import asyncio
from typing import Any

from app.tools.make_logger import simple_logger
from app.controllers.song_recognition.get_metadata import gather_song_info

logger = simple_logger(__name__)

def sanitize_fs_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\s_-]", "", s).strip()

def strip_feature(artist: str) -> str:
    return re.sub(r"\(feat[^)]*\)|\[feat[^]]*\]", "", artist, flags=re.IGNORECASE).strip()

def build_path(
    root_folder: str,
    organizing_schema: list[str],
    title: str,
    artist: str,
    album: str | None = None,
    wildcard_value: str | None = None,
) -> str:
    safe_artist = sanitize_fs_name(strip_feature(artist))
    safe_title = sanitize_fs_name(title)
    safe_album = None if (album is None or album.lower() == "unknown album") else sanitize_fs_name(album)
    safe_wildcard = sanitize_fs_name(wildcard_value) if wildcard_value else None
    parts = [root_folder]
    for keyword in organizing_schema:
        if keyword == "artist":
            parts.append(safe_artist)
        elif keyword == "title":
            pass
        elif keyword == "album" and safe_album:
            parts.append(safe_album)
        elif keyword == "wildcard" and safe_wildcard:
            parts.append(safe_wildcard)
        else:
            pass
    dir_path = os.path.join(*parts)
    filename = f"{safe_artist} - {safe_title}"
    return os.path.join(dir_path, filename)

def find_existing_files(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None
) -> list[str]:
    existing = []
    for track in playlist:
        title = track.get("title")
        artist = track.get("artist")
        album = track.get("album")
        correct_path_no_ext = build_path(
            root_folder,
            organizing_schema,
            title,
            artist,
            album=album,
            wildcard_value=wildcard_value,
        )
        correct_mp3_path = correct_path_no_ext + ".mp3"
        if os.path.isfile(correct_mp3_path):
            existing.append(correct_mp3_path)
    return existing

def move_incorrectly_placed_files(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None
) -> None:
    for track in playlist:
        title = track.get("title")
        artist = track.get("artist")
        album = track.get("album")
        correct_path_no_ext = build_path(
            root_folder,
            organizing_schema,
            title,
            artist,
            album=album,
            wildcard_value=wildcard_value,
        )
        correct_mp3_path = correct_path_no_ext + ".mp3"
        if not os.path.isfile(correct_mp3_path):
            file_basename = os.path.basename(correct_mp3_path)
            for dirpath, dirnames, filenames in os.walk(root_folder):
                if file_basename in filenames:
                    current_full_path = os.path.join(dirpath, file_basename)
                    if current_full_path != correct_mp3_path:
                        logger.info(f"Moving '{current_full_path}' -> '{correct_mp3_path}'")
                        os.makedirs(os.path.dirname(correct_mp3_path), exist_ok=True)
                        shutil.move(current_full_path, correct_mp3_path)
                    break

def download_missing_songs(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None
) -> None:
    from app.controllers.song_aquisition.get_check_enhance_song import get_check_enhance_song
    for track in playlist:
        title = track.get("title")
        artist = track.get("artist")
        if artist and "," in artist:
            artist = artist.split(",", 1)[0].strip()
        album = track.get("album")
        correct_path_no_ext = build_path(
            root_folder,
            organizing_schema,
            title,
            artist,
            album=album,
            wildcard_value=wildcard_value,
        )
        correct_mp3_path = correct_path_no_ext + ".mp3"
        if not os.path.isfile(correct_mp3_path):
            logger.info(f"Downloading missing track: {artist} - {title}")
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="download_tmp_")
            try:
                result_path = get_check_enhance_song(
                    artist_name=artist,
                    song_name=title,
                    output_directory=temp_dir,
                    output_filename=None,
                    max_retry=3,
                )
                if result_path:
                    os.makedirs(os.path.dirname(correct_mp3_path), exist_ok=True)
                    shutil.move(result_path, correct_mp3_path)
                    recognized_metadata = asyncio.run(gather_song_info(correct_mp3_path))
                    track["album"] = recognized_metadata.get("album_name", "Unknown Album")
                    new_path_no_ext = build_path(
                        root_folder,
                        organizing_schema,
                        title,
                        artist,
                        album=track["album"],
                        wildcard_value=wildcard_value,
                    )
                    new_mp3_path = new_path_no_ext + ".mp3"
                    if new_mp3_path != correct_mp3_path:
                        os.makedirs(os.path.dirname(new_mp3_path), exist_ok=True)
                        shutil.move(correct_mp3_path, new_mp3_path)
                    logger.info(f"Saved to library at {new_mp3_path if os.path.isfile(new_mp3_path) else correct_mp3_path}")
                else:
                    logger.warning(f"Failed to download track: {artist} - {title}")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

def integrate_playlist(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None
) -> None:
    existing = find_existing_files(
        playlist,
        root_folder,
        organizing_schema,
        wildcard_value=wildcard_value
    )
    logger.info(f"Already have {len(existing)} songs in correct folder.")
    move_incorrectly_placed_files(
        playlist,
        root_folder,
        organizing_schema,
        wildcard_value=wildcard_value
    )
    download_missing_songs(
        playlist,
        root_folder,
        organizing_schema,
        wildcard_value=wildcard_value
    )
