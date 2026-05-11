import io
import pytest
from mutagen.id3 import ID3, TIT2, TPE1, TALB


@pytest.fixture
def minimal_mp3(tmp_path):
    """A real minimal valid MP3 file with ID3 tags for testing."""
    mp3_path = tmp_path / "test_song.mp3"
    # Minimal MP3 frame: ID3 header + one null-filled audio frame
    # This is a real ID3v2.3 header + minimal valid MPEG frame
    mp3_bytes = (
        b"ID3\x03\x00\x00\x00\x00\x00\x00"  # ID3v2.3 header (10 bytes, size=0)
        + b"\xff\xfb\x90\x00" + b"\x00" * 413  # Minimal MPEG frame
    )
    mp3_path.write_bytes(mp3_bytes)
    # Write real tags
    tags = ID3()
    tags["TIT2"] = TIT2(encoding=3, text="Test Song")
    tags["TPE1"] = TPE1(encoding=3, text="Test Artist")
    tags["TALB"] = TALB(encoding=3, text="Test Album")
    tags.save(str(mp3_path), v2_version=3)
    return str(mp3_path)


@pytest.fixture
def sample_playlist():
    return [
        {"title": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera"},
        {"title": "Hotel California", "artist": "Eagles", "album": "Hotel California"},
        {"title": "Stairway to Heaven", "artist": "Led Zeppelin", "album": "Led Zeppelin IV"},
    ]


@pytest.fixture
def mock_shazam_response():
    """Minimal valid Shazam response for testing."""
    return {
        "track": {
            "title": "Test Song",
            "subtitle": "Test Artist",
            "images": {"coverarthq": "http://example.com/cover.jpg"},
            "sections": [
                {
                    "type": "SONG",
                    "metadata": [
                        {"title": "Album", "text": "Test Album"},
                        {"title": "Released", "text": "2020"},
                    ]
                },
                {
                    "type": "LYRICS",
                    "text": ["Line one", "Line two", "Line three"]
                }
            ]
        }
    }
