"""
Tests for duplicate_detector.py

Covers:
  - scan_library: finds .mp3 files, reads ID3 tags, falls back to filename
  - find_existing_in_library: exact match, fuzzy match, no match, artist mismatch,
    below-threshold no match
  - Integration: scan + find flow
"""
import os
import pytest
from unittest.mock import patch

from mutagen.id3 import ID3, TIT2, TPE1

from app.controllers.integration.duplicate_detector import (
    LibraryFile,
    scan_library,
    find_existing_in_library,
)


def _write_tagged_mp3(path: str, title: str, artist: str) -> None:
    """Write a minimal MP3 with ID3 tags at path (creates parent dirs)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Write minimal raw bytes first, then save tags
    with open(path, "wb") as f:
        f.write(b"\xff\xfb\x90\x00" + b"\x00" * 417)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.save(path, v2_version=3)


def _write_untagged_mp3(path: str) -> None:
    """Write raw bytes with NO ID3 header — fallback to filename parsing."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\xff\xfb\x90\x00" * 10)


# ---------------------------------------------------------------------------
# scan_library
# ---------------------------------------------------------------------------

class TestScanLibrary:
    def test_finds_mp3_files_in_nested_dirs(self, tmp_path):
        sub = tmp_path / "Artist" / "Album"
        sub.mkdir(parents=True)
        mp3_path = str(sub / "song.mp3")
        _write_tagged_mp3(mp3_path, "My Song", "My Artist")

        results = scan_library(str(tmp_path))

        assert len(results) == 1
        assert results[0].path == mp3_path

    def test_reads_id3_tags_correctly(self, tmp_path):
        mp3_path = str(tmp_path / "track.mp3")
        _write_tagged_mp3(mp3_path, "Tagged Song", "Tagged Artist")

        results = scan_library(str(tmp_path))

        assert results[0].title == "Tagged Song"
        assert results[0].artist == "Tagged Artist"

    def test_falls_back_to_filename_when_no_tags(self, tmp_path):
        # Filename pattern: "Artist - Title.mp3"
        mp3_path = str(tmp_path / "Some Artist - Great Song.mp3")
        _write_untagged_mp3(mp3_path)

        results = scan_library(str(tmp_path))

        assert len(results) == 1
        # Fallback parses "Title" from "Artist - Title"
        assert results[0].title == "Great Song"
        assert results[0].artist == "Some Artist"

    def test_ignores_non_mp3_files(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        (tmp_path / "notes.txt").write_text("some text")
        mp3_path = str(tmp_path / "song.mp3")
        _write_tagged_mp3(mp3_path, "Song", "Artist")

        results = scan_library(str(tmp_path))

        assert len(results) == 1

    def test_empty_directory_returns_empty_list(self, tmp_path):
        results = scan_library(str(tmp_path))
        assert results == []

    def test_multiple_files_all_found(self, tmp_path):
        for i in range(3):
            p = str(tmp_path / f"song_{i}.mp3")
            _write_tagged_mp3(p, f"Song {i}", f"Artist {i}")

        results = scan_library(str(tmp_path))

        assert len(results) == 3

    def test_filename_without_separator_uses_full_name_as_title(self, tmp_path):
        mp3_path = str(tmp_path / "justasong.mp3")
        _write_untagged_mp3(mp3_path)

        results = scan_library(str(tmp_path))

        assert results[0].title == "justasong"


# ---------------------------------------------------------------------------
# find_existing_in_library
# ---------------------------------------------------------------------------

class TestFindExistingInLibrary:
    def _make_library(self, entries):
        return [LibraryFile(path=f"/lib/{t}.mp3", title=t, artist=a) for t, a in entries]

    def test_exact_match_found(self):
        library = self._make_library([
            ("Bohemian Rhapsody", "Queen"),
            ("Hotel California", "Eagles"),
        ])
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library)
        assert result is not None
        assert result.title == "Bohemian Rhapsody"
        assert result.artist == "Queen"

    def test_exact_match_case_insensitive(self):
        library = self._make_library([("bohemian rhapsody", "queen")])
        result = find_existing_in_library("BOHEMIAN RHAPSODY", "QUEEN", library)
        assert result is not None

    def test_no_match_returns_none(self):
        library = self._make_library([("Hotel California", "Eagles")])
        result = find_existing_in_library("Stairway to Heaven", "Led Zeppelin", library)
        assert result is None

    def test_artist_mismatch_no_match(self):
        library = self._make_library([("Bohemian Rhapsody", "Wrong Artist")])
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library)
        # Artist similarity will be low → no match
        assert result is None

    def test_fuzzy_match_similar_title(self):
        # "Bohemian Rhapsody (Remastered)" vs "Bohemian Rhapsody" should match
        library = self._make_library([("Bohemian Rhapsody Remastered", "Queen")])
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library, threshold=0.7)
        assert result is not None

    def test_below_threshold_returns_none(self):
        library = self._make_library([("Completely Different Title", "Queen")])
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library, threshold=0.85)
        assert result is None

    def test_empty_library_returns_none(self):
        result = find_existing_in_library("Song", "Artist", [])
        assert result is None

    def test_best_fuzzy_match_returned(self):
        library = [
            LibraryFile(path="/a.mp3", title="Bohemian Rhapsody Remix", artist="Queen"),
            LibraryFile(path="/b.mp3", title="Bohemian Rhapsody", artist="Queen"),  # exact
        ]
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library)
        # Exact match (second entry) should win
        assert result.path == "/b.mp3"


