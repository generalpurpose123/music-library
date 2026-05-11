import os

import yt_dlp

from app.tools.make_logger import simple_logger

logger = simple_logger(__name__)

def download_audio_from_youtube(
    youtube_url: str,
    output_directory: str,
    output_filename: str | None = None
) -> str:
    """
    Download audio from the given YouTube URL and save it in the specified directory using yt-dlp.

    :param youtube_url: The URL of the YouTube video to download.
    :param output_directory: The directory where the downloaded file will be saved.
    :param output_filename: Optional. If provided, the downloaded file will use this name (sans extension).
    :return: The full path to the downloaded audio file.
    :raises FileNotFoundError: If the output directory does not exist.
    :raises Exception: For other unexpected download errors.
    """
    if not os.path.isdir(output_directory):
        error_msg = f"Output directory '{output_directory}' does not exist."
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    # If no specific filename is given, let yt-dlp handle the naming based on the video title.
    # We'll force mp3 in the post-processing.

    if not output_filename:
        outtmpl = os.path.join(output_directory, '%(title)s.%(ext)s')
    else:
        outtmpl = os.path.join(output_directory, f'{output_filename}.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': outtmpl,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }
        ],
        'logger': logger,
        'quiet': True,  # We'll handle logging ourselves.
    }

    try:
        logger.debug(f"Starting download for URL: {youtube_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            downloaded_filename = ydl.prepare_filename(info)

        # yt-dlp may produce an output file without .mp3 if postprocessor fails.
        # Typically, it's .mp3. We'll guess the final name:
        base, _ = os.path.splitext(downloaded_filename)
        final_filename = f"{base}.mp3"

        logger.info(f"Successfully downloaded audio to {final_filename}")
        return final_filename
    except Exception as e:
        logger.exception(f"Failed to download audio from {youtube_url}: {e}")
        raise


if __name__ == "__main__":
    download_audio_from_youtube(
        youtube_url="https://www.youtube.com/watch?v=LOZuxwVk7TU",
        output_directory="/home/johnny/PycharmProjects/music_library/app/controllers/song_aquisition",
        output_filename="test_audio.mp3"
    )