# Phase 1: corpus_tools Foundation + Ingest + Assess — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `corpus_tools` Python package with a SQLite catalog, ingest 231 source PDFs (splitting two-page spreads into per-magazine-page images and extracting the embedded OCR as run 0), and produce per-page quality assessments with an HTML report.

**Architecture:** One installable package (`src/corpus_tools/`) holds all logic; a thin argparse CLI (`python -m corpus_tools`) exposes it; two Claude Code skills (`corpus-ingest`, `corpus-assess`) orchestrate the CLI. All state lives in a file-based workspace with `catalog.db` (SQLite) as the single source of truth. Originals are copied in, checksummed, and never modified.

**Tech Stack:** Python 3.13, pypdf, Pillow, NumPy, opencv-python-headless, PyYAML, pytest. SQLite via stdlib `sqlite3`.

**Spec:** `docs/superpowers/specs/2026-07-12-ocr-corpus-pipeline-design.md` (esp. §0 source findings, §3 data model).

## Global Constraints

- Repo root: the project checkout (Windows). Source PDFs: `incoming\sf magazines 2025\<issue folder>\NNNN_NNN.pdf` (231 files). Commands below run from repo root; PowerShell is the shell.
- Workspace default location: `workspace/` under repo root (already gitignored, as is `incoming/`).
- Originals are read-only: ingest copies into `workspace/originals/`, never moves or rewrites source files.
- Page is the atomic unit. Page-id format: `<sha256-hex-first-6-of-source>-p<3-digit-1-based-pdf-page><L|R|F>` (e.g. `b3f2a1-p003L`). `F` = full/unsplit page (no gutter detected).
- Embedded scan images are extracted losslessly (they are native 300 DPI); never re-render pages.
- Embedded scanner OCR is stored as run `run0`, engine `embedded`, and is never overwritten.
- Every catalog mutation is also appended to `workspace/catalog_audit.log` as a JSON line.
- All text files written as UTF-8. All ingest/assess operations must be idempotent and resumable (re-running skips completed work).
- Python source lives in `src/corpus_tools/`; tests in `tests/`; every commit ends with the Co-Authored-By line: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Deferred from spec §4 (deliberate, do not add):** text-orientation detection (needs OCR-based signals; lands in Phase 3 with `corpus-triage`) and explicit triage-tier proposals in the assess report (the quality_score distributions and galleries are Phase 1's input to tiering; tier assignment is the Phase 3 triage skill's job).

---

