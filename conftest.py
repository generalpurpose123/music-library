"""
Root-level conftest.py — loaded first by pytest before any test module imports.

shazamio 0.4 was built against Python 3.11's typing_extensions; it fails to
import on Python 3.12 due to a TypeVar metaclass conflict.  Since every test
that exercises Shazam-related code already mocks `shazamio.Shazam` at the
call level, we pre-register a MagicMock stub in sys.modules here so that the
plain `from shazamio import Shazam` statements in app source files do not
crash at collection time.
"""
import sys
from unittest.mock import MagicMock

# Only stub when shazamio cannot be imported natively
try:
    import shazamio  # noqa: F401
except Exception:
    _shazamio_mock = MagicMock()
    sys.modules["shazamio"] = _shazamio_mock
