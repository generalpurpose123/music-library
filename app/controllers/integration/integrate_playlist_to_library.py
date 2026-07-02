import os
import re
import shutil
import tempfile
import time
from typing import Any

from app.tools.make_logger import simple_logger
from app.controllers.song_aquisition.get_check_enhance_song import (
    SongDownloadResult,
    get_check_enhance_song,
)
from app.models.exceptions import DownloadError, LibraryError

logger = simple_logger(__name__)

VALID_SCHEMA_KEYWORDS = {"artist", "album", "title", "wildcard"}


def sanitize_fs_name(s: str) -> str:
    # Strip filesystem-unsafe characters (/, :, *, ?, ", <, >, |, etc.) while
    # preserving Unicode letters and digits so names like "Björk" are not mangled.
    return re.sub(r"[^\w\s_-]", "", s, flags=re.UNICODE).strip()

def strip_feature(artist: str) -> str:
    return re.sub(r"\(feat[^)]*\)|\[feat[^]]*\]", "", artist, flags=re.IGNORECASE).strip()


def _safe_resolve(path: str, root: str) -> str:
    """Raise ValueError if resolved path escapes root_folder.

    Guards against path traversal attacks where a malicious playlist entry
    such as '../../etc/passwd' could cause reads or writes outside the library root.
    """
    resolved = os.path.realpath(path)
    root_resolved = os.path.realpath(root)
    if not resolved.startswith(root_resolved + os.sep) and resolved != root_resolved:
        raise ValueError(f"Path escapes root folder: {path!r}")
    return resolved


def _check_disk_space(path: str, min_bytes: int = 500 * 1024 * 1024) -> None:
    """Raise LibraryError if less than min_bytes free (default 500 MB)."""
    free = shutil.disk_usage(path).free
    if free < min_bytes:
        raise LibraryError(
            f"Insufficient disk space: {free // (1024 * 1024)} MB free, "
            f"need at least {min_bytes // (1024 * 1024)} MB"
        )


def build_path(
    root_folder: str,
    organizing_schema: list[str],
    title: str,
    artist: str,
    album: str | None = None,
    wildcard_value: str | None = None,
) -> str:
    unknown = set(organizing_schema) - VALID_SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(f"Unknown schema keywords: {unknown}. Valid: {VALID_SCHEMA_KEYWORDS}")

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


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _try_move_existing(
    title: str,
    artist: str,
    correct_mp3_path: str,
    root_folder: str,
    library_files: list | None = None,
) -> bool:
    """
    Use deep duplicate detection (ID3 tags + fuzzy matching) to find this track
    anywhere in root_folder. If found at a different path, move it to
    correct_mp3_path and return True. Returns False if no existing copy is found.

    Pass library_files to reuse a previously scanned snapshot (avoids O(N*M) scans
    when processing an entire playlist — call scan_library() once and pass the result).
    """
    from app.controllers.integration.duplicate_detector import scan_library, find_existing_in_library

    if library_files is None:
        library_files = scan_library(root_folder)
    match = find_existing_in_library(title, artist, library_files)
    if match is None:
        return False
    if match.path == correct_mp3_path:
        # Already in the right place; the caller's isfile() check will catch this
        return False
    logger.info(f"Moving '{match.path}' -> '{correct_mp3_path}'")
    try:
        os.makedirs(os.path.dirname(correct_mp3_path), exist_ok=True)
        shutil.move(match.path, correct_mp3_path)
    except OSError as exc:
        raise LibraryError(f"Failed to move file to '{correct_mp3_path}'") from exc
    return True