### Task 1: Package scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/corpus_tools/__init__.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: importable `corpus_tools` package, `corpus_tools.__version__`, and an installed dev environment with pytest.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "corpus-tools"
version = "0.1.0"
description = "Reusable OCR remediation pipeline for scanned archival corpora"
requires-python = ">=3.12"
dependencies = [
    "pypdf>=6",
    "pillow>=10",
    "numpy>=2",
    "opencv-python-headless>=4.10",
    "pyyaml>=6",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write src/corpus_tools/__init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Write the test**

`tests/test_scaffold.py`:

```python
import corpus_tools


def test_package_importable():
    assert corpus_tools.__version__ == "0.1.0"
```

- [ ] **Step 4: Install editable and run test**

Run: `pip install -e .[dev]` then `pytest tests/test_scaffold.py -v`
Expected: install succeeds (opencv wheel download may take a minute); test PASSES.

- [ ] **Step 5: Commit**

```
git add pyproject.toml src tests
git commit -m "feat: scaffold corpus_tools package"
```

---

### Task 2: Catalog (SQLite schema + audit log)

**Files:**
- Create: `src/corpus_tools/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `Catalog(db_path: Path, audit_path: Path | None = None)` with methods:
  - `init_schema() -> None` (idempotent)
  - `upsert_source(source: dict) -> None` — keys: `source_id, rel_path, original_path, issue_label, file_size, page_count, has_embedded_ocr, ingested_at`
  - `get_source(source_id: str) -> dict | None`
  - `add_page(page: dict) -> None` — keys: `page_id, source_id, pdf_page_index, side, image_path, width_px, height_px`
  - `get_page(page_id: str) -> dict | None`
  - `iter_pages(where: str = "", params: tuple = ()) -> list[dict]`
  - `update_page(page_id: str, fields: dict) -> None`
  - `add_run(run: dict) -> None` — keys: `run_id, engine, engine_version, params_json, recipe, created_at`
  - `add_run_page(rp: dict) -> None` — keys: `run_id, page_id, text_path, char_count, confidence`
  - `get_run_page(run_id: str, page_id: str) -> dict | None`
  - `count(table: str) -> int`
  - `close() -> None`; also usable as a context manager.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog.py`:

```python
import json
from pathlib import Path

import pytest

from corpus_tools.catalog import Catalog


@pytest.fixture
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db", audit_path=tmp_path / "audit.log")
    c.init_schema()
    yield c
    c.close()


SRC = dict(source_id="a" * 64, rel_path="originals/x.pdf", original_path="in/x.pdf",
           issue_label="kexue wenyi 1979.1", file_size=123, page_count=9,
           has_embedded_ocr=1, ingested_at="2026-07-12T00:00:00")


def test_source_roundtrip(cat):
    cat.upsert_source(SRC)
    got = cat.get_source("a" * 64)
    assert got["issue_label"] == "kexue wenyi 1979.1"
    assert cat.get_source("b" * 64) is None


def test_upsert_source_idempotent(cat):
    cat.upsert_source(SRC)
    cat.upsert_source(SRC)
    assert cat.count("sources") == 1


def test_page_roundtrip_and_update(cat):
    cat.upsert_source(SRC)
    cat.add_page(dict(page_id="aaaaaa-p001L", source_id="a" * 64, pdf_page_index=1,
                      side="L", image_path="pages/aaaaaa-p001L.png",
                      width_px=2100, height_px=3000))
    cat.update_page("aaaaaa-p001L", {"skew_deg": 0.5, "script": "simplified"})
    got = cat.get_page("aaaaaa-p001L")
    assert got["skew_deg"] == 0.5
    assert got["side"] == "L"
    rows = cat.iter_pages("side = ?", ("L",))
    assert len(rows) == 1


def test_run_and_run_page(cat):
    cat.upsert_source(SRC)
    cat.add_page(dict(page_id="aaaaaa-p001L", source_id="a" * 64, pdf_page_index=1,
                      side="L", image_path=None, width_px=None, height_px=None))
    cat.add_run(dict(run_id="run0", engine="embedded", engine_version=None,
                     params_json="{}", recipe=None, created_at="2026-07-12T00:00:00"))
    cat.add_run_page(dict(run_id="run0", page_id="aaaaaa-p001L",
                          text_path="ocr/runs/run0/aaaaaa-p001L.txt",
                          char_count=3074, confidence=None))
    got = cat.get_run_page("run0", "aaaaaa-p001L")
    assert got["char_count"] == 3074
    assert cat.get_run_page("run0", "nope") is None


def test_audit_log_written(cat, tmp_path):
    cat.upsert_source(SRC)
    lines = (tmp_path / "audit.log").read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["action"] == "upsert_source"
    assert rec["data"]["source_id"] == "a" * 64


def test_init_schema_idempotent(tmp_path):
    c = Catalog(tmp_path / "c.db")
    c.init_schema()
    c.init_schema()
    assert c.count("pages") == 0
    c.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corpus_tools.catalog'`

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/catalog.py`:

```python
from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    rel_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    issue_label TEXT,
    file_size INTEGER NOT NULL,
    page_count INTEGER,
    has_embedded_ocr INTEGER,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    page_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    pdf_page_index INTEGER NOT NULL,
    side TEXT NOT NULL,
    image_path TEXT,
    width_px INTEGER,
    height_px INTEGER,
    skew_deg REAL,
    contrast REAL,
    background_gray REAL,
    ink_density REAL,
    noise REAL,
    script TEXT,
    garbage_ratio REAL,
    quality_score REAL,
    triage_tier TEXT,
    issue_label TEXT,
    article TEXT,
    notes TEXT,
    assessed_at TEXT
);
CREATE TABLE IF NOT EXISTS ocr_runs (
    run_id TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    engine_version TEXT,
    params_json TEXT,
    recipe TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_pages (
    run_id TEXT NOT NULL REFERENCES ocr_runs(run_id),
    page_id TEXT NOT NULL REFERENCES pages(page_id),
    text_path TEXT,
    char_count INTEGER,
    confidence REAL,
    PRIMARY KEY (run_id, page_id)
);
CREATE TABLE IF NOT EXISTS evaluations (
    run_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    details_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, page_id, metric)
);
CREATE INDEX IF NOT EXISTS idx_pages_source ON pages(source_id);
"""

_PAGE_MUTABLE = {
    "image_path", "width_px", "height_px", "skew_deg", "contrast",
    "background_gray", "ink_density", "noise", "script", "garbage_ratio",
    "quality_score", "triage_tier", "issue_label", "article", "notes",
    "assessed_at",
}


class Catalog:
    def __init__(self, db_path: Path, audit_path: Path | None = None):
        self.db_path = Path(db_path)
        self.audit_path = Path(audit_path) if audit_path else self.db_path.parent / "catalog_audit.log"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _audit(self, action: str, data: dict) -> None:
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
               "action": action, "data": data}
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _write(self, action: str, sql: str, data: dict) -> None:
        self.conn.execute(sql, data)
        self.conn.commit()
        self._audit(action, data)

    def upsert_source(self, source: dict) -> None:
        self._write("upsert_source", """
            INSERT INTO sources (source_id, rel_path, original_path, issue_label,
                                 file_size, page_count, has_embedded_ocr, ingested_at)
            VALUES (:source_id, :rel_path, :original_path, :issue_label,
                    :file_size, :page_count, :has_embedded_ocr, :ingested_at)
            ON CONFLICT(source_id) DO UPDATE SET
                rel_path=excluded.rel_path, issue_label=excluded.issue_label,
                page_count=excluded.page_count, has_embedded_ocr=excluded.has_embedded_ocr
        """, source)

    def get_source(self, source_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM sources WHERE source_id = ?",
                                (source_id,)).fetchone()
        return dict(row) if row else None

    def add_page(self, page: dict) -> None:
        self._write("add_page", """
            INSERT OR IGNORE INTO pages (page_id, source_id, pdf_page_index, side,
                                         image_path, width_px, height_px)
            VALUES (:page_id, :source_id, :pdf_page_index, :side,
                    :image_path, :width_px, :height_px)
        """, page)

    def get_page(self, page_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM pages WHERE page_id = ?",
                                (page_id,)).fetchone()
        return dict(row) if row else None

    def iter_pages(self, where: str = "", params: tuple = ()) -> list[dict]:
        sql = "SELECT * FROM pages"
        if where:
            sql += " WHERE " + where
        sql += " ORDER BY page_id"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def update_page(self, page_id: str, fields: dict) -> None:
        bad = set(fields) - _PAGE_MUTABLE
        if bad:
            raise ValueError(f"not updatable: {bad}")
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        data = dict(fields, page_id=page_id)
        self._write("update_page", f"UPDATE pages SET {sets} WHERE page_id = :page_id", data)

    def add_run(self, run: dict) -> None:
        self._write("add_run", """
            INSERT OR IGNORE INTO ocr_runs (run_id, engine, engine_version,
                                            params_json, recipe, created_at)
            VALUES (:run_id, :engine, :engine_version, :params_json, :recipe, :created_at)
        """, run)

    def add_run_page(self, rp: dict) -> None:
        self._write("add_run_page", """
            INSERT OR IGNORE INTO run_pages (run_id, page_id, text_path, char_count, confidence)
            VALUES (:run_id, :page_id, :text_path, :char_count, :confidence)
        """, rp)

    def get_run_page(self, run_id: str, page_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM run_pages WHERE run_id = ? AND page_id = ?",
            (run_id, page_id)).fetchone()
        return dict(row) if row else None

    def count(self, table: str) -> int:
        if table not in {"sources", "pages", "ocr_runs", "run_pages", "evaluations"}:
            raise ValueError(table)
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_catalog.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/catalog.py tests/test_catalog.py
git commit -m "feat: SQLite catalog with audit log"
```

---

### Task 3: Workspace init/load

**Files:**
- Create: `src/corpus_tools/workspace.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `Catalog` from Task 2.
- Produces:
  - `class Workspace` with attributes `root: Path`; properties `catalog_path`, `audit_path`, `originals_dir`, `pages_dir`, `reports_dir`, `run_dir(run_id: str) -> Path`; method `open_catalog() -> Catalog`.
  - `init_workspace(root: Path, corpus_name: str) -> Workspace` (idempotent)
  - `load_workspace(root: Path) -> Workspace` (raises `FileNotFoundError` if `workspace.yaml` missing)

- [ ] **Step 1: Write the failing tests**

`tests/test_workspace.py`:

```python
import pytest
import yaml

from corpus_tools.workspace import init_workspace, load_workspace


def test_init_creates_layout(tmp_path):
    ws = init_workspace(tmp_path / "ws", "kexue-wenyi")
    for sub in ["originals", "pages", "preprocessed", "ocr/runs",
                "ground_truth", "reports", "rebuilt"]:
        assert (ws.root / sub).is_dir()
    assert ws.catalog_path.exists()
    cfg = yaml.safe_load((ws.root / "workspace.yaml").read_text(encoding="utf-8"))
    assert cfg["corpus_name"] == "kexue-wenyi"
    with ws.open_catalog() as cat:
        assert cat.count("pages") == 0


def test_init_idempotent(tmp_path):
    init_workspace(tmp_path / "ws", "kexue-wenyi")
    ws = init_workspace(tmp_path / "ws", "ignored-second-name")
    cfg = yaml.safe_load((ws.root / "workspace.yaml").read_text(encoding="utf-8"))
    assert cfg["corpus_name"] == "kexue-wenyi"


def test_load_requires_existing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workspace(tmp_path / "missing")
    init_workspace(tmp_path / "ws", "x")
    ws = load_workspace(tmp_path / "ws")
    assert ws.run_dir("run0") == ws.root / "ocr" / "runs" / "run0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_workspace.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/workspace.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_workspace.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/workspace.py tests/test_workspace.py
git commit -m "feat: workspace layout and init/load"
```

---

### Task 4: Spread splitting (synthetic-image TDD)

**Files:**
- Create: `src/corpus_tools/spreads.py`
- Test: `tests/test_spreads.py`

**Interfaces:**
- Produces:
  - `find_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int]` — (x, y, w, h) of the bright page region against the dark scanner background.
  - `find_gutter_x(gray: np.ndarray, bbox) -> int | None` — absolute x of the gutter valley, or None if no confident gutter (single page).
  - `split_spread(img: PIL.Image.Image) -> tuple[list[tuple[str, PIL.Image.Image]], int | None]` — `([("L", left), ("R", right)], gutter_x)` for spreads, `([("F", full)], None)` for single pages. Crops exclude the scanner background.

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads.py`:

```python
import numpy as np
from PIL import Image

from corpus_tools.spreads import find_content_bbox, find_gutter_x, split_spread

BG, PAGE, GUTTER = 30, 225, 90


def make_spread(w=1500, h=1000, gutter_w=24) -> Image.Image:
    """Dark background, two bright pages, dark-ish gutter between them."""
    a = np.full((h, w), BG, dtype=np.uint8)
    # content region inset 60 px from each edge
    a[60:h - 60, 60:w - 60] = PAGE
    mid = w // 2
    a[60:h - 60, mid - gutter_w // 2: mid + gutter_w // 2] = GUTTER
    return Image.fromarray(a).convert("RGB")


def make_single(w=800, h=1000) -> Image.Image:
    a = np.full((h, w), BG, dtype=np.uint8)
    a[50:h - 50, 50:w - 50] = PAGE
    return Image.fromarray(a).convert("RGB")


def test_content_bbox_excludes_background():
    gray = np.array(make_spread().convert("L"))
    x, y, w, h = find_content_bbox(gray)
    assert 40 <= x <= 70 and 40 <= y <= 70
    assert 1360 <= w <= 1420 and 860 <= h <= 920


def test_gutter_found_near_center():
    gray = np.array(make_spread().convert("L"))
    gx = find_gutter_x(gray, find_content_bbox(gray))
    assert gx is not None
    assert abs(gx - 750) < 30


def test_split_spread_returns_two_bright_halves():
    parts, gx = split_spread(make_spread())
    assert [s for s, _ in parts] == ["L", "R"]
    assert gx is not None
    for _, im in parts:
        arr = np.array(im.convert("L"))
        assert arr.mean() > 150          # mostly page, little background
        assert 600 < im.width < 800      # roughly half of the 1380px content


def test_single_page_not_split():
    parts, gx = split_spread(make_single())
    assert [s for s, _ in parts] == ["F"]
    assert gx is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spreads.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/spreads.py`:

```python
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Gutter must be at least this many gray levels darker than the page median.
GUTTER_MIN_DEPTH = 20
# A content region narrower than 1.1x its height is a single page, not a spread.
SPREAD_MIN_ASPECT = 1.1


def find_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int]:
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return (0, 0, gray.shape[1], gray.shape[0])
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
            int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))


def find_gutter_x(gray: np.ndarray, bbox: tuple[int, int, int, int]) -> int | None:
    x, y, w, h = bbox
    if w < SPREAD_MIN_ASPECT * h:
        return None
    region = gray[y:y + h, x:x + w]
    col = region.mean(axis=0)
    col = np.convolve(col, np.ones(31) / 31, mode="same")
    lo, hi = int(w * 0.35), int(w * 0.65)
    gx = lo + int(np.argmin(col[lo:hi]))
    if np.median(col) - col[gx] < GUTTER_MIN_DEPTH:
        return None
    return x + gx


def split_spread(img: Image.Image) -> tuple[list[tuple[str, Image.Image]], int | None]:
    gray = np.array(img.convert("L"))
    bbox = find_content_bbox(gray)
    x, y, w, h = bbox
    gx = find_gutter_x(gray, bbox)
    if gx is None:
        return [("F", img.crop((x, y, x + w, y + h)))], None
    return [("L", img.crop((x, y, gx, y + h))),
            ("R", img.crop((gx, y, x + w, y + h)))], gx
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spreads.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/spreads.py tests/test_spreads.py
git commit -m "feat: spread detection and gutter splitting"
```

---

### Task 5: Real-PDF test fixture

**Files:**
- Create: `tests/fixtures/sample_chunk.pdf` (copied from corpus)
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: pytest fixture `sample_pdf -> Path` pointing at a real 2.5 MB scanner chunk (spread images + embedded OCR), used by Tasks 6–8 integration tests.

- [ ] **Step 1: Copy the smallest real chunk into fixtures**

Run (PowerShell — locates the smallest chunk wherever it lives):
```
New-Item -ItemType Directory -Force tests\fixtures | Out-Null
$smallest = Get-ChildItem incoming -Recurse -Filter *.pdf | Sort-Object Length | Select-Object -First 1
Copy-Item $smallest.FullName tests\fixtures\sample_chunk.pdf
```
The tests only assume the fixture has ≥1 page with one large embedded scan image and non-empty embedded text (all corpus chunks satisfy this).

- [ ] **Step 2: Write conftest**

`tests/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    p = FIXTURES / "sample_chunk.pdf"
    if not p.exists():
        pytest.skip("real-PDF fixture not present")
    return p
```

- [ ] **Step 3: Verify collection still works**

Run: `pytest --collect-only -q`
Expected: existing tests listed, no errors.

- [ ] **Step 4: Commit**

```
git add tests/fixtures/sample_chunk.pdf tests/conftest.py
git commit -m "test: add real scanner-chunk PDF fixture"
```

---

### Task 6: Spread-image extraction from PDFs

**Files:**
- Create: `src/corpus_tools/pdfio.py`
- Test: `tests/test_pdfio.py`

**Interfaces:**
- Consumes: `sample_pdf` fixture (Task 5).
- Produces:
  - `pdf_page_count(pdf_path: Path) -> int`
  - `extract_spread_image(pdf_path: Path, page_index: int) -> PIL.Image.Image` — largest embedded image of the given 1-based page, unmodified pixels. Raises `ValueError` if the page has no images.
  - `pdf_has_text(pdf_path: Path) -> bool` — True if page 1 (or page 2 when page 1 is empty) yields extractable text.

- [ ] **Step 1: Write the failing tests**

`tests/test_pdfio.py`:

```python
from corpus_tools.pdfio import extract_spread_image, pdf_has_text, pdf_page_count


def test_page_count_positive(sample_pdf):
    assert pdf_page_count(sample_pdf) >= 1


def test_extract_spread_image_is_large_scan(sample_pdf):
    im = extract_spread_image(sample_pdf, 1)
    assert im.width > 2000 and im.height > 2000  # native ~300 DPI scan


def test_has_text(sample_pdf):
    assert pdf_has_text(sample_pdf) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdfio.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/pdfio.py`:

```python
from __future__ import annotations

from pathlib import Path

from PIL import Image
from pypdf import PdfReader


def pdf_page_count(pdf_path: Path) -> int:
    return len(PdfReader(pdf_path).pages)


def extract_spread_image(pdf_path: Path, page_index: int) -> Image.Image:
    page = PdfReader(pdf_path).pages[page_index - 1]
    images = list(page.images)
    if not images:
        raise ValueError(f"{pdf_path} page {page_index}: no embedded images")
    largest = max(images, key=lambda i: i.image.width * i.image.height)
    return largest.image


def pdf_has_text(pdf_path: Path) -> bool:
    reader = PdfReader(pdf_path)
    for page in reader.pages[:2]:
        if (page.extract_text() or "").strip():
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdfio.py -v`
Expected: 3 PASS (a few seconds; image decode is real work).

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/pdfio.py tests/test_pdfio.py
git commit -m "feat: lossless spread-image extraction from source PDFs"
```

---

### Task 7: Run-0 text extraction split at the gutter

**Files:**
- Create: `src/corpus_tools/run0.py`
- Test: `tests/test_run0.py`

**Interfaces:**
- Consumes: `sample_pdf` fixture; gutter x in image pixels from `split_spread` (Task 4); image width from `extract_spread_image` (Task 6).
- Produces: `extract_run0_text(pdf_path: Path, page_index: int, gutter_x_px: int | None, image_width_px: int) -> dict[str, str]` — mapping side (`"L"`/`"R"`, or `"F"` when `gutter_x_px is None`) to embedded-OCR text for that half, fragments in content-stream order, newline-joined.

**Approach note for the implementer:** the embedded OCR covers the whole spread; pypdf's `extract_text(visitor_text=...)` reports each text fragment with its transform matrices. We map the gutter from image pixels to PDF points (`gutter_pt = gutter_x_px / image_width_px * mediabox_width`) and assign each fragment to L or R by its user-space x. The user-space x of a fragment is `cm[0]*tm[4] + cm[2]*tm[5] + cm[4]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_run0.py`:

```python
from pypdf import PdfReader

from corpus_tools.pdfio import extract_spread_image, pdf_page_count
from corpus_tools.run0 import extract_run0_text
from corpus_tools.spreads import split_spread


def _body_page(sample_pdf):
    """Pick a middle page (body text, not cover) for a meaningful test."""
    return max(1, pdf_page_count(sample_pdf) // 2)


def test_full_page_text_nonempty(sample_pdf):
    idx = _body_page(sample_pdf)
    out = extract_run0_text(sample_pdf, idx, None, 4299)
    assert set(out) == {"F"}
    assert len(out["F"]) > 200


def test_split_text_both_sides_and_covers_full(sample_pdf):
    idx = _body_page(sample_pdf)
    im = extract_spread_image(sample_pdf, idx)
    parts, gx = split_spread(im)
    if gx is None:
        import pytest
        pytest.skip("fixture middle page is not a spread")
    out = extract_run0_text(sample_pdf, idx, gx, im.width)
    assert set(out) == {"L", "R"}
    assert len(out["L"]) > 100 and len(out["R"]) > 100
    full = extract_run0_text(sample_pdf, idx, None, im.width)["F"]
    # no text is lost by splitting (whitespace layout may differ)
    assert len(out["L"].split()) + len(out["R"].split()) == len(full.split())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_run0.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/run0.py`:

```python
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_run0_text(pdf_path: Path, page_index: int,
                      gutter_x_px: int | None, image_width_px: int) -> dict[str, str]:
    page = PdfReader(pdf_path).pages[page_index - 1]
    if gutter_x_px is None:
        return {"F": (page.extract_text() or "").strip()}

    gutter_pt = gutter_x_px / image_width_px * float(page.mediabox.width)
    frags: dict[str, list[str]] = {"L": [], "R": []}

    def visitor(text, cm, tm, font_dict, font_size):
        if not text.strip():
            return
        x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
        frags["L" if x < gutter_pt else "R"].append(text)

    page.extract_text(visitor_text=visitor)
    return {side: "\n".join(parts).strip() for side, parts in frags.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run0.py -v`
Expected: 2 PASS. If the word-count assertion fails by a small margin, inspect whether pypdf's plain `extract_text` inserts extra whitespace; it is acceptable to relax the last assertion to `>= 0.98 *` the full count — document the relaxation in the test with a comment.

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/run0.py tests/test_run0.py
git commit -m "feat: run-0 embedded OCR extraction split at gutter"
```

---

### Task 8: Ingest orchestration + CLI

**Files:**
- Create: `src/corpus_tools/ingest.py`
- Create: `src/corpus_tools/__main__.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces:
  - `sha256_file(path: Path) -> str`
  - `ingest_folder(ws: Workspace, folder: Path, limit: int | None = None) -> dict` — walks `folder` recursively for `*.pdf`; per file: checksum → skip if source already cataloged; copy to `originals/<issue_label>/<filename>`; per PDF page: extract spread image, split, save page PNGs to `pages/`, add page rows, write run-0 text to `ocr/runs/run0/<page_id>.txt`, add run_page rows. Returns stats dict `{"sources_new": int, "sources_skipped": int, "pages": int, "errors": [str, ...]}`. Issue label = name of the PDF's parent folder. Idempotent at page level too: a page whose PNG and catalog row and run-0 text all exist is skipped.
  - CLI: `python -m corpus_tools init <ws> --name <corpus>`, `python -m corpus_tools ingest <src-folder> --workspace <ws> [--limit N]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest.py`:

```python
import shutil

from corpus_tools.ingest import ingest_folder, sha256_file
from corpus_tools.workspace import init_workspace


def _setup(tmp_path, sample_pdf):
    src = tmp_path / "in" / "kexue wenyi 1980.5"
    src.mkdir(parents=True)
    shutil.copy(sample_pdf, src / "0838_043.pdf")
    ws = init_workspace(tmp_path / "ws", "test")
    return ws, tmp_path / "in"


def test_sha256_stable(sample_pdf):
    assert sha256_file(sample_pdf) == sha256_file(sample_pdf)
    assert len(sha256_file(sample_pdf)) == 64


def test_ingest_populates_workspace(tmp_path, sample_pdf):
    ws, src = _setup(tmp_path, sample_pdf)
    stats = ingest_folder(ws, src)
    assert stats["sources_new"] == 1 and not stats["errors"]
    with ws.open_catalog() as cat:
        assert cat.count("sources") == 1
        pages = cat.iter_pages()
        assert len(pages) >= 1
        src_row = cat.get_source(pages[0]["source_id"])
        assert src_row["issue_label"] == "kexue wenyi 1980.5"
        # every page has an image on disk and a run-0 text entry
        for p in pages:
            assert (ws.root / p["image_path"]).exists()
            rp = cat.get_run_page("run0", p["page_id"])
            assert rp is not None
            assert (ws.root / rp["text_path"]).exists()
    # original copied, read-only reference
    assert any(ws.originals_dir.rglob("0838_043.pdf"))


def test_ingest_idempotent(tmp_path, sample_pdf):
    ws, src = _setup(tmp_path, sample_pdf)
    first = ingest_folder(ws, src)
    second = ingest_folder(ws, src)
    assert second["sources_new"] == 0
    assert second["sources_skipped"] == 1
    with ws.open_catalog() as cat:
        assert cat.count("pages") == first["pages"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/ingest.py`:

```python
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
    if limit:
        pdfs = pdfs[:limit]
    with ws.open_catalog() as cat:
        cat.add_run(dict(run_id="run0", engine="embedded", engine_version=None,
                         params_json=json.dumps({"note": "scanner-embedded OCR layer"}),
                         recipe=None, created_at=_now()))
        for pdf in pdfs:
            try:
                _ingest_pdf(ws, cat, pdf, stats)
            except Exception as e:  # keep batch going; record the failure
                stats["errors"].append(f"{pdf}: {e}")
    return stats


def _ingest_pdf(ws: Workspace, cat, pdf: Path, stats: dict) -> None:
    source_id = sha256_file(pdf)
    issue_label = pdf.parent.name
    if cat.get_source(source_id):
        stats["sources_skipped"] += 1
        return

    dest = ws.originals_dir / issue_label / pdf.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(pdf, dest)

    n = pdf_page_count(dest)
    cat.upsert_source(dict(
        source_id=source_id, rel_path=str(dest.relative_to(ws.root)),
        original_path=str(pdf), issue_label=issue_label, file_size=pdf.stat().st_size,
        page_count=n, has_embedded_ocr=int(pdf_has_text(dest)), ingested_at=_now()))

    prefix = source_id[:6]
    for idx in range(1, n + 1):
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
            (ws.root / txt_rel).write_text(text, encoding="utf-8")
            cat.add_run_page(dict(run_id="run0", page_id=page_id, text_path=txt_rel,
                                  char_count=len(text), confidence=None))
            stats["pages"] += 1
    stats["sources_new"] += 1
```

`src/corpus_tools/__main__.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="corpus_tools")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace")
    p.add_argument("workspace", type=Path)
    p.add_argument("--name", required=True)

    p = sub.add_parser("ingest", help="ingest a folder of source PDFs")
    p.add_argument("source", type=Path)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None, help="max PDFs (for smoke tests)")

    args = ap.parse_args()
    if args.cmd == "init":
        from .workspace import init_workspace
        ws = init_workspace(args.workspace, args.name)
        print(f"workspace ready at {ws.root}")
    elif args.cmd == "ingest":
        from .ingest import ingest_folder
        from .workspace import load_workspace
        ws = load_workspace(args.workspace)
        stats = ingest_folder(ws, args.source, limit=args.limit)
        print(f"new sources: {stats['sources_new']}  skipped: {stats['sources_skipped']}  "
              f"pages: {stats['pages']}  errors: {len(stats['errors'])}")
        for e in stats["errors"]:
            print("ERROR:", e)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest.py -v`
Expected: 3 PASS (tens of seconds — real image decode/encode).

- [ ] **Step 5: CLI smoke test**

Run: `python -m corpus_tools init workspace --name kexue-wenyi` then
`python -m corpus_tools ingest "incoming\sf magazines 2025" --workspace workspace --limit 2`
Expected: prints `new sources: 2 ... errors: 0`; `workspace\pages\` contains PNGs with `L`/`R` (or `F`) suffixes; `workspace\ocr\runs\run0\` contains matching `.txt` files with Chinese text.

- [ ] **Step 6: Commit**

```
git add src/corpus_tools/ingest.py src/corpus_tools/__main__.py tests/test_ingest.py
git commit -m "feat: idempotent folder ingest with CLI"
```

---

### Task 9: Assessment metrics

**Files:**
- Create: `src/corpus_tools/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**
- Produces:
  - `measure_page(gray: np.ndarray) -> dict` — keys `skew_deg, contrast, background_gray, ink_density, noise` (all float).
  - `estimate_skew(gray: np.ndarray) -> float` — degrees, positive = counterclockwise, range ±3°.
  - `detect_script(text: str) -> str` — `"simplified" | "traditional" | "unknown"`.
  - `garbage_ratio(text: str) -> float` — fraction of non-whitespace chars outside CJK/ASCII/CJK-punctuation ranges.
  - `quality_score(fields: dict) -> float` — 0..1, higher is better; combines contrast, noise, |skew|, garbage_ratio.

- [ ] **Step 1: Write the failing tests**

`tests/test_assess.py`:

```python
import numpy as np
import pytest
from PIL import Image, ImageDraw

from corpus_tools.assess import (detect_script, estimate_skew, garbage_ratio,
                                 measure_page, quality_score)


def make_text_page(angle: float = 0.0) -> np.ndarray:
    """Bright page with dark horizontal text-like bars, optionally rotated."""
    im = Image.new("L", (1200, 1600), 235)
    d = ImageDraw.Draw(im)
    for y in range(150, 1450, 40):
        d.rectangle([100, y, 1100, y + 14], fill=25)
    if angle:
        im = im.rotate(angle, fillcolor=235, resample=Image.BILINEAR)
    return np.array(im)


@pytest.mark.parametrize("angle", [0.0, 1.5, -2.0])
def test_estimate_skew(angle):
    est = estimate_skew(make_text_page(angle))
    assert abs(est - angle) <= 0.3


def test_measure_page_fields():
    m = measure_page(make_text_page())
    assert set(m) == {"skew_deg", "contrast", "background_gray", "ink_density", "noise"}
    assert m["background_gray"] > 200
    assert 0.05 < m["ink_density"] < 0.6
    assert m["contrast"] > 150


def test_detect_script():
    assert detect_script("这是一个关于科学的故事，我们的时代会发展。") == "simplified"
    assert detect_script("這是一個關於科學的故事，我們的時代會發展。") == "traditional"
    assert detect_script("山中有水。") == "unknown"
    assert detect_script("") == "unknown"


def test_garbage_ratio():
    assert garbage_ratio("这是干净的中文。") == 0.0
    assert garbage_ratio("abc 123 中文") == 0.0
    r = garbage_ratio("中文θρ¤∶≡中文")   # 5 garbage of 9 non-space chars ≈ 0.56
    assert 0.4 < r < 0.6


def test_quality_score_orders_pages():
    good = quality_score(dict(contrast=180, noise=2.0, skew_deg=0.2, garbage_ratio=0.02))
    bad = quality_score(dict(contrast=60, noise=12.0, skew_deg=2.5, garbage_ratio=0.30))
    assert 0.0 <= bad < good <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_assess.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/assess.py`:

```python
from __future__ import annotations

import cv2
import numpy as np

# Characters that exist only in one script (common in 1980s magazine prose).
_SIMP = set("国发对说们时会学过还进动书长门问题体万与义乐传报讯电见观现连线")
_TRAD = set("國發對說們時會學過還進動書長門問題體萬與義樂傳報訊電見觀現連線")

_CJK_OK = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF),          # unified ideographs
    (0x3000, 0x303F), (0xFF00, 0xFFEF),          # CJK punct, full-width forms
    (0x2018, 0x201D), (0x2026, 0x2026),          # quotes, ellipsis
)


def estimate_skew(gray: np.ndarray) -> float:
    scale = 1000 / gray.shape[1]
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = ink.shape
    best_angle, best_score = 0.0, -1.0
    for ang in np.arange(-3.0, 3.01, 0.25):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h))
        prof = rot.sum(axis=1).astype(np.float64)
        score = float(((prof[1:] - prof[:-1]) ** 2).sum())
        if score > best_score:
            best_score, best_angle = score, float(ang)
    # best_angle is the correction that sharpens row profiles; the page's own
    # skew is its negation (positive = content rotated counterclockwise).
    return -best_angle


def measure_page(gray: np.ndarray) -> dict:
    p5, p95 = np.percentile(gray, [5, 95])
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink_mask = gray < otsu
    background = float(np.median(gray[~ink_mask])) if (~ink_mask).any() else float(p95)
    denoised = cv2.medianBlur(gray, 3)
    noise = float((gray.astype(np.int16) - denoised.astype(np.int16)).std())
    return {
        "skew_deg": estimate_skew(gray),
        "contrast": float(p95 - p5),
        "background_gray": background,
        "ink_density": float(ink_mask.mean()),
        "noise": noise,
    }


def detect_script(text: str) -> str:
    s = sum(c in _SIMP for c in text)
    t = sum(c in _TRAD for c in text)
    if s >= 3 and s > 2 * t:
        return "simplified"
    if t >= 3 and t > 2 * s:
        return "traditional"
    return "unknown"


def garbage_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    def ok(c: str) -> bool:
        o = ord(c)
        if o < 128:
            return True
        return any(lo <= o <= hi for lo, hi in _CJK_OK)
    return sum(not ok(c) for c in chars) / len(chars)


def quality_score(fields: dict) -> float:
    contrast = min(fields["contrast"] / 180.0, 1.0)
    noise = 1.0 - min(fields["noise"] / 15.0, 1.0)
    skew = 1.0 - min(abs(fields["skew_deg"]) / 3.0, 1.0)
    clean = 1.0 - min(fields["garbage_ratio"] / 0.3, 1.0)
    return round(0.35 * contrast + 0.2 * noise + 0.15 * skew + 0.3 * clean, 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_assess.py -v`
Expected: 7 PASS (3 skew parametrizations + 4 others).

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/assess.py tests/test_assess.py
git commit -m "feat: page quality metrics, script detection, quality score"
```

---

### Task 10: Assess orchestration + CLI subcommand

**Files:**
- Create: `src/corpus_tools/assess_run.py`
- Modify: `src/corpus_tools/__main__.py` (add `assess` subcommand)
- Test: `tests/test_assess_run.py`

**Interfaces:**
- Consumes: workspace/catalog (Tasks 2–3), metrics (Task 9), ingested pages (Task 8).
- Produces: `assess_workspace(ws: Workspace, limit: int | None = None, force: bool = False) -> dict` — for each page row with `assessed_at IS NULL` (all pages when `force`): load its PNG as grayscale, `measure_page`, read run-0 text for `detect_script`/`garbage_ratio`, compute `quality_score`, `update_page` with all fields + `assessed_at`. Returns `{"assessed": int, "skipped": int, "errors": [...]}`. CLI: `python -m corpus_tools assess --workspace <ws> [--limit N] [--force]`.

- [ ] **Step 1: Write the failing test**

`tests/test_assess_run.py`:

```python
import shutil

from corpus_tools.assess_run import assess_workspace
from corpus_tools.ingest import ingest_folder
from corpus_tools.workspace import init_workspace


def test_assess_fills_metrics_and_is_resumable(tmp_path, sample_pdf):
    src = tmp_path / "in" / "kexue wenyi 1980.5"
    src.mkdir(parents=True)
    shutil.copy(sample_pdf, src / "0838_043.pdf")
    ws = init_workspace(tmp_path / "ws", "test")
    ingest_folder(ws, tmp_path / "in")

    stats = assess_workspace(ws, limit=2)
    assert stats["assessed"] == 2 and not stats["errors"]
    with ws.open_catalog() as cat:
        done = cat.iter_pages("assessed_at IS NOT NULL")
        assert len(done) == 2
        p = done[0]
        assert p["quality_score"] is not None
        assert p["contrast"] is not None and p["background_gray"] is not None
        assert p["script"] in ("simplified", "traditional", "unknown")

    again = assess_workspace(ws, limit=2)
    assert again["assessed"] == 2  # next two pages, resume not repeat
    with ws.open_catalog() as cat:
        assert len(cat.iter_pages("assessed_at IS NOT NULL")) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_assess_run.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/assess_run.py`:

```python
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
```

Add to `src/corpus_tools/__main__.py`, after the `ingest` parser block:

```python
    p = sub.add_parser("assess", help="measure page quality metrics")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="re-assess already-assessed pages")
```

and after the `ingest` dispatch block:

```python
    elif args.cmd == "assess":
        from .assess_run import assess_workspace
        from .workspace import load_workspace
        ws = load_workspace(args.workspace)
        stats = assess_workspace(ws, limit=args.limit, force=args.force)
        print(f"assessed: {stats['assessed']}  errors: {len(stats['errors'])}")
        for e in stats["errors"]:
            print("ERROR:", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_assess_run.py -v`
Expected: PASS (skew search on real pages takes a few seconds each).

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/assess_run.py src/corpus_tools/__main__.py tests/test_assess_run.py
git commit -m "feat: resumable workspace assessment with CLI"
```

---

### Task 11: Assessment HTML report

**Files:**
- Create: `src/corpus_tools/report.py`
- Modify: `src/corpus_tools/__main__.py` (add `report` subcommand)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: assessed catalog (Task 10).
- Produces: `write_assess_report(ws: Workspace) -> Path` — writes `reports/assess_report.html` (self-contained: inline CSS, no external assets; thumbnails written to `reports/thumbs/` and referenced relatively). Report contains: corpus summary counts (sources, pages, assessed), per-metric distribution tables (10-bucket histograms rendered as HTML bars), script breakdown, and thumbnail galleries of the 12 lowest- and 12 highest-quality pages with their metric values. CLI: `python -m corpus_tools report --workspace <ws>`.

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:

```python
import shutil

from corpus_tools.assess_run import assess_workspace
from corpus_tools.ingest import ingest_folder
from corpus_tools.report import write_assess_report
from corpus_tools.workspace import init_workspace


def test_report_written(tmp_path, sample_pdf):
    src = tmp_path / "in" / "kexue wenyi 1980.5"
    src.mkdir(parents=True)
    shutil.copy(sample_pdf, src / "0838_043.pdf")
    ws = init_workspace(tmp_path / "ws", "test")
    ingest_folder(ws, tmp_path / "in")
    assess_workspace(ws, limit=3)

    out = write_assess_report(ws)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "quality_score" in html and "sources" in html
    assert list((ws.reports_dir / "thumbs").glob("*.jpg"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

`src/corpus_tools/report.py`:

```python
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
```

Add to `src/corpus_tools/__main__.py` — parser:

```python
    p = sub.add_parser("report", help="write assessment HTML report")
    p.add_argument("--workspace", type=Path, required=True)
```

dispatch:

```python
    elif args.cmd == "report":
        from .report import write_assess_report
        from .workspace import load_workspace
        out = write_assess_report(load_workspace(args.workspace))
        print(f"report: {out}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add src/corpus_tools/report.py src/corpus_tools/__main__.py tests/test_report.py
git commit -m "feat: self-contained assessment HTML report"
```

---

### Task 12: Skills + end-to-end smoke on one real issue

**Files:**
- Create: `.claude/skills/corpus-ingest/SKILL.md`
- Create: `.claude/skills/corpus-assess/SKILL.md`

**Interfaces:**
- Consumes: the CLI (`python -m corpus_tools init|ingest|assess|report`).
- Produces: user-invocable skills; a verified end-to-end run on one real issue folder.

- [ ] **Step 1: Write the ingest skill**

`.claude/skills/corpus-ingest/SKILL.md`:

```markdown
---
name: corpus-ingest
description: Ingest scanned source PDFs into a corpus workspace — checksums, spread splitting, page images, embedded OCR as run 0. Use when the user wants to add new scanned PDFs to the corpus or create a new workspace.
---

# Corpus Ingest

Ingest source PDFs into a workspace. All logic lives in `corpus_tools`; this skill orchestrates the CLI and verifies results.

## Steps

1. If no workspace exists yet: `python -m corpus_tools init <workspace-path> --name <corpus-name>`
2. Confirm the source folder with the user, then run (background for large batches; ~10–20 s per PDF on this CPU):
   `python -m corpus_tools ingest "<source-folder>" --workspace <workspace-path>`
3. Verify, and report to the user:
   - stats line printed by the CLI (`new sources / skipped / pages / errors`)
   - every error line, verbatim — never summarize errors away
   - sanity check in SQLite: `python -c "import sqlite3; c=sqlite3.connect(r'<ws>/catalog.db'); print(c.execute('SELECT COUNT(*) FROM sources').fetchone(), c.execute('SELECT side, COUNT(*) FROM pages GROUP BY side').fetchall())"`
   - expected shape: most pages are L/R pairs; a small number of F pages (covers/foldouts) is normal. A large F count suggests gutter detection is failing — open 2–3 F page PNGs and inspect before proceeding.
4. Re-running on the same folder is safe (checksummed sources are skipped).

## Rules

- Never modify or delete anything in the source folder or `originals/`.
- If a PDF errors, ingest continues; collect the errors and report them — do not retry blindly.
```

- [ ] **Step 2: Write the assess skill**

`.claude/skills/corpus-assess/SKILL.md`:

```markdown
---
name: corpus-assess
description: Measure per-page quality (skew, contrast, noise, script, garbage ratio, quality score) for ingested corpus pages and generate the HTML assessment report. Use after corpus-ingest, or when the user asks about scan/OCR quality.
---

# Corpus Assess

Assessment is resumable: only unassessed pages are processed; `--force` re-does everything.

## Steps

1. Run (background; roughly 1–3 s per page on this CPU — a full 3,600-page corpus is an hours-long job):
   `python -m corpus_tools assess --workspace <workspace-path>`
   For a quick look, use `--limit 200` first.
2. Generate the report: `python -m corpus_tools report --workspace <workspace-path>`
3. Open `reports/assess_report.html`, and summarize for the user:
   - quality_score distribution shape (uniform? bimodal? long tail?)
   - script breakdown (this corpus should be overwhelmingly simplified; a large 'unknown' share usually means empty/garbled run-0 text, not traditional script)
   - anything alarming in the lowest-quality gallery (blank pages, failed splits, upside-down scans)
4. Report errors verbatim.

## Rules

- Assessment writes only to the catalog and `reports/` — if anything tries to modify `pages/` or `originals/`, stop.
```

- [ ] **Step 3: End-to-end smoke on one real issue**

Run:
```
python -m corpus_tools init workspace --name kexue-wenyi
python -m corpus_tools ingest "incoming\sf magazines 2025\kexue wenyi 1979.1" --workspace workspace
python -m corpus_tools assess --workspace workspace
python -m corpus_tools report --workspace workspace
```
Expected: ~4–6 sources, ~60–100 pages, 0 errors; report exists. Open `workspace\reports\assess_report.html` and visually verify: thumbnails are single magazine pages (not spreads, not slivers), and run-0 text files contain Chinese.

- [ ] **Step 4: Full test suite**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```
git add .claude/skills
git commit -m "feat: corpus-ingest and corpus-assess skills; phase 1 complete"
```

---

## Verification checklist (whole phase)

- [ ] `pytest -v` — all green.
- [ ] One real issue ingested + assessed + reported with 0 errors.
- [ ] Spot-check 5 random page PNGs: correctly split, no scanner background.
- [ ] Spot-check 3 run-0 `.txt` files against their page images: text corresponds to the correct half of the spread.
- [ ] Re-run ingest on the same folder: `new sources: 0`, page count unchanged.
- [ ] `catalog_audit.log` is valid JSONL and grew during all of the above.
