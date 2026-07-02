"""
Purchase-list support for compliant mode.

When a track is not available on any free/CC source, it is recorded as
UNAVAILABLE with deep search links to legitimate stores where the owner can buy
it, and the job's unavailable tracks are exported as a CSV + HTML manifest.
"""
import csv
import html
import os
from urllib.parse import quote_plus

# store key -> (label, search-URL template with a {q} placeholder)
_STORES = {
    "bandcamp": ("Bandcamp", "https://bandcamp.com/search?q={q}"),
    "qobuz": ("Qobuz", "https://www.qobuz.com/search?q={q}"),
    "apple_music": ("Apple Music", "https://music.apple.com/us/search?term={q}"),
    "amazon_music": ("Amazon Music", "https://www.amazon.com/s?k={q}&i=digital-music"),
}


def build_purchase_links(artist: str, title: str) -> dict[str, str]:
    """Return {store_key: search_url} deep links for buying the given track."""
    q = quote_plus(f"{artist} {title}".strip())
    return {key: tmpl.format(q=q) for key, (_label, tmpl) in _STORES.items()}


def store_label(key: str) -> str:
    return _STORES.get(key, (key, ""))[0]


def write_purchase_manifest(job) -> str | None:
    """
    Write CSV + HTML manifests of the job's UNAVAILABLE tracks under the job dir.
    Returns the HTML manifest path, or None if there are no unavailable tracks.
    """
    from app.controllers.integration.job_state import TrackStatus

    unavailable = [t for t in job.tracks if t.status == TrackStatus.UNAVAILABLE]
    if not unavailable:
        return None

    os.makedirs(job.jobs_dir, exist_ok=True)
    csv_path = os.path.join(job.jobs_dir, f"{job.job_id}_purchase.csv")
    html_path = os.path.join(job.jobs_dir, f"{job.job_id}_purchase.html")
    store_keys = list(_STORES.keys())

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["artist", "title", "album", *store_keys])
        for t in unavailable:
            links = t.purchase_links or build_purchase_links(t.artist, t.title)
            writer.writerow([t.artist, t.title, t.album or "", *[links.get(k, "") for k in store_keys]])

    rows = []
    for t in unavailable:
        links = t.purchase_links or build_purchase_links(t.artist, t.title)
        buy = " · ".join(
            f'<a href="{html.escape(links[k])}" target="_blank" rel="noopener">{store_label(k)}</a>'
            for k in store_keys if links.get(k)
        )
        rows.append(
            f"<tr><td>{html.escape(t.artist)}</td><td>{html.escape(t.title)}</td>"
            f"<td>{html.escape(t.album or '')}</td><td>{buy}</td></tr>"
        )

    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Purchase list — job {html.escape(job.job_id)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}}</style></head>
<body><h1>Tracks to buy ({len(unavailable)})</h1>
<p>Not available on the compliant free/CC sources. Buy from a legitimate store:</p>
<table><thead><tr><th>Artist</th><th>Title</th><th>Album</th><th>Buy from</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    return html_path
