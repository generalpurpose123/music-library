import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import queue
import threading
import textwrap
from typing import List, Dict, Optional

import streamlit as st

# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Music Library",
    page_icon="music_library",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "library_root": "",
    "playlist_tracks": None,       # List[Dict] after fetch
    "playlist_url": "",
    "sync_schema": ["artist", "album"],
    "sync_wildcard": "",
    "download_log_lines": [],
    "download_running": False,
    "download_done": False,
    "download_error": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHEMA_OPTIONS = {
    "artist / album": ["artist", "album"],
    "artist only": ["artist"],
    "artist / album / wildcard": ["artist", "album", "wildcard"],
}

def _credentials_set() -> bool:
    return bool(
        st.session_state.spotify_client_id.strip()
        and st.session_state.spotify_client_secret.strip()
    )


def _patch_spotify_credentials() -> None:
    """Inject current session credentials into the already-imported config module.

    get_spotify_playlist reads SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET at
    call-time via the module-level names, so patching the module dict is
    sufficient — no reload needed.
    """
    import app.config.local_config as cfg
    cfg.SPOTIFY_CLIENT_ID = st.session_state.spotify_client_id.strip()
    cfg.SPOTIFY_CLIENT_SECRET = st.session_state.spotify_client_secret.strip()

    # Also patch the already-imported reference inside get_spotify_playlist
    # (the function re-reads the names from the config module, not a local copy,
    # so the module-level patch above is enough as long as we do it before the call)
    import app.controllers.playlist_aquisition.get_spotify_playlist as gsp_mod
    gsp_mod.SPOTIFY_CLIENT_ID = st.session_state.spotify_client_id.strip()
    gsp_mod.SPOTIFY_CLIENT_SECRET = st.session_state.spotify_client_secret.strip()


