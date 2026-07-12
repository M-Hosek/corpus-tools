from __future__ import annotations

import html
from pathlib import Path

from PIL import Image

from .workspace import Workspace

_METRICS = ["quality_score", "contrast", "background_gray", "ink_density",
            "noise", "skew_deg", "garbage_ratio"]

_CSS = """
body{font-family:Segoe UI,sans-serif;margin:2em;max-width:1100px}
table{border-collapse:collapse;margin:1em 0}
td,th{border:1px solid #ccc;padding:4px 10px;text-align:right}
th{background:#f0f0f0}
.bar{background:#4a7ebb;height:12px;display:inline-block}
.gallery{display:flex;flex-wrap:wrap;gap:10px}
.card{width:160px;font-size:11px;text-align:center}
.card img{width:150px;border:1px solid #999}
"""


def _histogram_rows(values: list[float], buckets: int = 10) -> str:
    if not values:
        return "<tr><td colspan=3>no data</td></tr>"
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    counts = [0] * buckets
    for v in values:
        counts[min(int((v - lo) / span * buckets), buckets - 1)] += 1
    peak = max(counts) or 1
    rows = []
    for i, c in enumerate(counts):
        a, b = lo + span * i / buckets, lo + span * (i + 1) / buckets
        w = int(300 * c / peak)
        rows.append(f"<tr><td>{a:.2f}–{b:.2f}</td><td>{c}</td>"
                    f'<td style="text-align:left"><span class="bar" style="width:{w}px"></span></td></tr>')
    return "\n".join(rows)


def _thumb(ws: Workspace, page: dict, thumbs_dir: Path) -> str:
    out = thumbs_dir / (page["page_id"] + ".jpg")
    if not out.exists():
        im = Image.open(ws.root / page["image_path"]).convert("L")
        im.thumbnail((300, 300))
        im.save(out, quality=70)
    return out.name


def _gallery(ws: Workspace, pages: list[dict], thumbs_dir: Path) -> str:
    cards = []
    for p in pages:
        name = _thumb(ws, p, thumbs_dir)
        cards.append(
            f'<div class="card"><img src="thumbs/{name}"><br>'
            f"{html.escape(p['page_id'])}<br>q={p['quality_score']:.2f} "
            f"c={p['contrast']:.0f} g={p['garbage_ratio']:.2f}</div>")
    return '<div class="gallery">' + "\n".join(cards) + "</div>"


def write_assess_report(ws: Workspace) -> Path:
    thumbs_dir = ws.reports_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        n_sources = cat.count("sources")
        n_pages = cat.count("pages")
        assessed = cat.iter_pages("assessed_at IS NOT NULL")

    parts = [f"<style>{_CSS}</style><h1>Assessment report</h1>",
             f"<p>sources: {n_sources} &nbsp; pages: {n_pages} &nbsp; assessed: {len(assessed)}</p>"]

    scripts: dict[str, int] = {}
    for p in assessed:
        scripts[p["script"] or "?"] = scripts.get(p["script"] or "?", 0) + 1
    parts.append("<h2>Script breakdown</h2><table><tr><th>script</th><th>pages</th></tr>" +
                 "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
                         for k, v in sorted(scripts.items())) + "</table>")

    for m in _METRICS:
        vals = [p[m] for p in assessed if p[m] is not None]
        parts.append(f"<h2>{m}</h2><table><tr><th>range</th><th>pages</th><th></th></tr>"
                     f"{_histogram_rows(vals)}</table>")

    ranked = sorted((p for p in assessed if p["quality_score"] is not None),
                    key=lambda p: p["quality_score"])
    if ranked:
        parts.append("<h2>Lowest-quality pages</h2>" + _gallery(ws, ranked[:12], thumbs_dir))
        parts.append("<h2>Highest-quality pages</h2>" + _gallery(ws, ranked[-12:][::-1], thumbs_dir))

    out = ws.reports_dir / "assess_report.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
