"""
Pluggable audio-source providers.

Each provider acquires a single track as a tagged local MP3 from one source
(YouTube, Jamendo, Internet Archive, ...). The `registry` selects which
providers a given acquisition `mode` uses.
"""
from app.controllers.song_aquisition.providers.base import (
    AudioSourceProvider,
    SongDownloadResult,
)

__all__ = ["AudioSourceProvider", "SongDownloadResult"]
