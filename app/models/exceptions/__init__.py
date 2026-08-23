class MusicLibraryError(Exception):
    """Base exception for all music-library errors."""

class DownloadError(MusicLibraryError):
    """Raised when a song cannot be downloaded from YouTube."""

class RecognitionError(MusicLibraryError):
    """Raised when Shazam fails to recognise a track."""

class PlaylistFetchError(MusicLibraryError):
    """Raised when a Spotify playlist cannot be retrieved."""

class LibraryError(MusicLibraryError):
    """Raised for library filesystem errors (moves, reads, writes)."""

class CredentialsError(MusicLibraryError):
    """Raised when required API credentials are missing or invalid."""

class TrackListParseError(MusicLibraryError):
    """Raised when a pasted or uploaded track list cannot be parsed."""
