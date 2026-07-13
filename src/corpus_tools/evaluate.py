from __future__ import annotations

import datetime
import json

from .metrics import cer
from .workspace import Workspace


def evaluate_run(ws: Workspace, run_id: str) -> dict:
    stats: dict = {"evaluated": 0, "skipped": [], "errors": []}
    with ws.open_catalog() as cat:
        cat.init_schema()
        for g in cat.iter_gt_pages(status="done"):
            pid = g["page_id"]
            gt_path = ws.ground_truth_dir / f"{pid}.txt"
            rp = cat.get_run_page(run_id, pid)
            if rp is None or not rp["text_path"]:
                stats["skipped"].append(pid)
                continue
            hyp_path = ws.root / rp["text_path"]
            try:
                ref = gt_path.read_text(encoding="utf-8")
                hyp = hyp_path.read_text(encoding="utf-8") if hyp_path.exists() else ""
                res = cer(ref, hyp)
            except ValueError:
                stats["skipped"].append(pid)      # empty reference
                continue
            except OSError as e:
                stats["errors"].append(f"{pid}: {e}")
                continue
            cat.add_evaluation({
                "run_id": run_id, "page_id": pid, "metric": "cer",
                "value": res["cer"],
                "details_json": json.dumps(
                    {k: res[k] for k in ("distance", "sub", "dele", "ins", "ref_chars")}),
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            })
            stats["evaluated"] += 1
    return stats
