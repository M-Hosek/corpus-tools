from __future__ import annotations

import datetime

from .sampling import stratified_sample
from .workspace import Workspace

_NOTES_TEMPLATE = """# {page_id} — transcription notes

- date:
- method: ocr-base | scratch
- confidence: high | medium | low
- notes:
"""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def scaffold_sample(ws: Workspace, n: int = 40, seed: int = 1979) -> dict:
    stats = {"selected": 0, "already": 0, "drafts_written": 0}
    ws.gt_drafts_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        cat.init_schema()
        pages = cat.iter_pages("assessed_at IS NOT NULL")
        existing = {g["page_id"] for g in cat.iter_gt_pages()}
        for p in stratified_sample(pages, n=n, seed=seed):
            pid = p["page_id"]
            if pid in existing:
                stats["already"] += 1
                continue
            cat.upsert_gt_page({"page_id": pid, "stratum": p["stratum"],
                                "status": "selected", "selected_at": _now(),
                                "completed_at": None})
            stats["selected"] += 1
            draft = ws.gt_drafts_dir / f"{pid}.txt"
            if not draft.exists():
                rp = cat.get_run_page("run0", pid)
                text = ""
                if rp and rp["text_path"]:
                    src = ws.root / rp["text_path"]
                    if src.exists():
                        text = src.read_text(encoding="utf-8")
                draft.write_text(text, encoding="utf-8")
                stats["drafts_written"] += 1
            notes = ws.gt_drafts_dir / f"{pid}.notes.md"
            if not notes.exists():
                notes.write_text(_NOTES_TEMPLATE.format(page_id=pid), encoding="utf-8")
    return stats


def sync_gt_status(ws: Workspace) -> dict:
    stats = {"selected": 0, "done": 0, "adopted": 0}
    with ws.open_catalog() as cat:
        cat.init_schema()
        known = {g["page_id"]: g for g in cat.iter_gt_pages()}
        for g in known.values():
            final = ws.ground_truth_dir / f"{g['page_id']}.txt"
            if final.exists() and final.read_text(encoding="utf-8").strip():
                if g["status"] != "done":
                    cat.upsert_gt_page(dict(g, status="done",
                                            completed_at=g["completed_at"] or _now()))
                stats["done"] += 1
            else:
                stats["selected"] += 1
        for final in sorted(ws.ground_truth_dir.glob("*.txt")):
            pid = final.stem
            if pid in known or not final.read_text(encoding="utf-8").strip():
                continue
            cat.upsert_gt_page({"page_id": pid, "stratum": None, "status": "done",
                                "selected_at": _now(), "completed_at": _now()})
            stats["adopted"] += 1
            stats["done"] += 1
    return stats
