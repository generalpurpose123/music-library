"""
music-library — entry point.

Run the Streamlit frontend:
    streamlit run frontend/app.py

Or use the library programmatically:
    from app.controllers.integration.integrate_playlist_to_library import integrate_playlist
    from app.controllers.playlist_aquisition.get_spotify_playlist import get_spotify_playlist

    tracks = get_spotify_playlist("https://open.spotify.com/playlist/...")
    integrate_playlist(tracks, root_folder="/path/to/music", organizing_schema=["artist", "album"])
"""


def main() -> None:
    """Launch the Streamlit frontend."""
    import subprocess
    import sys
    import os

    frontend_path = os.path.join(os.path.dirname(__file__), "frontend", "app.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", frontend_path], check=True)


if __name__ == "__main__":
    main()
