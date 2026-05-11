import os
import logging

from app.tools.make_logger import simple_logger
from app.controllers.song_aquisition.get_check_enhance_song import get_check_enhance_song

logger = simple_logger(__name__)

def main():
    """
    Demonstrates a simple usage example for the YouTube -> Shazam -> ID3 workflow
    without requiring a YouTube Data API key.

    1) Define the artist and song name.
    2) Provide an output directory and optional filename.
    3) Let 'get_check_enhance_song' do the work: search on YouTube (via yt-dlp), download,
       verify via Shazam, attach metadata.
    """
    # Example data:
    artist_name = "Coldplay"  # Adjust to your preference
    song_name = "Viva La Vida"  # Adjust to your preference

    # Output directory (make sure it exists)
    output_dir = "."  # Adjust to your preference

    # Optional: A custom base filename (omit or set to None to let the library auto-generate)
    filename = "coldplay_vivalavida"

    # Maximum number of search results (and verification attempts)
    max_retry = 3

    # Call the integrated workflow
    final_path = get_check_enhance_song(
        artist_name=artist_name,
        song_name=song_name,
        output_directory=output_dir,
        output_filename=filename,
        max_retry=max_retry,
    )

    if final_path:
        logger.info(f"Successfully acquired, verified, and tagged: {final_path}")
    else:
        logger.error("No valid match found after trying all candidates.")


if __name__ == "__main__":
    main()
