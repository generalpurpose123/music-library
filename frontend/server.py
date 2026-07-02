"""
music-library web frontend — FastAPI + HTMX
Run with: uvicorn frontend.server:app --reload
"""
import asyncio
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=_ENV_FILE)

app = FastAPI(title="Music Library")
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(_HERE / "templates"))

_executor = ThreadPoolExecutor(max_workers=4)

# In-process log queue keyed by job_id — populated by background threads
_log_queues: dict[str, queue.Queue] = {}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _library_root() -> str:
    return os.environ.get("MUSIC_LIBRARY_ROOT", "")


def _count_mp3s(root: str) -> int:
    if not root or not os.path.isdir(root):
        return 0
    count = 0
    for _, _, files in os.walk(root):
        count += sum(1 for f in files if f.lower().endswith(".mp3"))
    return count


def _recent_jobs(root: str, limit: int = 10) -> list[dict[str, Any]]:
    jobs_dir = os.path.join(root, ".music_library_jobs") if root else ""
    if not jobs_dir or not os.path.isdir(jobs_dir):
        return []
    from app.controllers.integration.job_state import Job
    entries: list[tuple[float, dict[str, Any]]] = []
    for fname in os.listdir(jobs_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(jobs_dir, fname)) as f:
                job = Job.from_json(f.read())
            total = len(job.tracks)
            done = sum(1 for t in job.tracks if t.status.value in ("done", "skipped"))
            failed = sum(1 for t in job.tracks if t.status.value == "failed")
            entries.append((job.created_at or 0.0, {
                "job_id": job.job_id,
                "schema": " / ".join(job.organizing_schema),
                "tracks": total,
                "done": done,
                "failed": failed,
                "completed": job.completed_at is not None,
                "created_at": time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(job.created_at)
                ),
            }))
        except Exception:
            continue
    # Job filenames are random UUIDs — sort by creation time, newest first.
    entries.sort(key=lambda e: e[0], reverse=True)
    return [row for _, row in entries[:limit]]


def _load_job(root_folder: str, job_id: str):
    from app.controllers.integration.job_state import Job
    job_file = os.path.join(root_folder, ".music_library_jobs", f"{job_id}.json")
    with open(job_file) as f:
        return Job.from_json(f.read())


# ---------------------------------------------------------------------------
# Background integration task
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            pass


def _run_integration(
    job_id: str,
    playlist: list[dict[str, Any]],
    root_folder: str,
    organizing_schema: list[str],
    wildcard_value: str | None,
    mode: str = "youtube",
) -> None:
    """Run in a thread pool thread. Writes job state to disk; SSE picks it up."""
    from app.controllers.integration.integrate_playlist_to_library import integrate_playlist
    from app.controllers.integration.job_state import new_job, TrackStatus

    log_q = _log_queues.setdefault(job_id, queue.Queue())

    root_logger = logging.getLogger()
    handler = _QueueHandler(log_q)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(handler)

    try:
        job = new_job(playlist, root_folder, organizing_schema, wildcard_value, mode=mode)
        # Override the generated job_id with the one we already handed to the client
        job.job_id = job_id
        job.save()

        integrate_playlist(
            playlist=playlist,
            root_folder=root_folder,
            organizing_schema=organizing_schema,
            wildcard_value=wildcard_value,
            mode=mode,
        )

        # Mark all pending/downloading tracks as done in the job file so SSE can close
        job = _load_job(root_folder, job_id)
        import time as _time
        job.completed_at = _time.time()
        for t in job.tracks:
            if t.status == TrackStatus.PENDING or t.status == TrackStatus.DOWNLOADING:
                t.status = TrackStatus.DONE
        job.save()

    except Exception as exc:
        log_q.put(f"ERROR: {exc}")
        try:
            job = _load_job(root_folder, job_id)
            import time as _time
            job.completed_at = _time.time()
            job.save()
        except Exception:
            pass
    finally:
        root_logger.removeHandler(handler)
        log_q.put(None)  # sentinel


