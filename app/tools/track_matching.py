"""
Normalization and matching helpers for comparing track/artist names across
providers (Spotify, Shazam, ID3 tags).

Decoration suffixes such as "(feat. X)" or "- Remastered 2020" are stripped
before comparison, but meaningful variant markers ("Remix", "Live",
"Acoustic") are preserved so a remix never matches the original recording.
"""
import re
from difflib import SequenceMatcher

# Parenthesized chunks and " - " suffixes are stripped only when they start
# with one of these decoration keywords; anything else is part of the title.
_DECORATION_KEYWORDS = (
    r"feat\.?|ft\.?|featuring|with"
    r"|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?"
    r"|radio edit|single version|album version|original version"
    r"|mono|stereo|explicit|clean|bonus track|deluxe(?:\s+edition)?"
)

_PAREN_DECORATION = re.compile(
    rf"[(\[]\s*(?:{_DECORATION_KEYWORDS})[^)\]]*[)\]]", re.IGNORECASE
)
_DASH_DECORATION = re.compile(
    rf"\s[-–—]\s(?:{_DECORATION_KEYWORDS}).*$", re.IGNORECASE
)
_TRAILING_FEAT = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.+$", re.IGNORECASE)

# Markers that denote a genuinely different recording. Two titles only match
# when they carry the same marker set — plain fuzzy ratio would happily match
# "Song (Remix)" to "Song" on longer titles.
_VARIANT_MARKERS = re.compile(
    r"\b(remix|remixed|live|acoustic|unplugged|instrumental|karaoke|cover|demo"
    r"|edit|version|sped up|slowed|reprise|medley|mashup)\b",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

# Separators between individual artists in a multi-artist credit string.
_ARTIST_SEPARATORS = re.compile(
    r"\s*(?:,|;|/|\+|&|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\bwith\b|\band\b|\bx\b|\bvs\.?\b)\s*",
    re.IGNORECASE,
)


def normalize_for_match(name: str) -> str:
    """Casefold and strip decoration so provider variants of one name compare equal."""
    if not name:
        return ""
    result = name.casefold()
    result = _PAREN_DECORATION.sub(" ", result)
    result = _DASH_DECORATION.sub(" ", result)
    result = _TRAILING_FEAT.sub(" ", result)
    result = _PUNCTUATION.sub("", result)
    result = _WHITESPACE.sub(" ", result).strip()
    if not result:
        # The whole name was decoration-shaped (e.g. "(Interlude)") — keep it.
        result = _WHITESPACE.sub(" ", _PUNCTUATION.sub("", name.casefold())).strip()
    return result


def similarity(a: str, b: str) -> float:
    """Fuzzy ratio between two names after normalization."""
    return SequenceMatcher(None, normalize_for_match(a), normalize_for_match(b)).ratio()


def artist_tokens(credit: str) -> set[str]:
    """Split a multi-artist credit string into a set of normalized artist names."""
    if not credit:
        return set()
    parts = _ARTIST_SEPARATORS.split(credit)
    return {normalize_for_match(p) for p in parts if normalize_for_match(p)}


def artists_match(wanted: str, got: str, threshold: float = 0.75) -> bool:
    """
    True when two artist credits plausibly describe the same act: either the
    full strings are similar, or one credit's artists are a subset of the
    other's (handles "Macklemore" vs "Macklemore & Ryan Lewis Feat. Wanz").
    """
    if similarity(wanted, got) >= threshold:
        return True
    wanted_set = artist_tokens(wanted)
    got_set = artist_tokens(got)
    if not wanted_set or not got_set:
        return False
    return wanted_set <= got_set or got_set <= wanted_set


def _variant_markers(name: str) -> set[str]:
    return {m.casefold() for m in _VARIANT_MARKERS.findall(normalize_for_match(name))}


def titles_match(wanted: str, got: str, threshold: float = 0.75) -> bool:
    """
    True when two track titles are the same modulo decoration suffixes.
    Titles with different variant markers (remix, live, ...) never match.
    """
    if _variant_markers(wanted) != _variant_markers(got):
        return False
    return similarity(wanted, got) >= threshold
