"""
Parse user-supplied track lists (pasted text or exported CSV) into the
[{"title": ..., "artist": ...}, ...] shape that integrate_playlist expects.

This is the Spotify-API-free import path: users export their playlist with a
compliant tool (Chosic's exporter, Exportify, or Spotify's official privacy
data export) and paste/upload the result — no app registration or Premium
subscription needed.
"""
import csv
import io
import re

from app.tools.make_logger import simple_logger
from app.models.exceptions import TrackListParseError

logger = simple_logger(__name__)

# "Artist - Title" with hyphen, en dash or em dash; the separator must be
# surrounded by whitespace so hyphenated names ("Jay-Z") don't split.
_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+")

# Column-header aliases (lowercased) seen in common exports:
# Exportify: "Track Name" / "Artist Name(s)"; Chosic: "Song" / "Artist".
_TITLE_COLUMNS = ("track name", "song", "title", "name")
_ARTIST_COLUMNS = ("artist name(s)", "artist name", "artists", "artist")


def parse_track_list(text: str) -> list[dict[str, str]]:
    """
    Parse plain-text lines of the form "Artist - Title" (also en/em dashes).

    Blank lines and lines without a separator are skipped with a log warning.

    :param text: The pasted text, one track per line.
    :return: List of {"title", "artist"} dicts.
    :raises TrackListParseError: If no line could be parsed.
    """
    tracks = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _SEPARATOR_RE.split(line, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            skipped += 1
            logger.warning(f"Skipping unparseable line: {line!r}")
            continue
        artist, title = parts[0].strip(), parts[1].strip()
        tracks.append({"title": title, "artist": artist})

    if not tracks:
        raise TrackListParseError(
            "No tracks could be parsed. Expected one track per line in the form "
            '"Artist - Title" (e.g. "Madonna - La Isla Bonita").'
        )
    if skipped:
        logger.warning(f"Skipped {skipped} unparseable line(s).")
    return tracks


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.strip().lower(): name for name in fieldnames if name}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def parse_track_csv(content: str) -> list[dict[str, str]]:
    """
    Parse a CSV export (Exportify, Chosic, or similar) into a track list.

    Columns are detected by header, case-insensitively; the delimiter is
    sniffed. Multi-artist cells are kept comma-joined — the download pipeline
    uses the first artist for matching, same as the Spotify flow.

    :param content: Decoded text content of the CSV file.
    :return: List of {"title", "artist"} dicts.
    :raises TrackListParseError: If headers are missing or no rows parse.
    """
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        raise TrackListParseError("The uploaded file is empty.")

    title_col = _find_column(reader.fieldnames, _TITLE_COLUMNS)
    artist_col = _find_column(reader.fieldnames, _ARTIST_COLUMNS)
    if not title_col or not artist_col:
        raise TrackListParseError(
            "Could not find title/artist columns in the CSV. Expected headers "
            'like "Track Name"/"Artist Name(s)" (Exportify) or "Song"/"Artist" (Chosic); '
            f"got: {', '.join(reader.fieldnames)}"
        )

    tracks = []
    for row in reader:
        title = (row.get(title_col) or "").strip()
        artist = (row.get(artist_col) or "").strip()
        if not title or not artist:
            continue
        tracks.append({"title": title, "artist": artist})

    if not tracks:
        raise TrackListParseError("The CSV contained no rows with both a title and an artist.")
    return tracks
