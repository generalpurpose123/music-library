"""
Tests for job_state.py

Covers:
  - new_job: creates Job with correct track list and PENDING statuses
  - Job.save / Job.from_json: roundtrip serialization
  - find_resumable_job: matching unfinished job, completed jobs ignored,
    wrong schema ignored, most recent returned
  - LibraryLock: acquires/releases cleanly, concurrent lock raises RuntimeError
  - cleanup_orphaned_temp_dirs: removes download_tmp_ dirs, leaves others alone
  - Track status transitions: PENDING -> DOWNLOADING -> DONE, FAILED with error message
"""
import fcntl
import json
import os
import tempfile
import time
import uuid

import pytest

from app.controllers.integration.job_state import (
    Job,
    TrackJob,
    TrackStatus,
    LibraryLock,
    new_job,
    find_resumable_job,
    cleanup_orphaned_temp_dirs,
)


# ---------------------------------------------------------------------------
# new_job
# ---------------------------------------------------------------------------

class TestNewJob:
    def test_creates_job_with_all_tracks_pending(self):
        playlist = [
            {"title": "Song A", "artist": "Artist A", "album": "Album A"},
            {"title": "Song B", "artist": "Artist B", "album": None},
        ]
        job = new_job(playlist, "/some/root", ["artist", "album"], None)

        assert len(job.tracks) == 2
        for track in job.tracks:
            assert track.status == TrackStatus.PENDING

    def test_track_fields_set_correctly(self):
        playlist = [{"title": "My Song", "artist": "My Artist", "album": "My Album"}]
        job = new_job(playlist, "/root", ["artist"], None)

        assert job.tracks[0].title == "My Song"
        assert job.tracks[0].artist == "My Artist"
        assert job.tracks[0].album == "My Album"

    def test_job_id_is_string(self):
        job = new_job([], "/root", ["artist"], None)
        assert isinstance(job.job_id, str)

    def test_root_folder_and_schema_stored(self):
        job = new_job([], "/my/library", ["artist", "album"], "Pop")
        assert job.root_folder == "/my/library"
        assert job.organizing_schema == ["artist", "album"]
        assert job.wildcard_value == "Pop"

    def test_empty_playlist_creates_job_with_no_tracks(self):
        job = new_job([], "/root", ["artist"], None)
        assert job.tracks == []

    def test_track_missing_album_defaults_to_none(self):
        playlist = [{"title": "Song", "artist": "Artist"}]
        job = new_job(playlist, "/root", ["artist"], None)
        assert job.tracks[0].album is None


# ---------------------------------------------------------------------------
# Job serialization roundtrip
# ---------------------------------------------------------------------------

class TestJobSerialization:
    def _make_job(self, root_folder):
        playlist = [
            {"title": "Song A", "artist": "Artist A", "album": "Album A"},
        ]
        return new_job(playlist, root_folder, ["artist", "album"], None)

    def test_save_creates_json_file(self, tmp_path):
        job = self._make_job(str(tmp_path))
        job.save()
        assert os.path.isfile(job.job_file)

    def test_from_json_roundtrip(self, tmp_path):
        job = self._make_job(str(tmp_path))
        job.tracks[0].status = TrackStatus.DONE

        serialized = job.to_json()
        restored = Job.from_json(serialized)

        assert restored.job_id == job.job_id
        assert restored.root_folder == job.root_folder
        assert restored.organizing_schema == job.organizing_schema
        assert len(restored.tracks) == 1
        assert restored.tracks[0].title == "Song A"
        assert restored.tracks[0].status == TrackStatus.DONE

    def test_save_and_reload_from_file(self, tmp_path):
        job = self._make_job(str(tmp_path))
        job.save()

        with open(job.job_file) as f:
            restored = Job.from_json(f.read())

        assert restored.job_id == job.job_id

    def test_all_track_statuses_serialize_correctly(self, tmp_path):
        job = self._make_job(str(tmp_path))
        for status in TrackStatus:
            job.tracks[0].status = status
            data = job.to_json()
            restored = Job.from_json(data)
            assert restored.tracks[0].status == status

    def test_save_is_atomic_temp_file_cleaned_up(self, tmp_path):
        job = self._make_job(str(tmp_path))
        job.save()
        # No .tmp files should remain
        tmp_files = [f for f in os.listdir(job.jobs_dir) if f.endswith(".tmp")]
        assert tmp_files == []


# ---------------------------------------------------------------------------
# find_resumable_job
# ---------------------------------------------------------------------------

