"""
Tests for parse_track_list.py — the Spotify-API-free import parsers.
Pure functions, no network or filesystem.
"""
import pytest

from app.controllers.playlist_aquisition.parse_track_list import (
    parse_track_csv,
    parse_track_list,
)
from app.models.exceptions import TrackListParseError


class TestParseTrackList:
    def test_basic_lines(self):
        text = "Madonna - La Isla Bonita\nKanye West - Can't Tell Me Nothing"
        assert parse_track_list(text) == [
            {"title": "La Isla Bonita", "artist": "Madonna"},
            {"title": "Can't Tell Me Nothing", "artist": "Kanye West"},
        ]

    def test_en_and_em_dash_separators(self):
        text = "Coldplay – Yellow\nPortishead — Glory Box"
        assert parse_track_list(text) == [
            {"title": "Yellow", "artist": "Coldplay"},
            {"title": "Glory Box", "artist": "Portishead"},
        ]

    def test_hyphenated_names_do_not_split(self):
        # "Jay-Z" has no whitespace around its hyphen; only " - " separates.
        result = parse_track_list("Jay-Z - 99 Problems")
        assert result == [{"title": "99 Problems", "artist": "Jay-Z"}]

    def test_title_containing_separator_splits_only_once(self):
        result = parse_track_list("Nirvana - Something - In The Way")
        assert result == [{"title": "Something - In The Way", "artist": "Nirvana"}]

    def test_blank_and_garbage_lines_skipped(self):
        text = "\n\nMadonna - La Isla Bonita\nnot a track line\n   \n"
        assert parse_track_list(text) == [
            {"title": "La Isla Bonita", "artist": "Madonna"},
        ]

    def test_non_latin_characters_preserved(self):
        text = "Πυξ Λαξ - Μοναξιά μου όλα\nКино - Группа крови"
        assert parse_track_list(text) == [
            {"title": "Μοναξιά μου όλα", "artist": "Πυξ Λαξ"},
            {"title": "Группа крови", "artist": "Кино"},
        ]

    def test_empty_input_raises(self):
        with pytest.raises(TrackListParseError):
            parse_track_list("")

    def test_only_garbage_raises(self):
        with pytest.raises(TrackListParseError):
            parse_track_list("no separators here\nnor here")


class TestParseTrackCsv:
    def test_exportify_style_headers(self):
        content = (
            "Track URI,Track Name,Artist URI(s),Artist Name(s),Album Name\n"
            "spotify:track:aaa,Yellow,spotify:artist:bbb,Coldplay,Parachutes\n"
            'spotify:track:ccc,"Song, with comma",spotify:artist:ddd,"Artist A, Artist B",Album\n'
        )
        assert parse_track_csv(content) == [
            {"title": "Yellow", "artist": "Coldplay"},
            {"title": "Song, with comma", "artist": "Artist A, Artist B"},
        ]

    def test_chosic_style_headers(self):
        content = "Song,Artist,Album,Year\nLa Isla Bonita,Madonna,True Blue,1986\n"
        assert parse_track_csv(content) == [
            {"title": "La Isla Bonita", "artist": "Madonna"},
        ]

    def test_semicolon_delimiter_sniffed(self):
        content = "Title;Artist\nYellow;Coldplay\n"
        assert parse_track_csv(content) == [{"title": "Yellow", "artist": "Coldplay"}]

    def test_rows_missing_fields_skipped(self):
        content = "Song,Artist\nYellow,Coldplay\n,MissingTitle\nMissingArtist,\n"
        assert parse_track_csv(content) == [{"title": "Yellow", "artist": "Coldplay"}]

    def test_missing_columns_raises(self):
        with pytest.raises(TrackListParseError, match="Could not find"):
            parse_track_csv("Foo,Bar\n1,2\n")

    def test_empty_file_raises(self):
        with pytest.raises(TrackListParseError):
            parse_track_csv("")

    def test_headers_only_raises(self):
        with pytest.raises(TrackListParseError, match="no rows"):
            parse_track_csv("Song,Artist\n")