def _run_single_download(
    job_id: str,
    artist: str,
    song: str,
    output_folder: str,
    mode: str = "youtube",
) -> None:
    """Run single song download in a thread. Streams logs via queue."""
    from app.controllers.song_aquisition.providers.registry import acquire_track

    log_q = _log_queues.setdefault(job_id, queue.Queue())
    root_logger = logging.getLogger()
    handler = _QueueHandler(log_q)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root_logger.addHandler(handler)

    try:
        os.makedirs(output_folder, exist_ok=True)
        result, source = acquire_track(
            artist, song, None, output_folder, mode=mode,
        )
        if result is None:
            if mode == "compliant":
                log_q.put(
                    "UNAVAILABLE: Not found on any compliant source. Try YouTube mode "
                    "or buy the track (Bandcamp / Qobuz / Apple / Amazon)."
                )
            else:
                log_q.put("ERROR: No matching track could be downloaded.")
        else:
            if result.tag_error:
                log_q.put(f"WARNING: ID3 tagging failed: {result.tag_error}")
            log_q.put(f"SUCCESS: Downloaded to {result.path} (source: {source})")
    except Exception as exc:
        log_q.put(f"ERROR: {exc}")
    finally:
        root_logger.removeHandler(handler)
        log_q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    root = _library_root()
    mp3_count = await asyncio.get_running_loop().run_in_executor(_executor, _count_mp3s, root)
    recent = await asyncio.get_running_loop().run_in_executor(_executor, _recent_jobs, root)
    return templates.TemplateResponse(request, "index.html", {
        "library_root": root,
        "mp3_count": mp3_count,
        "recent_jobs": recent,
    })


@app.get("/sync", response_class=HTMLResponse)
async def sync_page(request: Request):
    return templates.TemplateResponse(request, "sync.html")


@app.get("/browse", response_class=HTMLResponse)
async def browse_page(request: Request):
    root = _library_root()
    return templates.TemplateResponse(request, "browse.html", {"library_root": root})


@app.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    root = _library_root()
    return templates.TemplateResponse(request, "download.html", {"library_root": root})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    client_id_set = bool(os.environ.get("SPOTIFY_CLIENT_ID", "").strip())
    client_secret_set = bool(os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip())
    jamendo_client_id_set = bool(os.environ.get("JAMENDO_CLIENT_ID", "").strip())
    root = _library_root()
    return templates.TemplateResponse(request, "settings.html", {
        "client_id_set": client_id_set,
        "client_secret_set": client_secret_set,
        "jamendo_client_id_set": jamendo_client_id_set,
        "library_root": root,
    })


# ---------------------------------------------------------------------------
# Routes — HTMX fragments and actions
# ---------------------------------------------------------------------------

@app.post("/sync/fetch", response_class=HTMLResponse)
async def sync_fetch(
    request: Request,
    playlist_url: str = Form(...),
    schema: str = Form("artist/album"),
    wildcard: str = Form(""),
    mode: str = Form("compliant"),
):
    from app.controllers.playlist_aquisition.get_spotify_playlist import get_spotify_playlist

    mode = mode if mode in ("youtube", "compliant") else "compliant"

    try:
        tracks = await asyncio.get_running_loop().run_in_executor(
            _executor, get_spotify_playlist, playlist_url
        )
    except Exception as exc:
        return HTMLResponse(f'<div class="error">Failed to fetch playlist: {exc}</div>')

    if not tracks:
        return HTMLResponse('<div class="warning">No tracks found in this playlist.</div>')

    schema_list = [s.strip() for s in schema.split("/") if s.strip()]
    rows_html = "\n".join(
        f"<tr><td>{i+1}</td><td>{t.get('title','')}</td><td>{t.get('artist','')}</td>"
        f"<td>{t.get('album') or ''}</td></tr>"
        for i, t in enumerate(tracks)
    )

    tracks_json = json.dumps(tracks)
    schema_json = json.dumps(schema_list)
    wildcard_safe = wildcard.replace('"', "&quot;")
    mode_label = "Compliant (Jamendo / Internet Archive + buy-list)" if mode == "compliant" else "YouTube"

    notice = ""
    if mode == "compliant" and not os.environ.get("JAMENDO_CLIENT_ID", "").strip():
        notice = (
            '<p class="notice">No Jamendo API key set — compliant mode will only use '
            'Internet Archive and the purchase list. Add a key on the Settings page to '
            'enable Jamendo downloads.</p>'
        )

    return HTMLResponse(f"""
<div id="fetch-result">
  <p class="success">{len(tracks)} tracks found. Acquisition mode: <strong>{mode_label}</strong>.</p>
  {notice}
  <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>Title</th><th>Artist</th><th>Album</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <form method="post" action="/sync/start" class="start-form">
    <input type="hidden" name="playlist_json" value="{tracks_json.replace('"', '&quot;')}">
    <input type="hidden" name="schema_json" value="{schema_json.replace('"', '&quot;')}">
    <input type="hidden" name="wildcard" value="{wildcard_safe}">
    <input type="hidden" name="mode" value="{mode}">
    <button type="submit" class="btn-primary">Start Sync ({len(tracks)} tracks)</button>
  </form>
</div>
""")


