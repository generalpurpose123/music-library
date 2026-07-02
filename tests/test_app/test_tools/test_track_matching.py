"""
Tests for app.tools.track_matching — normalization and fuzzy matching used by
download verification (get_check_enhance_song) and the duplicate detector.
"""
from app.tools.track_matching import (
    artist_tokens,
    artists_match,
    normalize_for_match,
    similarity,
    titles_match,
)


class TestNormalizeForMatch:
    def test_remaster_dash_suffix_stripped(self):
        assert normalize_for_match("Song - Remastered 2020") == normalize_for_match("Song")

    def test_year_first_remaster_suffix_stripped(self):
        assert normalize_for_match("Song - 2011 Remaster") == normalize_for_match("Song")

    def test_feat_parenthetical_stripped(self):
        assert normalize_for_match("Song (feat. Wanz)") == normalize_for_match("Song")

    def test_trailing_feat_without_parens_stripped(self):
        assert normalize_for_match("Drake feat. Future") == normalize_for_match("Drake")

    def test_punctuation_ignored(self):
        assert normalize_for_match("Don't Stop") == normalize_for_match("Dont Stop")

    def test_casefolded(self):
        assert normalize_for_match("HELLO") == normalize_for_match("hello")

    def test_remix_marker_preserved(self):
        assert normalize_for_match("Song (Remix)") != normalize_for_match("Song")

    def test_live_marker_preserved(self):
        assert normalize_for_match("Song (Live)") != normalize_for_match("Song")

    def test_pure_decoration_title_does_not_normalize_to_empty(self):
        assert normalize_for_match("(Interlude)") != ""

    def test_empty_string(self):
        assert normalize_for_match("") == ""


class TestArtistTokens:
    def test_comma_and_ampersand_split(self):
        assert artist_tokens("A, B & C") == {"a", "b", "c"}

    def test_feat_split(self):
        assert artist_tokens("Macklemore & Ryan Lewis Feat. Wanz") == {
            "macklemore",
            "ryan lewis",
            "wanz",
        }

    def test_single_artist(self):
        assert artist_tokens("Queen") == {"queen"}


class TestArtistsMatch:
    def test_exact(self):
        assert artists_match("Queen", "Queen")

    def test_first_artist_subset_of_full_credit(self):
        assert artists_match("Macklemore", "Macklemore & Ryan Lewis Feat. Wanz")

    def test_full_credit_superset_of_first_artist(self):
        assert artists_match("Macklemore & Ryan Lewis Feat. Wanz", "Macklemore")

    def test_unrelated_artists_do_not_match(self):
        assert not artists_match("Queen", "Metallica")

    def test_minor_spelling_variation_matches(self):
        assert artists_match("Beyonce", "Beyoncé")


class TestTitlesMatch:
    def test_remaster_variant_matches(self):
        assert titles_match("Blinding Lights - Remastered 2020", "Blinding Lights")

    def test_feat_variant_matches(self):
        assert titles_match("Thrift Shop (feat. Wanz)", "Thrift Shop")

    def test_different_song_rejected(self):
        assert not titles_match("Bohemian Rhapsody", "Another One Bites the Dust")

    def test_remix_does_not_match_original(self):
        assert not titles_match("Around the World (Remix)", "Around the World")


class TestSimilarity:
    def test_identical_after_normalization_is_one(self):
        assert similarity("Song - Remastered", "song") == 1.0

    def test_disjoint_strings_low(self):
        assert similarity("abcdef", "uvwxyz") < 0.3
