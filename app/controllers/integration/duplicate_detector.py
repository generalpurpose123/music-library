"""
Deep duplicate detection for the music library.

Scans the entire root_folder recursively, reads ID3 tags from every .mp3 file,
and can detect if a track already exists anywhere in the tree using:
  1. Exact sanitized filename match
  2. ID3 TIT2 + TPE1 tag match
  3. Fuzzy similarity (difflib >= threshold, default 0.85)
"""
import os
from difflib import SequenceMatcher
from typing import NamedTuple

from mutagen.id3 import ID3, ID3NoHeaderError

from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)


class LibraryFile(NamedTuple):
    path: str
    title: str   # from ID3 TIT2 or filename
    artist: str  # from ID3 TPE1 or filename


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _read_tags(path: str) -> tuple[str, str]:
    """Return (title, artist) from ID3 tags, falling back to filename parsing."""
    try:
        tags = ID3(path)
        title = str(tags.get("TIT2", "")).strip()
        artist = str(tags.get("TPE1", "")).strip()
        if title and artist:
            return title, artist
    except (ID3NoHeaderError, Exception):
        pass
    # Fallback: parse "Artist - Title.mp3" from filename
    basename = os.path.splitext(os.path.basename(path))[0]
    if " - " in basename:
        parts = basename.split(" - ", 1)
        return parts[1].strip(), parts[0].strip()
    return basename, ""


def scan_library(root_folder: str) -> list[LibraryFile]:
    """Walk root_folder recursively and return metadata for all .mp3 files."""
    results = []
    for dirpath, _, filenames in os.walk(root_folder):
        for fname in filenames:
            if not fname.lower().endswith(".mp3"):
                continue
            full = os.path.join(dirpath, fname)
            title, artist = _read_tags(full)
            results.append(LibraryFile(path=full, title=title, artist=artist))
    logger.debug(f"Scanned {len(results)} MP3 files under {root_folder!r}")
    return results


def find_existing_in_library(
    title: str,
    artist: str,
    library_files: list[LibraryFile],
    threshold: float = 0.85,
) -> LibraryFile | None:
    """
    Search library_files for a track matching (title, artist).
    Strategy (in order):
      1. Exact match on both title and artist (case-insensitive)
      2. ID3 fuzzy match: both title and artist similarity >= threshold
    Returns the best match or None.
    """
    title_l = title.lower().strip()
    artist_l = artist.lower().strip()

    best: LibraryFile | None = None
    best_score: float = 0.0

    for lf in library_files:
        lf_title = lf.title.lower().strip()
        lf_artist = lf.artist.lower().strip()

        # Exact match: fast path
        if lf_title == title_l and lf_artist == artist_l:
            return lf

        # Fuzzy match
        t_sim = _similarity(title, lf.title)
        a_sim = _similarity(artist, lf.artist)
        if t_sim >= threshold and a_sim >= threshold:
            combined = (t_sim + a_sim) / 2
            if combined > best_score:
                best_score = combined
                best = lf

    return best
