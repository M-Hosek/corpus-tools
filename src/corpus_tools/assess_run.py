from __future__ import annotations

import datetime

import cv2

from .assess import detect_script, garbage_ratio, measure_page, quality_score
from .workspace import Workspace


def assess_workspace(ws: Workspace, limit: int | None = None, force: bool = False) -> dict:
    stats = {"assessed": 0, "skipped": 0, "errors": []}
    with ws.open_catalog() as cat:
        where = "" if force else "assessed_at IS NULL"
        todo = cat.iter_pages(where)
        if limit:
            todo = todo[:limit]
        for page in todo:
            try:
                gray = cv2.imread(str(ws.root / page["image_path"]), cv2.IMREAD_GRAYSCALE)
                if gray is None:
                    raise FileNotFoundError(page["image_path"])
                fields = measure_page(gray)
                rp = cat.get_run_page("run0", page["page_id"])
                text = ""
                if rp and rp["text_path"]:
                    text = (ws.root / rp["text_path"]).read_text(encoding="utf-8")
                fields["script"] = detect_script(text)
                fields["garbage_ratio"] = round(garbage_ratio(text), 4)
                fields["quality_score"] = quality_score(fields)
                fields["assessed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                cat.update_page(page["page_id"], fields)
                stats["assessed"] += 1
            except Exception as e:
                stats["errors"].append(f"{page['page_id']}: {e}")
    return stats