class TestExactOnly:
    def _make_library(self, entries):
        return [LibraryFile(path=f"/lib/{t}.mp3", title=t, artist=a) for t, a in entries]

    def test_decorated_title_is_normalized_exact(self):
        """Feat/remaster decorations still count as an exact match."""
        library = self._make_library([("Thrift Shop (feat. Wanz)", "Macklemore & Ryan Lewis")])
        result = find_existing_in_library(
            "Thrift Shop", "Macklemore", library, exact_only=True
        )
        assert result is not None

    def test_fuzzy_near_miss_found_by_default(self):
        library = self._make_library([("Hello Wrld", "Artist C")])
        result = find_existing_in_library("Hello World", "Artist C", library)
        assert result is not None

    def test_fuzzy_near_miss_rejected_with_exact_only(self):
        """Regression (B8): typo-level matches must not qualify as exact."""
        library = self._make_library([("Hello Wrld", "Artist C")])
        result = find_existing_in_library("Hello World", "Artist C", library, exact_only=True)
        assert result is None

    def test_remix_never_matches_original(self):
        library = self._make_library([("Around the World (Remix)", "Artist D")])
        assert find_existing_in_library("Around the World", "Artist D", library) is None
        assert (
            find_existing_in_library("Around the World", "Artist D", library, exact_only=True)
            is None
        )


# ---------------------------------------------------------------------------
# Integration: scan_library + find_existing_in_library
# ---------------------------------------------------------------------------

class TestDuplicateDetectorIntegration:
    def test_full_flow_scan_then_find(self, tmp_path):
        mp3_path = str(tmp_path / "Queen - Bohemian Rhapsody.mp3")
        _write_tagged_mp3(mp3_path, "Bohemian Rhapsody", "Queen")

        library_files = scan_library(str(tmp_path))
        result = find_existing_in_library("Bohemian Rhapsody", "Queen", library_files)

        assert result is not None
        assert result.path == mp3_path

    def test_full_flow_not_found(self, tmp_path):
        mp3_path = str(tmp_path / "Eagles - Hotel California.mp3")
        _write_tagged_mp3(mp3_path, "Hotel California", "Eagles")

        library_files = scan_library(str(tmp_path))
        result = find_existing_in_library("Stairway to Heaven", "Led Zeppelin", library_files)

        assert result is None
