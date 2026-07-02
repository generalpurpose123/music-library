"""Tests for purchase-list generation (Phase D)."""
import csv
import os

from app.controllers.integration.job_state import Job, TrackJob, TrackStatus, new_job
from app.controllers.integration.purchase_links import (
    build_purchase_links,
    write_purchase_manifest,
)


class TestBuildPurchaseLinks:
    def test_all_stores_present(self):
        links = build_purchase_links("Coldplay", "Viva La Vida")
        assert set(links) == {"bandcamp", "qobuz", "apple_music", "amazon_music"}

    def test_query_is_url_encoded(self):
        links = build_purchase_links("AC/DC", "Back In Black")
        # spaces and slashes are encoded, never raw in the query
        assert " " not in links["bandcamp"]
        assert "AC%2FDC" in links["bandcamp"]


class TestWriteManifest:
    def _job_with(self, tmp_path, statuses):
        playlist = [{"title": f"S{i}", "artist": f"A{i}", "album": None} for i in range(len(statuses))]
        job = new_job(playlist, str(tmp_path), ["artist"], None, mode="compliant")
        for t, s in zip(job.tracks, statuses):
            t.status = s
            if s == TrackStatus.UNAVAILABLE:
                t.purchase_links = build_purchase_links(t.artist, t.title)
        return job

    def test_no_manifest_when_no_unavailable(self, tmp_path):
        job = self._job_with(tmp_path, [TrackStatus.DONE, TrackStatus.SKIPPED])
        assert write_purchase_manifest(job) is None

    def test_writes_csv_and_html(self, tmp_path):
        job = self._job_with(tmp_path, [TrackStatus.DONE, TrackStatus.UNAVAILABLE])
        html_path = write_purchase_manifest(job)

        assert html_path and os.path.isfile(html_path)
        csv_path = html_path[:-5] + ".csv"
        assert os.path.isfile(csv_path)

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # header + exactly the one unavailable track
        assert rows[0][:3] == ["artist", "title", "album"]
        assert len(rows) == 2
        assert rows[1][0] == "A1" and rows[1][1] == "S1"
        assert "bandcamp.com" in "".join(rows[1])

    def test_html_contains_buy_links(self, tmp_path):
        job = self._job_with(tmp_path, [TrackStatus.UNAVAILABLE])
        html_path = write_purchase_manifest(job)
        with open(html_path, encoding="utf-8") as f:
            doc = f.read()
        assert "Bandcamp" in doc and "qobuz.com" in doc
