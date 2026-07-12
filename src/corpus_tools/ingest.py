from __future__ import annotations

import datetime
import hashlib
import json
import shutil
from pathlib import Path

from .pdfio import extract_spread_image, pdf_has_text, pdf_page_count
from .run0 import extract_run0_text
from .spreads import split_spread
from .workspace import Workspace


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def ingest_folder(ws: Workspace, folder: Path, limit: int | None = None) -> dict:
    stats = {"sources_new": 0, "sources_skipped": 0, "pages": 0, "errors": []}
    run0_dir = ws.run_dir("run0")
    run0_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(Path(folder).rglob("*.pdf"))
    if limit is not None:
        pdfs = pdfs[:limit]
    with ws.open_catalog() as cat:
        cat.add_run(dict(run_id="run0", engine="embedded", engine_version=None,
                         params_json=json.dumps({"note": "scanner-embedded OCR layer"}),
                         recipe=None, created_at=_now()))
        for pdf in pdfs:
            try:
                _ingest_pdf(ws, cat, pdf, stats)
            except Exception as e:  # keep batch going; record the failure
                stats["errors"].append(f"{pdf}: {type(e).__name__}: {e}")
    return stats


def _ingest_pdf(ws: Workspace, cat, pdf: Path, stats: dict) -> None:
    source_id = sha256_file(pdf)
    issue_label = pdf.parent.name
    if cat.get_source(source_id):
        stats["sources_skipped"] += 1
        return

    dest = ws.originals_dir / issue_label / pdf.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256_file(dest) != source_id:
        # Same filename, different bytes: don't let the new source_id get
        # paired with the old file's content. Disambiguate by content hash.
        dest = dest.parent / f"{dest.stem}.{source_id[:6]}{dest.suffix}"
    if not dest.exists():
        shutil.copy2(pdf, dest)

    n = pdf_page_count(dest)

    prefix = source_id[:6]
    for idx in range(1, n + 1):
        if _page_already_ingested(ws, cat, source_id, idx):
            continue
        spread = extract_spread_image(dest, idx)
        parts, gutter_x = split_spread(spread)
        texts = extract_run0_text(dest, idx, gutter_x, spread.width)
        for side, img in parts:
            page_id = f"{prefix}-p{idx:03d}{side}"
            png_rel = f"pages/{page_id}.png"
            png_abs = ws.root / png_rel
            if not png_abs.exists():
                img.save(png_abs)
            cat.add_page(dict(page_id=page_id, source_id=source_id,
                              pdf_page_index=idx, side=side, image_path=png_rel,
                              width_px=img.width, height_px=img.height))
            cat.update_page(page_id, {"issue_label": issue_label})
            text = texts.get(side, "")
            txt_rel = f"ocr/runs/run0/{page_id}.txt"
            txt_abs = ws.root / txt_rel
            if not txt_abs.exists():
                txt_abs.write_text(text, encoding="utf-8")
            cat.add_run_page(dict(run_id="run0", page_id=page_id, text_path=txt_rel,
                                  char_count=len(text), confidence=None))
            stats["pages"] += 1

    cat.upsert_source(dict(
        source_id=source_id, rel_path=str(dest.relative_to(ws.root)),
        original_path=str(pdf), issue_label=issue_label, file_size=pdf.stat().st_size,
        page_count=n, has_embedded_ocr=int(pdf_has_text(dest)), ingested_at=_now()))
    stats["sources_new"] += 1


def _page_already_ingested(ws: Workspace, cat, source_id: str, idx: int) -> bool:
    rows = cat.iter_pages("source_id = ? AND pdf_page_index = ?", (source_id, idx))
    if not rows:
        return False
    sides = {row["side"] for row in rows}
    if sides not in ({"L", "R"}, {"F"}):
        # A crash between committing one side and the other leaves a lone
        # {L} or {R}: incomplete, must be reprocessed (writes are
        # exists-guarded and inserts are OR IGNORE, so this is safe).
        return False
    for row in rows:
        if not row.get("image_path") or not (ws.root / row["image_path"]).exists():
            return False
        rp = cat.get_run_page("run0", row["page_id"])
        if not rp or not rp.get("text_path") or not (ws.root / rp["text_path"]).exists():
            return False
    return True
