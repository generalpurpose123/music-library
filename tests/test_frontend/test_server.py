"""
Tests for the FastAPI frontend (frontend/server.py).

No network access; background work is intercepted at the executor boundary.
"""
import json
import queue

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.controllers.integration.job_state import Job, TrackJob
from frontend import server


class TestRecentJobs:
    def _save_job(self, root, job_id, created_at):
        Job(
            job_id=job_id,
            root_folder=root,
            organizing_schema=["artist"],
            wildcard_value=None,
            tracks=[TrackJob(title="T", artist="A", album=None)],
            created_at=created_at,
        ).save()

    def test_recent_jobs_sorted_by_created_at(self, tmp_path):
        """Regression (E): job files are UUID-named — recency must come from created_at."""
        root = str(tmp_path)
        # Lexical job_id order deliberately contradicts creation time.
        self._save_job(root, "aaa11111", created_at=3000.0)
        self._save_job(root, "mmm22222", created_at=1000.0)
        self._save_job(root, "zzz33333", created_at=2000.0)

        rows = server._recent_jobs(root)

        assert [r["job_id"] for r in rows] == ["aaa11111", "zzz33333", "mmm22222"]

    def test_limit_applies_after_sorting(self, tmp_path):
        root = str(tmp_path)
        self._save_job(root, "old00001", created_at=5.0)
        self._save_job(root, "mid00002", created_at=50.0)
        self._save_job(root, "new00003", created_at=500.0)

        rows = server._recent_jobs(root, limit=2)

        assert [r["job_id"] for r in rows] == ["new00003", "mid00002"]


class TestBackgroundScheduling:
    async def test_sync_start_submits_to_executor(self, monkeypatch, tmp_path):
        """Regression (B): jobs are scheduled via executor.submit, not event-loop tricks."""
        monkeypatch.setenv("MUSIC_LIBRARY_ROOT", str(tmp_path))
        executor = MagicMock()
        monkeypatch.setattr(server, "_executor", executor)

        response = await server.sync_start(
            playlist_json=json.dumps([{"title": "T", "artist": "A", "album": None}]),
            schema_json=json.dumps(["artist"]),
            wildcard="",
        )

        assert response.status_code == 303
        executor.submit.assert_called_once()
        assert executor.submit.call_args.args[0] is server._run_integration

    async def test_download_start_submits_to_executor(self, monkeypatch, tmp_path):
        executor = MagicMock()
        monkeypatch.setattr(server, "_executor", executor)

        response = await server.download_start(
            artist="A", song="S", output_folder=str(tmp_path)
        )

        assert response.status_code == 303
        executor.submit.assert_called_once()
        assert executor.submit.call_args.args[0] is server._run_single_download


class TestPageRendering:
    """Every page must render (regression: Starlette 1.0 TemplateResponse signature)."""

    def test_all_pages_render(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MUSIC_LIBRARY_ROOT", str(tmp_path))
        client = TestClient(server.app)
        for path in (
            "/",
            "/sync",
            "/browse",
            "/download",
            "/settings",
            "/jobs/someid00",
            "/download/progress/someid00",
        ):
            response = client.get(path)
            assert response.status_code == 200, f"{path} -> {response.status_code}"


class TestLogQueueCleanup:
    def test_log_queue_removed_after_download_stream_completes(self):
        """Regression (D): finished job queues must not accumulate forever."""
        job_id = "testjob1"
        log_q = queue.Queue()
        log_q.put("line one")
        log_q.put(None)  # completion sentinel
        server._log_queues[job_id] = log_q

        client = TestClient(server.app)
        with client.stream("GET", f"/download/progress/{job_id}/stream") as resp:
            body = "".join(resp.iter_text())

        assert "line one" in body
        assert job_id not in server._log_queues