class TestFindResumableJob:
    def _save_job(self, tmp_path, playlist, schema, completed=False, created_at=None):
        job = new_job(playlist, str(tmp_path), schema, None)
        if created_at is not None:
            job.created_at = created_at
        if completed:
            job.completed_at = time.time()
        job.save()
        return job

    def test_finds_matching_unfinished_job(self, tmp_path):
        playlist = [{"title": "Song", "artist": "Artist"}]
        schema = ["artist"]
        self._save_job(tmp_path, playlist, schema, completed=False)

        result = find_resumable_job(str(tmp_path), playlist, schema)

        assert result is not None
        assert result.tracks[0].title == "Song"

    def test_ignores_completed_jobs(self, tmp_path):
        playlist = [{"title": "Song", "artist": "Artist"}]
        schema = ["artist"]
        self._save_job(tmp_path, playlist, schema, completed=True)

        result = find_resumable_job(str(tmp_path), playlist, schema)

        assert result is None

    def test_ignores_different_schema(self, tmp_path):
        playlist = [{"title": "Song", "artist": "Artist"}]
        self._save_job(tmp_path, playlist, ["artist", "album"], completed=False)

        result = find_resumable_job(str(tmp_path), playlist, ["artist"])

        assert result is None

    def test_returns_none_when_no_jobs_dir(self, tmp_path):
        playlist = [{"title": "Song", "artist": "Artist"}]
        result = find_resumable_job(str(tmp_path), playlist, ["artist"])
        assert result is None

    def test_returns_most_recent_when_multiple(self, tmp_path):
        playlist = [{"title": "Song", "artist": "Artist"}]
        schema = ["artist"]
        old_job = self._save_job(tmp_path, playlist, schema, created_at=1000.0)
        new_job_obj = self._save_job(tmp_path, playlist, schema, created_at=2000.0)

        result = find_resumable_job(str(tmp_path), playlist, schema)

        assert result is not None
        assert result.job_id == new_job_obj.job_id

    def test_ignores_different_playlist(self, tmp_path):
        playlist_a = [{"title": "Song A", "artist": "Artist A"}]
        playlist_b = [{"title": "Song B", "artist": "Artist B"}]
        schema = ["artist"]
        self._save_job(tmp_path, playlist_a, schema, completed=False)

        result = find_resumable_job(str(tmp_path), playlist_b, schema)

        assert result is None

    def test_ignores_corrupted_json_files(self, tmp_path):
        jobs_dir = tmp_path / ".music_library_jobs"
        jobs_dir.mkdir()
        bad_file = jobs_dir / "corrupt.json"
        bad_file.write_text("not valid json {{{")

        playlist = [{"title": "Song", "artist": "Artist"}]
        result = find_resumable_job(str(tmp_path), playlist, ["artist"])
        assert result is None


# ---------------------------------------------------------------------------
# LibraryLock
# ---------------------------------------------------------------------------

class TestLibraryLock:
    def test_acquires_and_releases_cleanly(self, tmp_path):
        with LibraryLock(str(tmp_path)) as lock:
            assert lock is not None
        # After context exit the lock file exists but the lock is released

    def test_lock_file_created(self, tmp_path):
        with LibraryLock(str(tmp_path)):
            lock_path = tmp_path / ".music_library_jobs" / ".lock"
            assert lock_path.exists()

    def test_second_lock_on_same_folder_raises_runtime_error(self, tmp_path):
        """Two LibraryLock objects on the same folder: the second should fail."""
        lock1 = LibraryLock(str(tmp_path))
        lock1.__enter__()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                lock2 = LibraryLock(str(tmp_path))
                lock2.__enter__()
        finally:
            lock1.__exit__(None, None, None)

    def test_lock_released_allows_reacquisition(self, tmp_path):
        with LibraryLock(str(tmp_path)):
            pass
        # Should not raise
        with LibraryLock(str(tmp_path)):
            pass


# ---------------------------------------------------------------------------
# cleanup_orphaned_temp_dirs
# ---------------------------------------------------------------------------

class TestCleanupOrphanedTempDirs:
    def test_removes_download_tmp_directories(self, tmp_path):
        # Create fake download_tmp_ dirs in the system temp dir
        tmp_dir = tempfile.gettempdir()
        orphan1 = tempfile.mkdtemp(prefix="download_tmp_", dir=tmp_dir)
        orphan2 = tempfile.mkdtemp(prefix="download_tmp_", dir=tmp_dir)
        # Put a file in one
        open(os.path.join(orphan1, "partial.mp3"), "w").close()

        cleanup_orphaned_temp_dirs(str(tmp_path))

        assert not os.path.isdir(orphan1)
        assert not os.path.isdir(orphan2)

    def test_leaves_other_temp_dirs_alone(self, tmp_path):
        tmp_dir = tempfile.gettempdir()
        safe_dir = tempfile.mkdtemp(prefix="music_library_safe_", dir=tmp_dir)
        try:
            cleanup_orphaned_temp_dirs(str(tmp_path))
            assert os.path.isdir(safe_dir)
        finally:
            if os.path.isdir(safe_dir):
                import shutil
                shutil.rmtree(safe_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Track status transitions
# ---------------------------------------------------------------------------

class TestTrackStatusTransitions:
    def test_pending_to_downloading_to_done(self):
        track = TrackJob(title="Song", artist="Artist", album=None)
        assert track.status == TrackStatus.PENDING

        track.status = TrackStatus.DOWNLOADING
        track.started_at = time.time()
        assert track.status == TrackStatus.DOWNLOADING

        track.status = TrackStatus.DONE
        track.completed_at = time.time()
        assert track.status == TrackStatus.DONE
        assert track.completed_at is not None

    def test_failed_status_records_error_message(self):
        track = TrackJob(title="Song", artist="Artist", album=None)
        track.status = TrackStatus.FAILED
        track.error = "Shazam recognition failed after 3 attempts"
        assert track.status == TrackStatus.FAILED
        assert "Shazam" in track.error

    def test_skipped_status(self):
        track = TrackJob(title="Song", artist="Artist", album=None)
        track.status = TrackStatus.SKIPPED
        assert track.status == TrackStatus.SKIPPED

    def test_status_serializes_as_string(self, tmp_path):
        job = new_job([{"title": "Song", "artist": "Artist"}], str(tmp_path), ["artist"], None)
        job.tracks[0].status = TrackStatus.FAILED
        job.tracks[0].error = "Download failed"

        data = json.loads(job.to_json())
        assert data["tracks"][0]["status"] == "failed"
        assert data["tracks"][0]["error"] == "Download failed"
