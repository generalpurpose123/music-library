"""
Persistent job state for playlist integration runs.

A job file is written to <root_folder>/.music_library_jobs/<job_id>.json
and updated after every track completes. On re-run, completed tracks are
skipped and failed/pending tracks are retried.
"""
import json
import os
import time
import uuid
import fcntl
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TrackStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"  # Already existed in library


@dataclass
class TrackJob:
    title: str
    artist: str
    album: str | None
    status: TrackStatus = TrackStatus.PENDING
    target_path: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class Job:
    job_id: str
    root_folder: str
    organizing_schema: list[str]
    wildcard_value: str | None
    tracks: list[TrackJob]
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "Job":
        d = json.loads(data)
        d["tracks"] = [TrackJob(**{**t, "status": TrackStatus(t["status"])}) for t in d["tracks"]]
        return cls(**d)

    @property
    def jobs_dir(self) -> str:
        return os.path.join(self.root_folder, ".music_library_jobs")

    @property
    def job_file(self) -> str:
        return os.path.join(self.jobs_dir, f"{self.job_id}.json")

    def save(self) -> None:
        os.makedirs(self.jobs_dir, exist_ok=True)
        # Atomic write: write to temp file then rename
        fd, tmp = tempfile.mkstemp(dir=self.jobs_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self.to_json())
            os.replace(tmp, self.job_file)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class LibraryLock:
    """Exclusive lock on a root_folder to prevent concurrent integration runs."""

    def __init__(self, root_folder: str):
        self._lock_path = os.path.join(root_folder, ".music_library_jobs", ".lock")
        self._fd: int | None = None

    def __enter__(self) -> "LibraryLock":
        os.makedirs(os.path.dirname(self._lock_path), exist_ok=True)
        self._fd = open(self._lock_path, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fd.close()
            raise RuntimeError(
                f"Another music-library process is already running on {os.path.dirname(self._lock_path)!r}. "
                "Wait for it to finish or remove the lock file manually."
            )
        return self

    def __exit__(self, *_: Any) -> None:
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()


def new_job(
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None,
) -> Job:
    tracks = [
        TrackJob(
            title=t.get("title", ""),
            artist=t.get("artist", ""),
            album=t.get("album"),
        )
        for t in playlist
    ]
    job = Job(
        job_id=str(uuid.uuid4())[:8],
        root_folder=root_folder,
        organizing_schema=organizing_schema,
        wildcard_value=wildcard_value,
        tracks=tracks,
    )
    return job


def find_resumable_job(
    root_folder: str,
    playlist: list[dict[str, Any]],
    organizing_schema: list[str],
) -> Job | None:
    """
    Find an unfinished job for the same playlist in root_folder.
    Matches by track list (title+artist) and organizing_schema.
    Returns the most recent match, or None.
    """
    jobs_dir = os.path.join(root_folder, ".music_library_jobs")
    if not os.path.isdir(jobs_dir):
        return None

    playlist_keys = {(t.get("title", ""), t.get("artist", "")) for t in playlist}
    candidates = []
    for fname in os.listdir(jobs_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(jobs_dir, fname)) as f:
                job = Job.from_json(f.read())
        except Exception:
            continue
        if job.completed_at is not None:
            continue  # Already finished
        if job.organizing_schema != organizing_schema:
            continue
        job_keys = {(t.title, t.artist) for t in job.tracks}
        if job_keys == playlist_keys:
            candidates.append(job)

    if not candidates:
        return None
    return max(candidates, key=lambda j: j.created_at)


def cleanup_orphaned_temp_dirs(root_folder: str, max_age_hours: float = 24.0) -> None:
    """
    Remove download_tmp_* directories left by crashed previous runs.

    Only directories older than max_age_hours are removed: the temp dir is
    shared machine-wide, so a fresh download_tmp_* may belong to another
    job that is still running (the library lock only serializes one root).
    """
    parent = tempfile.gettempdir()
    cutoff = time.time() - max_age_hours * 3600
    for name in os.listdir(parent):
        if name.startswith("download_tmp_"):
            full = os.path.join(parent, name)
            try:
                if os.path.isdir(full) and os.stat(full).st_mtime < cutoff:
                    shutil.rmtree(full, ignore_errors=True)
            except OSError:
                continue