@app.post("/sync/start")
async def sync_start(
    playlist_json: str = Form(...),
    schema_json: str = Form(...),
    wildcard: str = Form(""),
    mode: str = Form("compliant"),
):
    import uuid
    root = _library_root()
    if not root:
        return HTMLResponse('<div class="error">Music library root is not set. Go to Settings.</div>', status_code=400)

    playlist = json.loads(playlist_json)
    schema = json.loads(schema_json)
    mode = mode if mode in ("youtube", "compliant") else "compliant"
    job_id = str(uuid.uuid4())[:8]

    _executor.submit(_run_integration, job_id, playlist, root, schema, wildcard or None, mode)

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    root = _library_root()
    return templates.TemplateResponse(request, "job.html", {
        "job_id": job_id,
        "root_folder": root,
    })


@app.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    root = _library_root()

    async def event_gen():
        last_log_count = 0
        while True:
            # Stream log lines first (from in-memory queue)
            log_q = _log_queues.get(job_id)
            new_lines = []
            if log_q:
                while True:
                    try:
                        msg = log_q.get_nowait()
                        if msg is None:
                            break
                        new_lines.append(msg)
                    except queue.Empty:
                        break

            # Read job file if it exists
            job_data = None
            try:
                job = _load_job(root, job_id)
                job_data = {
                    "tracks": [asdict(t) for t in job.tracks],
                    "done": job.completed_at is not None,
                }
                # Convert enums to strings
                for t in job_data["tracks"]:
                    t["status"] = t["status"] if isinstance(t["status"], str) else t["status"].value
            except FileNotFoundError:
                job_data = {"tracks": [], "done": False}
            except Exception as exc:
                job_data = {"tracks": [], "done": False, "error": str(exc)}

            payload = {
                "log_lines": new_lines,
                "job": job_data,
            }
            yield {"data": json.dumps(payload)}

            if job_data.get("done"):
                # Job finished and this stream delivered it — release the queue.
                _log_queues.pop(job_id, None)
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_gen())


@app.post("/browse/scan", response_class=HTMLResponse)
async def browse_scan(folder: str = Form(...)):
    if not folder.strip():
        return HTMLResponse('<div class="error">Please enter a folder path.</div>')
    if not os.path.isdir(folder):
        return HTMLResponse(f'<div class="error">Directory not found: {folder}</div>')

    def _scan(path: str):
        from mutagen.id3 import ID3, ID3NoHeaderError
        rows = []
        for dirpath, _, filenames in os.walk(path):
            for fname in sorted(filenames):
                if not fname.lower().endswith(".mp3"):
                    continue
                full = os.path.join(dirpath, fname)
                title = artist = album = ""
                try:
                    tags = ID3(full)
                    title = str(tags.get("TIT2", ""))
                    artist = str(tags.get("TPE1", ""))
                    album = str(tags.get("TALB", ""))
                except (ID3NoHeaderError, Exception):
                    pass
                rows.append((os.path.relpath(full, path), title, artist, album))
        return rows

    rows = await asyncio.get_running_loop().run_in_executor(_executor, _scan, folder)

    if not rows:
        return HTMLResponse('<div class="warning">No MP3 files found in this folder.</div>')

    display = rows[:500]
    more = len(rows) - len(display)
    rows_html = "\n".join(
        f"<tr><td class='mono'>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td></tr>"
        for r in display
    )
    note = f'<p class="muted">Showing {len(display)} of {len(rows)} files.</p>' if more > 0 else f'<p class="muted">{len(rows)} files.</p>'

    return HTMLResponse(f"""
<div id="scan-result">
  {note}
  <div class="form-group" style="max-width:400px;margin-bottom:0.75rem">
    <input type="text" id="browse-filter" placeholder="Filter by path, title, artist&#x2026;"
           class="input-wide" oninput="filterBrowseTable(this.value)">
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Path</th><th>Title</th><th>Artist</th><th>Album</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <script>
function filterBrowseTable(q) {{
  var lower = q.toLowerCase();
  document.querySelectorAll('#scan-result tbody tr').forEach(function(row) {{
    var text = row.textContent.toLowerCase();
    row.style.display = text.includes(lower) ? '' : 'none';
  }});
}}
  </script>
</div>
""")


