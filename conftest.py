"""
Root-level conftest.py — keeps the project root on sys.path so `import app`
and `import frontend` resolve regardless of pytest's import mode.

(A shazamio import stub used to live here for shazamio 0.4 on Python 3.12;
it has been removed — shazamio >= 0.7 imports cleanly.)
"""
