from __future__ import annotations

import datetime
from pathlib import Path

import yaml

from .catalog import Catalog

SUBDIRS = ["originals", "pages", "preprocessed", "ocr/runs",
           "ground_truth", "reports", "rebuilt"]


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def catalog_path(self) -> Path:
        return self.root / "catalog.db"

    @property
    def audit_path(self) -> Path:
        return self.root / "catalog_audit.log"

    @property
    def originals_dir(self) -> Path:
        return self.root / "originals"

    @property
    def pages_dir(self) -> Path:
        return self.root / "pages"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def ground_truth_dir(self) -> Path:
        return self.root / "ground_truth"

    @property
    def gt_drafts_dir(self) -> Path:
        return self.root / "ground_truth" / "drafts"

    def run_dir(self, run_id: str) -> Path:
        return self.root / "ocr" / "runs" / run_id

    def open_catalog(self) -> Catalog:
        return Catalog(self.catalog_path, audit_path=self.audit_path)


def init_workspace(root: Path, corpus_name: str) -> Workspace:
    ws = Workspace(root)
    ws.root.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (ws.root / sub).mkdir(parents=True, exist_ok=True)
    cfg_path = ws.root / "workspace.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(yaml.safe_dump({
            "corpus_name": corpus_name,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "native_dpi": 300,
        }), encoding="utf-8")
    with ws.open_catalog() as cat:
        cat.init_schema()
    return ws


def load_workspace(root: Path) -> Workspace:
    ws = Workspace(root)
    if not (ws.root / "workspace.yaml").exists():
        raise FileNotFoundError(f"no workspace.yaml in {ws.root}")
    return ws
