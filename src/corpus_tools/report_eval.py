from __future__ import annotations

import html
import json
import statistics
from pathlib import Path

from .report import _CSS, _histogram_rows
from .workspace import Workspace


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def write_eval_report(ws: Workspace, run_id: str) -> Path:
    with ws.open_catalog() as cat:
        rows = [dict(r) for r in cat.conn.execute("""
            SELECT e.page_id, e.value AS cer, e.details_json,
                   g.stratum, p.quality_score, p.image_path
            FROM evaluations e
            LEFT JOIN gt_pages g ON g.page_id = e.page_id
            LEFT JOIN pages p ON p.page_id = e.page_id
            WHERE e.run_id = ? AND e.metric = 'cer'
            ORDER BY e.value DESC
        """, (run_id,)).fetchall()]
    if not rows:
        raise ValueError(f"no CER evaluations for run {run_id}")

    cers = [r["cer"] for r in rows]
    cers_sorted = sorted(cers)
    p90 = cers_sorted[min(int(0.9 * len(cers_sorted)), len(cers_sorted) - 1)]
    parts = [f"<style>{_CSS}</style><h1>Evaluation report — {html.escape(run_id)}</h1>",
             f"<p>pages: {len(rows)} &nbsp; median CER: {statistics.median(cers):.4f} "
             f"&nbsp; mean: {statistics.fmean(cers):.4f} &nbsp; p90: {p90:.4f}</p>"]

    parts.append("<h2>CER distribution</h2><table><tr><th>range</th><th>pages</th><th></th></tr>"
                 f"{_histogram_rows(cers)}</table>")

    strata: dict[str, list[float]] = {}
    for r in rows:
        strata.setdefault(r["stratum"] or "(unstratified)", []).append(r["cer"])
    parts.append("<h2>Per-stratum median CER</h2>"
                 "<table><tr><th>stratum</th><th>pages</th><th>median CER</th></tr>" +
                 "".join(f"<tr><td>{html.escape(s)}</td><td>{len(v)}</td>"
                         f"<td>{statistics.median(v):.4f}</td></tr>"
                         for s, v in sorted(strata.items())) + "</table>")

    calib = [(r["quality_score"], r["cer"]) for r in rows
             if r["quality_score"] is not None]
    if calib:
        r_val = _pearson([c[0] for c in calib], [c[1] for c in calib])
        r_txt = f"{r_val:.3f}" if r_val is not None else "n/a"
        parts.append(f"<h2>Calibration: quality_score vs CER</h2>"
                     f"<p>Pearson r = {r_txt} (n = {len(calib)})</p>"
                     "<table><tr><th>quality_score</th><th>CER</th></tr>" +
                     "".join(f"<tr><td>{q:.3f}</td><td>{c:.4f}</td></tr>"
                             for q, c in sorted(calib)) + "</table>")

    body = []
    for r in rows:
        d = json.loads(r["details_json"] or "{}")
        img = (f'<a href="../{html.escape(r["image_path"])}">image</a>'
               if r["image_path"] else "")
        body.append(f"<tr><td>{html.escape(r['page_id'])}</td><td>{r['cer']:.4f}</td>"
                    f"<td>{d.get('sub', '')}</td><td>{d.get('dele', '')}</td>"
                    f"<td>{d.get('ins', '')}</td><td>{d.get('ref_chars', '')}</td>"
                    f"<td>{img}</td></tr>")
    parts.append("<h2>Per-page CER (worst first)</h2>"
                 "<table><tr><th>page</th><th>CER</th><th>sub</th><th>del</th>"
                 "<th>ins</th><th>ref chars</th><th></th></tr>" + "".join(body) + "</table>")

    ws.reports_dir.mkdir(parents=True, exist_ok=True)
    out = ws.reports_dir / f"eval_{run_id}.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
