# music-library

A Python tool that builds a local MP3 library from Spotify playlists.

Given a Spotify playlist URL, music-library fetches the track listing, searches YouTube for each track (no API key required), verifies each download using Shazam audio recognition, attaches full ID3 metadata (title, artist, album, year, genre, lyrics, album art), and organises the files into a configurable folder structure.

## Features

- Fetch full track listings from any public Spotify playlist, including paginated playlists over 100 tracks
- Search and download audio from YouTube via yt-dlp — no YouTube API key required
- Verify each download with Shazam recognition before keeping it; retry with the next search result on mismatch
- Attach complete ID3 metadata: title, artist, album, year, genre, ISRC, lyrics, and embedded album art
- Fetch lyrics from Shazam; fall back to lyrics.ovh if Shazam does not provide them
- Organise the library by a configurable schema (e.g. `artist/album/`) with automatic folder creation
- Detect and move files that are already downloaded but placed in the wrong folder
- FastAPI + HTMX web frontend with live job progress (SSE)

## Architecture

The pipeline has four main stages. `get_spotify_playlist` authenticates with the Spotify API using client credentials and returns a list of `{title, artist, album}` dicts, handling pagination automatically. `get_check_enhance_song` takes a single track, searches YouTube via yt-dlp, downloads the top result as an MP3, runs it through Shazam for recognition, and attaches ID3 tags; if the recognised track does not match the target it discards the file and tries the next search result, up to `max_retry` times — it returns a `SongDownloadResult` carrying the file path and the recognition metadata. `gather_song_info` is the Shazam wrapper that also fetches album art and lyrics. `integrate_playlist` is the top-level orchestrator: it checks which tracks from the playlist already exist at their correct paths, moves any that are misplaced (only on a normalized-exact tag match), and calls `get_check_enhance_song` for those that are missing.

## Getting Started

### Prerequisites

- Python 3.12+
- ffmpeg — required by yt-dlp for audio conversion (`sudo apt install ffmpeg` or `brew install ffmpeg`)
- A Spotify Developer account with an app registered at https://developer.spotify.com/dashboard

### Installation

```bash
git clone https://github.com/generalpurpose123/music-library.git
cd music-library
pip install -e ".[dev]"
```

### Credentials Setup

Copy the example env file to the project root and fill in your Spotify credentials:

```bash
cp .env.example .env
```

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
```

Alternatively, start the frontend and enter the credentials on the **Settings** page — it writes the same `.env` file. Credentials take effect immediately; no restart needed.

Get your credentials from https://developer.spotify.com/dashboard — create an app, then copy the Client ID and Client Secret. No redirect URI is needed; this tool uses the Client Credentials flow and does not access private user data. Note: for the same reason it can only read **public** playlists — private, collaborative, and Spotify-generated (editorial) playlists are not accessible.

`.env` is gitignored and must never be committed.

### Running the Frontend

```bash
python main.py
```

Then open http://127.0.0.1:8000. Equivalent alternatives: `music-library-serve` (after `pip install -e .`) or `uvicorn frontend.server:app`.

### Programmatic Usage

```python
from app.controllers.playlist_aquisition.get_spotify_playlist import get_spotify_playlist
from app.controllers.integration.integrate_playlist_to_library import integrate_playlist

# Step 1: fetch the track listing from Spotify
tracks = get_spotify_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")

# Step 2: download missing tracks and organise the library
integrate_playlist(
    playlist=tracks,
    root_folder="/path/to/my/music",
    organizing_schema=["artist", "album"],
)
```

`integrate_playlist` is idempotent — re-running it will skip tracks that are already present.

## Folder Organisation

Files are organised under `root_folder` according to `organizing_schema`. With the default `["artist", "album"]` schema the output looks like:

```
/path/to/my/music/
├── Radiohead/
│   ├── OK Computer/
│   │   └── Radiohead - Karma Police.mp3
│   └── Kid A/
│       └── Radiohead - How to Disappear Completely.mp3
└── Portishead/
    └── Dummy/
        └── Portishead - Glory Box.mp3
```

Filenames follow the pattern `{Artist} - {Title}.mp3`. Special characters are stripped from folder and file names to ensure filesystem compatibility. Featured artists in the artist field (e.g. `feat. ...`) are removed from the folder name.

If `organizing_schema` omits `"album"`, all tracks for an artist are placed directly under the artist folder. A `"wildcard"` token is also supported for grouping by an arbitrary value passed as `wildcard_value`.

## Legal Notice

This tool is intended for **personal, non-commercial use only**, to help organise music you legally own or otherwise have the right to download.

Be aware of what using this tool involves:

- **YouTube:** downloading content is against the YouTube Terms of Service unless YouTube provides an explicit download feature for it. Whether a personal copy is additionally a copyright issue depends on your jurisdiction. In Germany, courts have held — final since 2025 (OLG Hamburg 5 U 54/23; BGH review rejected) — that YouTube's stream obfuscation ("rolling cipher") is an effective technical protection measure under §95a UrhG, and that circumventing it (which yt-dlp-style tools do) is not covered by the §53 private-copy exception.
- **Spotify:** only public playlist metadata (title/artist/album) is read via the official Web API, but using that metadata to source audio elsewhere may conflict with the Spotify Developer Policy. The realistic consequence is revocation of your API credentials.
- **Shazam:** recognition uses an unofficial API via `shazamio`; heavy use may get rate-limited or blocked.

Downloading copyrighted music without the rights holder's permission may be illegal in your jurisdiction. Laws vary by country. It is your responsibility to understand and comply with applicable law and the providers' terms before using this tool.

The authors of this project accept no liability for any misuse, including but not limited to downloading or distributing copyrighted material without authorisation.

Never redistribute downloaded files, serve them beyond your own devices, or use them commercially. Audio files (`.mp3`, `.mp4`, `.flac`, etc.) are gitignored and must never be committed or pushed to GitHub.

## License

Private, personal project — all rights reserved. See [LICENSE](LICENSE). Not licensed for redistribution or third-party use.
