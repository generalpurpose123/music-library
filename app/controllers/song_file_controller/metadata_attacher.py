import re
from typing import Any

from mutagen.id3 import (
    ID3,
    APIC,
    USLT,
    TPE1,
    TIT2,
    TALB,
    TCON,
    TSRC,
    TYER,
    WCOP,
    COMM,
    ID3NoHeaderError,
)

from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)


def attach_id3_metadata(mp3_path: str, metadata: dict[str, Any]) -> None:
    """
    Attach the provided metadata dictionary as ID3 tags to the specified MP3 file.

    :param mp3_path: Path to the MP3 file.
    :param metadata: Dictionary containing song metadata.
        Keys expected:
            "song_name" (str): The track title (required)
            "artist_name" (str): The artist name (required)
            "album_name" (str): The album name (fallback "Unknown Album")
            "optional_metadata" (Dict[str, Any]): Additional optional metadata,
                e.g. { "year": "2020" }.
            "album_art_file" (BytesIO or None): Binary image data for album cover.
            "lyrics" (str or None): Song lyrics.

    This function uses mutagen to write ID3v2.3 frames:
      - TPE1 for artist
      - TIT2 for track title
      - TALB for album
      - TYER for year (if present)
      - USLT for lyrics
      - APIC for album cover art

    :return: None
    :raises FileNotFoundError: If the MP3 file is not found.
    :raises Exception: For other unexpected errors (IO, ID3, etc.).
    """
    try:
        try:
            audio = ID3(mp3_path)
        except ID3NoHeaderError:
            logger.debug(f"No existing ID3 header found in {mp3_path}, creating a new one.")
            audio = ID3()

        # ------------------------------------------------
        # 1) Required fields: Song name, Artist
        # ------------------------------------------------
        song_name = metadata.get("song_name")
        artist_name = metadata.get("artist_name")
        if not song_name or not artist_name:
            msg = f"Missing required song_name or artist_name in metadata for file: {mp3_path}"
            logger.error(msg)
            raise ValueError(msg)

        audio["TIT2"] = TIT2(encoding=3, text=song_name)
        audio["TPE1"] = TPE1(encoding=3, text=artist_name)

        # ------------------------------------------------
        # 2) Album name ("Unknown Album" if not found)
        # ------------------------------------------------
        album_name = metadata.get("album_name", "Unknown Album")
        audio["TALB"] = TALB(encoding=3, text=album_name)

        # ------------------------------------------------
        # 3) Optional metadata (like year)
        # ------------------------------------------------
        optional_metadata = metadata.get("optional_metadata", {})
        year = optional_metadata.get("year")
        if year:
            # Shazam's release field may be a full date ("3 August 2015");
            # TYER is a 4-digit-year frame, so extract just the year.
            year_match = re.search(r"\b(\d{4})\b", str(year))
            if year_match:
                audio["TYER"] = TYER(encoding=3, text=year_match.group(1))
            else:
                logger.warning(f"Skipping year frame; no 4-digit year in {year!r}")

        genre = optional_metadata.get("genre")
        if genre:
            audio["TCON"] = TCON(encoding=3, text=genre)

        isrc = optional_metadata.get("isrc")
        if isrc:
            audio["TSRC"] = TSRC(encoding=3, text=isrc)

        # ------------------------------------------------
        # 4) Lyrics
        # ------------------------------------------------
        lyrics_text = metadata.get("lyrics")
        if lyrics_text:
            audio["USLT"] = USLT(encoding=3, desc="Lyrics", text=lyrics_text)

        # ------------------------------------------------
        # 4b) License / copyright URL (e.g. Creative Commons from Jamendo)
        # ------------------------------------------------
        license_url = metadata.get("license_url")
        if license_url:
            audio["WCOP"] = WCOP(url=license_url)
            audio["COMM"] = COMM(
                encoding=3, lang="eng", desc="License",
                text=f"Licensed under: {license_url}",
            )

        # ------------------------------------------------
        # 5) Album cover art
        # ------------------------------------------------
        album_art_file = metadata.get("album_art_file")
        if album_art_file:
            # We'll assume it's JPEG, but if you know the MIME type, pass accordingly
            audio["APIC"] = APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,  # 3 = front cover
                desc="Cover",
                data=album_art_file.getvalue()
            )

        # ------------------------------------------------
        # Save the file
        # ------------------------------------------------
        audio.save(mp3_path, v2_version=3)
        logger.info(f"Successfully attached ID3 metadata to {mp3_path}")

    except FileNotFoundError as fnfe:
        logger.error(f"File not found: {mp3_path} - {fnfe}")
        raise
    except Exception as e:
        logger.exception(f"Error attaching metadata: {e}")
        raise