def _download_single_track(
    artist: str,
    title: str,
    correct_mp3_path: str,
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None,
    album: str | None = None,
) -> SongDownloadResult | None:
    """
    Download one track into a temp directory and move it to correct_mp3_path.
    When the playlist did not provide an album, the file is relocated to a
    path built from the Shazam-recognized album instead (metadata reused from
    download verification — no second recognition pass).
    Returns a SongDownloadResult with the final path, None if nothing was downloaded.
    """
    # Normalise multi-artist fields the same way the rest of the module does
    download_artist = artist.split(",", 1)[0].strip() if artist and "," in artist else artist

    temp_dir = tempfile.mkdtemp(prefix="download_tmp_")
    try:
        result = get_check_enhance_song(
            artist_name=download_artist,
            song_name=title,
            output_directory=temp_dir,
            output_filename=None,
            max_retry=3,
        )
        if not result:
            return None

        try:
            os.makedirs(os.path.dirname(correct_mp3_path), exist_ok=True)
            shutil.move(result.path, correct_mp3_path)
        except OSError as exc:
            raise LibraryError(f"Failed to place downloaded file at '{correct_mp3_path}'") from exc

        if album is not None:
            # The playlist supplied the album, so correct_mp3_path was already
            # built album-aware — expected path == final path, no relocation.
            final_path = correct_mp3_path
        else:
            shazam_album = result.metadata.get("album_name", "Unknown Album")
            new_path_no_ext = build_path(
                root_folder,
                organizing_schema,
                title,
                artist,
                album=shazam_album,
                wildcard_value=wildcard_value,
            )
            new_mp3_path = new_path_no_ext + ".mp3"
            if new_mp3_path != correct_mp3_path:
                try:
                    os.makedirs(os.path.dirname(new_mp3_path), exist_ok=True)
                    shutil.move(correct_mp3_path, new_mp3_path)
                except OSError as exc:
                    raise LibraryError(f"Failed to move file to final path '{new_mp3_path}'") from exc

            final_path = new_mp3_path if os.path.isfile(new_mp3_path) else correct_mp3_path
        logger.info(f"Saved to library at {final_path}")
        return result._replace(path=final_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Backward-compatible public functions (kept for external callers)
# ---------------------------------------------------------------------------

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
        _safe_resolve(correct_mp3_path, root_folder)
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
        _safe_resolve(correct_mp3_path, root_folder)
        if not os.path.isfile(correct_mp3_path):
            _try_move_existing(title, artist, correct_mp3_path, root_folder)


def download_missing_songs(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None
) -> None:
    _check_disk_space(root_folder)

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
        _safe_resolve(correct_mp3_path, root_folder)
        if not title or not artist:
            logger.warning(f"Skipping track with missing title or artist in playlist entry: {track!r}")
            continue

        if not os.path.isfile(correct_mp3_path):
            logger.info(f"Downloading missing track: {artist} - {title}")
            try:
                result = _download_single_track(
                    artist, title, correct_mp3_path, root_folder, organizing_schema, wildcard_value,
                    album=album,
                )
                if not result:
                    logger.warning(f"Failed to download track: {artist} - {title}")
            except DownloadError as exc:
                logger.warning(f"Could not download '{artist} - {title}': {exc}")


# ---------------------------------------------------------------------------
# Primary entry point — job-aware with crash recovery
# ---------------------------------------------------------------------------

def integrate_playlist(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None = None,
    resume: bool = True,
) -> "Job":  # noqa: F821 — type alias; Job imported locally to avoid circular imports
    from app.controllers.integration.job_state import (
        new_job,
        find_resumable_job,
        cleanup_orphaned_temp_dirs,
        LibraryLock,
        TrackStatus,
        Job,
    )

    cleanup_orphaned_temp_dirs(root_folder)

    with LibraryLock(root_folder):
        job = find_resumable_job(root_folder, playlist, organizing_schema) if resume else None
        if job:
            done_count = sum(1 for t in job.tracks if t.status == TrackStatus.DONE)
            logger.info(f"Resuming job {job.job_id} ({done_count} tracks already done)")
        else:
            job = new_job(playlist, root_folder, organizing_schema, wildcard_value)
            logger.info(f"Starting new job {job.job_id} ({len(job.tracks)} tracks)")
        job.save()

        # Scan the library once so every _try_move_existing call reuses the snapshot.
        from app.controllers.integration.duplicate_detector import scan_library
        library_snapshot = scan_library(root_folder)

        for track_job in job.tracks:
            if track_job.status in (TrackStatus.DONE, TrackStatus.SKIPPED):
                continue  # Already handled in a previous run

            # Guard against playlists with missing title/artist fields.
            if not track_job.title or not track_job.artist:
                logger.warning(f"Skipping track with missing title or artist: {track_job!r}")
                track_job.status = TrackStatus.FAILED
                track_job.error = "Missing title or artist"
                job.save()
                continue

            correct_path_no_ext = build_path(
                root_folder,
                organizing_schema,
                track_job.title,
                track_job.artist,
                album=track_job.album,
                wildcard_value=wildcard_value,
            )
            correct_mp3_path = correct_path_no_ext + ".mp3"
            _safe_resolve(correct_mp3_path, root_folder)

            # Check if already at correct location
            if os.path.isfile(correct_mp3_path):
                track_job.status = TrackStatus.SKIPPED
                track_job.target_path = correct_mp3_path
                job.save()
                continue

            # Try to find and move existing misplaced file using fuzzy duplicate detection.
            # Pass the cached library snapshot to avoid re-scanning for every track.
            moved = _try_move_existing(track_job.title, track_job.artist, correct_mp3_path, root_folder, library_snapshot)
            if moved:
                track_job.status = TrackStatus.SKIPPED
                track_job.target_path = correct_mp3_path
                job.save()
                continue

            # Download
            track_job.status = TrackStatus.DOWNLOADING
            track_job.started_at = time.time()
            job.save()

            try:
                result = _download_single_track(
                    track_job.artist,
                    track_job.title,
                    correct_mp3_path,
                    root_folder,
                    organizing_schema,
                    wildcard_value,
                    album=track_job.album,
                )
                if result:
                    track_job.status = TrackStatus.DONE
                    track_job.target_path = result.path
                    track_job.completed_at = time.time()
                    if result.tag_error:
                        track_job.error = f"warning: ID3 tagging failed: {result.tag_error}"
                else:
                    track_job.status = TrackStatus.FAILED
                    track_job.error = "Download returned no file"
            except Exception as exc:
                track_job.status = TrackStatus.FAILED
                track_job.error = str(exc)
                logger.error(f"Track {track_job.artist} - {track_job.title} failed: {exc}")
            finally:
                job.save()

        job.completed_at = time.time()
        job.save()

        done = sum(1 for t in job.tracks if t.status == TrackStatus.DONE)
        skipped = sum(1 for t in job.tracks if t.status == TrackStatus.SKIPPED)
        failed = sum(1 for t in job.tracks if t.status == TrackStatus.FAILED)
        logger.info(
            f"Job {job.job_id} complete: {done} downloaded, {skipped} already present, {failed} failed"
        )
        return job