@app.post("/download/start")
async def download_start(
    artist: str = Form(...),
    song: str = Form(...),
    output_folder: str = Form(...),
    mode: str = Form("compliant"),
):
    import uuid
    mode = mode if mode in ("youtube", "compliant") else "compliant"
    job_id = str(uuid.uuid4())[:8]

    _executor.submit(_run_single_download, job_id, artist, song, output_folder, mode)

    return RedirectResponse(url=f"/download/progress/{job_id}", status_code=303)


@app.get("/download/progress/{job_id}", response_class=HTMLResponse)
async def download_progress_page(request: Request, job_id: str):
    return templates.TemplateResponse(request, "download_progress.html", {
        "job_id": job_id,
    })


@app.get("/download/progress/{job_id}/stream")
async def stream_download(job_id: str):
    async def event_gen():
        seen = 0
        accumulated: list[str] = []
        done = False
        while not done:
            log_q = _log_queues.get(job_id)
            if log_q:
                while True:
                    try:
                        msg = log_q.get_nowait()
                        if msg is None:
                            done = True
                            break
                        accumulated.append(msg)
                    except queue.Empty:
                        break

            new_lines = accumulated[seen:]
            seen = len(accumulated)
            if new_lines or done:
                yield {"data": json.dumps({"lines": new_lines, "done": done})}
            if done:
                _log_queues.pop(job_id, None)
            else:
                await asyncio.sleep(0.5)

    return EventSourceResponse(event_gen())


@app.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    spotify_client_id: str = Form(""),
    spotify_client_secret: str = Form(""),
    jamendo_client_id: str = Form(""),
    library_root: str = Form(""),
):
    env_path = str(_ENV_FILE)
    # Ensure file exists
    _ENV_FILE.touch(exist_ok=True)

    if spotify_client_id.strip():
        set_key(env_path, "SPOTIFY_CLIENT_ID", spotify_client_id.strip())
        os.environ["SPOTIFY_CLIENT_ID"] = spotify_client_id.strip()

    if spotify_client_secret.strip():
        set_key(env_path, "SPOTIFY_CLIENT_SECRET", spotify_client_secret.strip())
        os.environ["SPOTIFY_CLIENT_SECRET"] = spotify_client_secret.strip()

    if jamendo_client_id.strip():
        set_key(env_path, "JAMENDO_CLIENT_ID", jamendo_client_id.strip())
        os.environ["JAMENDO_CLIENT_ID"] = jamendo_client_id.strip()

    if library_root.strip():
        set_key(env_path, "MUSIC_LIBRARY_ROOT", library_root.strip())
        os.environ["MUSIC_LIBRARY_ROOT"] = library_root.strip()

    client_id_set = bool(os.environ.get("SPOTIFY_CLIENT_ID", "").strip())
    client_secret_set = bool(os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip())
    jamendo_client_id_set = bool(os.environ.get("JAMENDO_CLIENT_ID", "").strip())
    root = _library_root()

    return templates.TemplateResponse(request, "settings.html", {
        "client_id_set": client_id_set,
        "client_secret_set": client_secret_set,
        "jamendo_client_id_set": jamendo_client_id_set,
        "library_root": root,
        "saved": True,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def serve() -> None:
    import uvicorn
    uvicorn.run("frontend.server:app", host="127.0.0.1", port=8000, reload=False)