# ---------------------------------------------------------------------------
# Queue-based logging handler for streaming progress into the UI
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    """Forwards log records to a thread-safe queue."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tab 1 — Settings
# ---------------------------------------------------------------------------

def render_settings() -> None:
    st.header("Settings")

    st.subheader("Spotify Credentials")
    st.session_state.spotify_client_id = st.text_input(
        "Spotify Client ID",
        value=st.session_state.spotify_client_id,
        type="password",
        key="_input_client_id",
    )
    st.session_state.spotify_client_secret = st.text_input(
        "Spotify Client Secret",
        value=st.session_state.spotify_client_secret,
        type="password",
        key="_input_client_secret",
    )

    st.subheader("Library")
    st.session_state.library_root = st.text_input(
        "Music library root folder",
        value=st.session_state.library_root,
        placeholder="/home/user/Music",
        key="_input_library_root",
    )

    # Status indicator
    if _credentials_set():
        st.success("Spotify credentials: set")
    else:
        st.error("Spotify credentials: missing")

    st.divider()

    st.warning(
        "Clicking **Save Settings** writes your Spotify credentials and library "
        "path directly to `app/config/local_config.py` on disk. "
        "Do not commit that file to version control if it contains real secrets."
    )

    if st.button("Save Settings", type="primary"):
        _save_settings_to_disk()


def _save_settings_to_disk() -> None:
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "config", "local_config.py"
    )
    config_path = os.path.normpath(config_path)

    client_id = st.session_state.spotify_client_id.strip()
    client_secret = st.session_state.spotify_client_secret.strip()
    library_root = st.session_state.library_root.strip()

    lines = [
        f'SPOTIFY_CLIENT_ID = "{client_id}"\n',
        f'SPOTIFY_CLIENT_SECRET = "{client_secret}"\n',
    ]
    if library_root:
        lines.append(f'LIBRARY_ROOT = "{library_root}"\n')

    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        st.success(f"Settings saved to {config_path}")
    except OSError as exc:
        st.error(f"Could not write config file: {exc}")


# ---------------------------------------------------------------------------
# Tab 2 — Sync Playlist
# ---------------------------------------------------------------------------

def render_sync_playlist() -> None:
    st.header("Sync Playlist")

    if not _credentials_set():
        st.warning("Set your Spotify credentials in the **Settings** tab first.")

    playlist_url = st.text_input(
        "Spotify Playlist URL",
        value=st.session_state.playlist_url,
        placeholder="https://open.spotify.com/playlist/...",
        key="_sync_url",
    )
    st.session_state.playlist_url = playlist_url

    schema_label = st.selectbox(
        "Organising schema",
        options=list(SCHEMA_OPTIONS.keys()),
        index=0,
        key="_sync_schema_label",
    )
    selected_schema = SCHEMA_OPTIONS[schema_label]

    wildcard_value: Optional[str] = None
    if "wildcard" in selected_schema:
        wildcard_value = st.text_input(
            "Wildcard folder name",
            value=st.session_state.sync_wildcard,
            placeholder="e.g. Favourites",
            key="_sync_wildcard",
        )
        st.session_state.sync_wildcard = wildcard_value or ""

    st.divider()

    # --- Fetch playlist ---
    if st.button("Fetch Playlist", type="secondary", disabled=not playlist_url.strip()):
        _fetch_playlist(playlist_url)

    if st.session_state.playlist_tracks is not None:
        tracks: List[Dict] = st.session_state.playlist_tracks
        if tracks:
            st.success(f"Found **{len(tracks)}** tracks.")
            st.dataframe(
                tracks,
                use_container_width=True,
                hide_index=True,
            )

            st.divider()
            _render_download_section(selected_schema, wildcard_value)
        else:
            st.warning("No tracks found in this playlist (or fetch failed).")


def _fetch_playlist(url: str) -> None:
    if not _credentials_set():
        st.error("Spotify credentials are not set. Go to Settings tab.")
        return

    _patch_spotify_credentials()

    from app.controllers.playlist_aquisition.get_spotify_playlist import get_spotify_playlist

    with st.spinner("Fetching playlist from Spotify..."):
        try:
            tracks = get_spotify_playlist(url)
            st.session_state.playlist_tracks = tracks
            # Reset download state when a new playlist is fetched
            st.session_state.download_log_lines = []
            st.session_state.download_running = False
            st.session_state.download_done = False
            st.session_state.download_error = None
        except Exception as exc:
            st.error(f"Failed to fetch playlist: {exc}")
            st.session_state.playlist_tracks = []


def _render_download_section(schema: List[str], wildcard_value: Optional[str]) -> None:
    root_folder = st.session_state.library_root.strip()
    if not root_folder:
        st.warning("Set a **Music library root folder** in the Settings tab before downloading.")
        return

    if st.session_state.download_done:
        st.success("Download run complete.")
        if st.button("Reset / run again"):
            st.session_state.download_log_lines = []
            st.session_state.download_running = False
            st.session_state.download_done = False
            st.session_state.download_error = None
            st.rerun()
        _show_log_output()
        return

    if st.session_state.download_running:
        st.info("Download in progress — scroll down for live log.")
        _show_log_output()
        # Poll: rerun every second until the thread signals completion
        # We check a sentinel in session_state set by the thread callback
        import time
        time.sleep(0.8)
        st.rerun()
        return

    if st.button("Start Download", type="primary"):
        _start_download_thread(
            tracks=st.session_state.playlist_tracks,
            root_folder=root_folder,
            schema=schema,
            wildcard_value=wildcard_value,
        )
        st.rerun()

    if st.session_state.download_log_lines:
        _show_log_output()


def _show_log_output() -> None:
    if st.session_state.download_error:
        st.error(f"Error during download: {st.session_state.download_error}")

    if st.session_state.download_log_lines:
        log_text = "\n".join(st.session_state.download_log_lines)
        st.text_area(
            "Progress log",
            value=log_text,
            height=300,
            key="_log_area",
            disabled=True,
        )


def _start_download_thread(
    tracks: List[Dict],
    root_folder: str,
    schema: List[str],
    wildcard_value: Optional[str],
) -> None:
    """Spin up a daemon thread that runs integrate_playlist and drains log records
    into st.session_state.download_log_lines via a shared queue."""

    log_queue: queue.Queue = queue.Queue()
    st.session_state.download_log_lines = []
    st.session_state.download_running = True
    st.session_state.download_done = False
    st.session_state.download_error = None

    def _run() -> None:
        # Attach our queue handler to the root logger so we capture all
        # module loggers created via simple_logger(name).
        root_logger = logging.getLogger()
        handler = _QueueHandler(log_queue)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root_logger.addHandler(handler)

        try:
            from app.controllers.integration.integrate_playlist_to_library import (
                integrate_playlist,
            )
            integrate_playlist(
                playlist=tracks,
                root_folder=root_folder,
                organizing_schema=schema,
                wildcard_value=wildcard_value if wildcard_value else None,
            )
        except Exception as exc:
            log_queue.put(f"ERROR: {exc}")
            st.session_state.download_error = str(exc)
        finally:
            root_logger.removeHandler(handler)
            log_queue.put(None)  # sentinel

    def _drain() -> None:
        """Drain the queue into session_state from the main thread perspective.
        This function itself runs in a second daemon thread so we don't block
        the Streamlit rerun loop — session_state is safe to write from threads
        in Streamlit >= 1.18."""
        _run_thread = threading.Thread(target=_run, daemon=True)
        _run_thread.start()
        while True:
            try:
                msg = log_queue.get(timeout=30)
            except queue.Empty:
                break
            if msg is None:
                break
            st.session_state.download_log_lines.append(msg)
        _run_thread.join()
        st.session_state.download_running = False
        st.session_state.download_done = True

    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()


# ---------------------------------------------------------------------------
# Tab 3 — Browse Library
# ---------------------------------------------------------------------------

def render_browse_library() -> None:
    st.header("Browse Library")

    scan_folder = st.text_input(
        "Folder to scan",
        value=st.session_state.library_root,
        placeholder="/home/user/Music",
        key="_browse_folder",
    )

    if st.button("Scan Library", type="secondary", disabled=not scan_folder.strip()):
        _scan_library(scan_folder.strip())


def _scan_library(folder: str) -> None:
    if not os.path.isdir(folder):
        st.error(f"Directory not found: {folder}")
        return

    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TALB
    except ImportError:
        st.error(
            "mutagen is not installed. Install it with: pip install mutagen"
        )
        return

    mp3_files = []
    for dirpath, _dirs, filenames in os.walk(folder):
        for fname in filenames:
            if fname.lower().endswith(".mp3"):
                mp3_files.append(os.path.join(dirpath, fname))

    if not mp3_files:
        st.info("No MP3 files found in the selected folder.")
        return

    rows = []
    for path in sorted(mp3_files):
        title = artist = album = ""
        try:
            tags = ID3(path)
            title = str(tags.get("TIT2", ""))
            artist = str(tags.get("TPE1", ""))
            album = str(tags.get("TALB", ""))
        except Exception:
            pass  # File has no ID3 tags — leave blank
        rows.append(
            {
                "File": os.path.relpath(path, folder),
                "Title": title,
                "Artist": artist,
                "Album": album,
            }
        )

    st.success(f"Found **{len(rows)}** MP3 files.")
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab 4 — Single Song Download
# ---------------------------------------------------------------------------

def render_single_song() -> None:
    st.header("Single Song Download")

    artist = st.text_input("Artist name", key="_single_artist")
    song = st.text_input("Song name", key="_single_song")
    output_folder = st.text_input(
        "Output folder",
        value=st.session_state.library_root,
        placeholder="/home/user/Music",
        key="_single_output",
    )

    ready = bool(artist.strip() and song.strip() and output_folder.strip())

    if st.button("Download", type="primary", disabled=not ready):
        _download_single_song(
            artist=artist.strip(),
            song=song.strip(),
            output_folder=output_folder.strip(),
        )


def _download_single_song(artist: str, song: str, output_folder: str) -> None:
    if not os.path.isdir(output_folder):
        try:
            os.makedirs(output_folder, exist_ok=True)
        except OSError as exc:
            st.error(f"Cannot create output folder: {exc}")
            return

    progress_placeholder = st.empty()

    # Capture logs into a list while the download runs
    log_lines: List[str] = []
    log_q: queue.Queue = queue.Queue()

    root_logger = logging.getLogger()
    handler = _QueueHandler(log_q)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(handler)

    result_path: Optional[str] = None
    error_msg: Optional[str] = None

    with st.spinner(f"Downloading '{artist} - {song}'..."):
        try:
            from app.controllers.song_aquisition.get_check_enhance_song import (
                get_check_enhance_song,
            )
            result_path = get_check_enhance_song(
                artist_name=artist,
                song_name=song,
                output_directory=output_folder,
                output_filename=None,
                max_retry=3,
            )
        except Exception as exc:
            error_msg = str(exc)
        finally:
            root_logger.removeHandler(handler)
            # Drain remaining log records
            while not log_q.empty():
                try:
                    msg = log_q.get_nowait()
                    if msg is not None:
                        log_lines.append(msg)
                except queue.Empty:
                    break

    if error_msg:
        st.error(f"Download failed: {error_msg}")
    elif result_path:
        st.success(f"Downloaded successfully: `{result_path}`")
    else:
        st.warning(
            "Download completed but no file was returned. "
            "The song may not have been recognised by Shazam. Check the log below."
        )

    if log_lines:
        st.text_area(
            "Download log",
            value="\n".join(log_lines),
            height=200,
            disabled=True,
        )


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

st.title("Music Library")

tab_settings, tab_sync, tab_browse, tab_single = st.tabs(
    ["Settings", "Sync Playlist", "Browse Library", "Single Song Download"]
)

with tab_settings:
    render_settings()

with tab_sync:
    render_sync_playlist()

with tab_browse:
    render_browse_library()

with tab_single:
    render_single_song()
