# Phase 2: Ground-Truth Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `corpus-evaluate` tooling: stratified ground-truth sample selection, transcription scaffolding/status tracking, character-error-rate (CER) measurement of OCR runs against ground truth, and a baseline evaluation report.

**Architecture:** Four new `corpus_tools` modules (`metrics`, `sampling`, `gt`, `evaluate`) plus a report writer, all reading/writing state through the existing SQLite `Catalog`. Two new tables: `gt_pages` (sample membership + transcription status) and reuse of the existing `evaluations` table via new write methods. A thin `corpus-evaluate` skill orchestrates the CLI subcommands.

**Tech Stack:** Python 3.10+, stdlib only for the new logic (sqlite3, random, statistics, html). Reuses existing `Workspace`, `Catalog`, and `report._histogram_rows`.

## Global Constraints

- Python ≥ 3.10 (existing code uses `X | None` unions).
- **No new dependencies** — new modules are stdlib-only (existing deps pypdf/Pillow/numpy/yaml remain available).
- Every catalog mutation goes through `Catalog._write` so it lands in the audit log.
- Ground-truth files follow `docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`: final files at `ground_truth/<page-id>.txt`, UTF-8, printed line breaks preserved, `□` (U+25A1) for illegible characters.
- CER is computed on **whitespace-stripped** character streams (line breaks are layout, not content): `cer = levenshtein(ref, hyp) / len(ref)` after removing all whitespace from both.
- Sampling must be deterministic given a seed (default `seed=1979`).
- All new CLI subcommands exit `1` when the stats dict contains errors (matches existing `ingest`/`assess` behavior).
- Tests live in `tests/`, run with `python -m pytest -q`; all 46 existing tests must stay green.

**Operational note (not a task):** only one chunk (`ca4071`, 99 pages, issue 1979.1) is ingested so far. The tooling is built and tested against that, but the *real* ground-truth sample should be drawn only after the full corpus ingest, so strata cover all issues. Sampling is cheap and re-runnable; `gt-sample` only ever *adds* pages, so an early trial sample stays valid.

---

### Task 1: Catalog support — `gt_pages` table + evaluation writes

**Files:**
- Modify: `src/corpus_tools/catalog.py`
- Test: `tests/test_catalog.py` (append)

**Interfaces:**
- Consumes: existing `Catalog` class.
- Produces:
  - New table `gt_pages(page_id TEXT PK, stratum TEXT, status TEXT NOT NULL DEFAULT 'selected', selected_at TEXT NOT NULL, completed_at TEXT)`. `status` is `'selected'` or `'done'`.
  - `Catalog.upsert_gt_page(g: dict) -> None` — keys: `page_id, stratum, status, selected_at, completed_at`.
  - `Catalog.get_gt_page(page_id: str) -> dict | None`
  - `Catalog.iter_gt_pages(status: str | None = None) -> list[dict]` — ordered by `page_id`.
  - `Catalog.add_evaluation(ev: dict) -> None` — keys: `run_id, page_id, metric, value, details_json, created_at`; INSERT OR REPLACE (re-evaluation after a GT fix must overwrite).
  - `Catalog.get_evaluation(run_id, page_id, metric) -> dict | None`
  - `Catalog.count("gt_pages")` allowed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog.py`:

```python
def _mk_cat(tmp_path):
    from corpus_tools.catalog import Catalog
    cat = Catalog(tmp_path / "cat.db")
    cat.init_schema()
    return cat


def test_gt_page_roundtrip(tmp_path):
    cat = _mk_cat(tmp_path)
    cat.upsert_gt_page({"page_id": "ab-p001L", "stratum": "1979.1|simplified|mid",
                        "status": "selected", "selected_at": "2026-07-13T10:00:00",
                        "completed_at": None})
    g = cat.get_gt_page("ab-p001L")
    assert g["status"] == "selected" and g["stratum"] == "1979.1|simplified|mid"
    # upsert updates status without duplicating
    cat.upsert_gt_page({"page_id": "ab-p001L", "stratum": "1979.1|simplified|mid",
                        "status": "done", "selected_at": "2026-07-13T10:00:00",
                        "completed_at": "2026-07-13T12:00:00"})
    assert cat.count("gt_pages") == 1
    assert cat.get_gt_page("ab-p001L")["status"] == "done"


def test_iter_gt_pages_filter(tmp_path):
    cat = _mk_cat(tmp_path)
    for pid, st in [("ab-p001L", "selected"), ("ab-p002R", "done")]:
        cat.upsert_gt_page({"page_id": pid, "stratum": "s", "status": st,
                            "selected_at": "t", "completed_at": None})
    assert [g["page_id"] for g in cat.iter_gt_pages()] == ["ab-p001L", "ab-p002R"]
    assert [g["page_id"] for g in cat.iter_gt_pages(status="done")] == ["ab-p002R"]


def test_evaluation_upsert(tmp_path):
    cat = _mk_cat(tmp_path)
    ev = {"run_id": "run0", "page_id": "ab-p001L", "metric": "cer",
          "value": 0.31, "details_json": "{}", "created_at": "t1"}
    cat.add_evaluation(ev)
    cat.add_evaluation(dict(ev, value=0.12, created_at="t2"))
    got = cat.get_evaluation("run0", "ab-p001L", "cer")
    assert got["value"] == 0.12
    assert cat.count("evaluations") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_catalog.py -q`
Expected: 3 new tests FAIL (`gt_pages` table missing / `AttributeError: upsert_gt_page`).

- [ ] **Step 3: Implement**

In `src/corpus_tools/catalog.py`, append to `SCHEMA` (before the index line):

```sql
CREATE TABLE IF NOT EXISTS gt_pages (
    page_id TEXT PRIMARY KEY REFERENCES pages(page_id),
    stratum TEXT,
    status TEXT NOT NULL DEFAULT 'selected',
    selected_at TEXT NOT NULL,
    completed_at TEXT
);
```

Add `"gt_pages"` to the allowed set in `Catalog.count`. Add methods to `Catalog`:

```python
    def upsert_gt_page(self, g: dict) -> None:
        self._write("upsert_gt_page", """
            INSERT INTO gt_pages (page_id, stratum, status, selected_at, completed_at)
            VALUES (:page_id, :stratum, :status, :selected_at, :completed_at)
            ON CONFLICT(page_id) DO UPDATE SET
                status=excluded.status, completed_at=excluded.completed_at
        """, g)

    def get_gt_page(self, page_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM gt_pages WHERE page_id = ?",
                                (page_id,)).fetchone()
        return dict(row) if row else None

    def iter_gt_pages(self, status: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM gt_pages", ()
        if status:
            sql, params = sql + " WHERE status = ?", (status,)
        sql += " ORDER BY page_id"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def add_evaluation(self, ev: dict) -> None:
        self._write("add_evaluation", """
            INSERT OR REPLACE INTO evaluations
                (run_id, page_id, metric, value, details_json, created_at)
            VALUES (:run_id, :page_id, :metric, :value, :details_json, :created_at)
        """, ev)

    def get_evaluation(self, run_id: str, page_id: str, metric: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM evaluations WHERE run_id = ? AND page_id = ? AND metric = ?",
            (run_id, page_id, metric)).fetchone()
        return dict(row) if row else None
```

**Existing-workspace note:** `init_schema()` is `CREATE TABLE IF NOT EXISTS`, so re-running it on the live `workspace/catalog.db` adds `gt_pages` without touching data. The new code paths (Task 4/5) call `cat.init_schema()` first for exactly this reason.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_catalog.py -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/catalog.py tests/test_catalog.py
git commit -m "feat: catalog support for ground-truth sample tracking and evaluations"
```

---

### Task 2: CER metric (`metrics.py`)

**Files:**
- Create: `src/corpus_tools/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces:
  - `strip_layout(text: str) -> str` — removes **all** whitespace (`"".join(text.split())`).
  - `cer(ref: str, hyp: str) -> dict` — keys `cer` (float), `distance`, `sub`, `dele`, `ins`, `ref_chars` (ints). Raises `ValueError` if the stripped reference is empty. Levenshtein with unit costs; counts come from a rolling-row DP (no full matrix).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:

```python
import pytest

from corpus_tools.metrics import cer, strip_layout


def test_strip_layout_removes_all_whitespace():
    assert strip_layout("科学\n文艺 abc\t1") == "科学文艺abc1"


def test_cer_identical_is_zero():
    r = cer("科学文艺", "科学\n文艺")  # layout differences don't count
    assert r["cer"] == 0.0 and r["distance"] == 0 and r["ref_chars"] == 4


def test_cer_substitution():
    r = cer("科学文艺", "科字文艺")
    assert r == {"cer": 0.25, "distance": 1, "sub": 1, "dele": 0,
                 "ins": 0, "ref_chars": 4}


def test_cer_deletion_and_insertion():
    assert cer("科学文艺", "科文艺")["dele"] == 1      # hyp missing one ref char
    assert cer("科文艺", "科学文艺")["ins"] == 1       # hyp has one extra char


def test_cer_empty_hyp_is_one():
    r = cer("科学文艺", "")
    assert r["cer"] == 1.0 and r["dele"] == 4


def test_cer_empty_ref_raises():
    with pytest.raises(ValueError):
        cer("  \n ", "科学")


def test_cer_counts_sum_to_distance():
    r = cer("中国科学文艺一九七九", "中國科学芸一九七九年")
    assert r["sub"] + r["dele"] + r["ins"] == r["distance"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_tools.metrics`.

- [ ] **Step 3: Implement**

Create `src/corpus_tools/metrics.py`:

```python
from __future__ import annotations


def strip_layout(text: str) -> str:
    """Remove all whitespace: line breaks and spacing are layout, not content."""
    return "".join(text.split())


def cer(ref: str, hyp: str) -> dict:
    """Character error rate of hyp against ref, whitespace-insensitive.

    Returns cer, distance, and substitution/deletion/insertion counts.
    Deletion = ref char missing from hyp; insertion = extra char in hyp.
    """
    r, h = strip_layout(ref), strip_layout(hyp)
    if not r:
        raise ValueError("empty reference text")
    n = len(h)
    # rolling rows: distance plus S/D/I counts along the optimal path
    dist = list(range(n + 1))
    sub = [0] * (n + 1)
    dele = [0] * (n + 1)
    ins = list(range(n + 1))
    for i in range(1, len(r) + 1):
        pdist, psub, pdele, pins = dist, sub, dele, ins
        dist = [i] + [0] * n
        sub = [0] * (n + 1)
        dele = [i] + [0] * n
        ins = [0] * (n + 1)
        rc = r[i - 1]
        for j in range(1, n + 1):
            if rc == h[j - 1]:
                dist[j], sub[j], dele[j], ins[j] = (
                    pdist[j - 1], psub[j - 1], pdele[j - 1], pins[j - 1])
                continue
            a, b, c = pdist[j - 1], pdist[j], dist[j - 1]
            if a <= b and a <= c:            # substitution
                dist[j] = a + 1
                sub[j], dele[j], ins[j] = psub[j - 1] + 1, pdele[j - 1], pins[j - 1]
            elif b <= c:                     # deletion (ref char dropped)
                dist[j] = b + 1
                sub[j], dele[j], ins[j] = psub[j], pdele[j] + 1, pins[j]
            else:                            # insertion (extra hyp char)
                dist[j] = c + 1
                sub[j], dele[j], ins[j] = sub[j - 1], dele[j - 1], ins[j - 1] + 1
    return {"cer": dist[n] / len(r), "distance": dist[n], "sub": sub[n],
            "dele": dele[n], "ins": ins[n], "ref_chars": len(r)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -q` — Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/metrics.py tests/test_metrics.py
git commit -m "feat: whitespace-insensitive CER metric with edit-op counts"
```

---

### Task 3: Stratified sampling (`sampling.py`)

**Files:**
- Create: `src/corpus_tools/sampling.py`
- Test: `tests/test_sampling.py`

**Interfaces:**
- Consumes: page dicts as returned by `Catalog.iter_pages` (keys used: `page_id`, `issue_label`, `source_id`, `script`, `quality_score`).
- Produces:
  - `quality_band(q: float) -> str` — `"low"` (< 0.5), `"mid"` (0.5–0.75), `"high"` (≥ 0.75).
  - `stratum(page: dict) -> str` — `"<issue_label or source_id[:6]>|<script or 'unknown'>|<band>"`.
  - `stratified_sample(pages: list[dict], n: int = 40, seed: int = 1979) -> list[dict]` — deterministic; proportional allocation with ≥1 per stratum (largest strata win when strata outnumber n); each returned dict is the page dict plus a `"stratum"` key; sorted by `page_id`. Pages with `quality_score is None` are excluded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sampling.py`:

```python
from corpus_tools.sampling import quality_band, stratified_sample, stratum


def _page(pid, q, script="simplified", issue="1979.1"):
    return {"page_id": pid, "quality_score": q, "script": script,
            "issue_label": issue, "source_id": "ca4071deadbeef"}


def test_quality_band_edges():
    assert quality_band(0.49) == "low"
    assert quality_band(0.5) == "mid"
    assert quality_band(0.75) == "high"


def test_stratum_label():
    assert stratum(_page("a-p1L", 0.9)) == "1979.1|simplified|high"
    assert stratum(_page("a-p1L", 0.9, script=None, issue=None)) == "ca4071|unknown|high"


def test_sample_is_deterministic_and_sized():
    pages = [_page(f"a-p{i:03d}L", 0.2 + 0.007 * i) for i in range(100)]
    s1 = stratified_sample(pages, n=10, seed=42)
    s2 = stratified_sample(pages, n=10, seed=42)
    assert [p["page_id"] for p in s1] == [p["page_id"] for p in s2]
    assert len(s1) == 10
    assert all("stratum" in p for p in s1)


def test_sample_covers_every_stratum():
    pages = ([_page(f"a-p{i:03d}L", 0.3) for i in range(50)]
             + [_page(f"b-p{i:03d}L", 0.9, script="traditional") for i in range(3)])
    chosen = stratified_sample(pages, n=10, seed=1)
    assert any(p["stratum"].startswith("1979.1|traditional") for p in chosen)


def test_sample_skips_unassessed_and_caps_at_population():
    pages = [_page("a-p001L", 0.6), _page("a-p002L", None)]
    chosen = stratified_sample(pages, n=40, seed=1)
    assert [p["page_id"] for p in chosen] == ["a-p001L"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sampling.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_tools.sampling`.

- [ ] **Step 3: Implement**

Create `src/corpus_tools/sampling.py`:

```python
from __future__ import annotations

import random


def quality_band(q: float) -> str:
    if q < 0.5:
        return "low"
    if q < 0.75:
        return "mid"
    return "high"


def stratum(page: dict) -> str:
    issue = page.get("issue_label") or (page.get("source_id") or "")[:6]
    script = page.get("script") or "unknown"
    return f"{issue}|{script}|{quality_band(page['quality_score'])}"


def stratified_sample(pages: list[dict], n: int = 40, seed: int = 1979) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for p in pages:
        if p.get("quality_score") is None:
            continue
        groups.setdefault(stratum(p), []).append(p)
    if not groups:
        return []
    names = sorted(groups)
    total = sum(len(groups[s]) for s in names)
    n = min(n, total)

    # one slot per stratum (largest strata first when strata outnumber n),
    # then fill remaining slots proportionally to stratum size
    alloc = dict.fromkeys(names, 0)
    for s in sorted(names, key=lambda s: (-len(groups[s]), s))[:n]:
        alloc[s] = 1
    while sum(alloc.values()) < n:
        s = max((s for s in names if alloc[s] < len(groups[s])),
                key=lambda s: (len(groups[s]) / (alloc[s] + 1), s))
        alloc[s] += 1

    rng = random.Random(seed)
    out: list[dict] = []
    for s in names:
        pool = sorted(groups[s], key=lambda p: p["page_id"])
        out.extend(dict(p, stratum=s) for p in rng.sample(pool, alloc[s]))
    return sorted(out, key=lambda p: p["page_id"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sampling.py -q` — Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/sampling.py tests/test_sampling.py
git commit -m "feat: deterministic stratified sampling for ground-truth selection"
```

---

### Task 4: Ground-truth scaffolding and status sync (`gt.py`)

**Files:**
- Create: `src/corpus_tools/gt.py`
- Modify: `src/corpus_tools/workspace.py` (add `ground_truth_dir` / `gt_drafts_dir` properties)
- Test: `tests/test_gt.py`

**Interfaces:**
- Consumes: `Workspace`; `Catalog.upsert_gt_page` / `iter_gt_pages` / `get_gt_page` / `get_run_page` (Task 1); `stratified_sample` (Task 3).
- Produces:
  - `Workspace.ground_truth_dir -> Path` (`root / "ground_truth"`), `Workspace.gt_drafts_dir -> Path` (`root / "ground_truth" / "drafts"`).
  - `scaffold_sample(ws: Workspace, n: int = 40, seed: int = 1979) -> dict` — selects pages, records them in `gt_pages` (status `selected`), writes draft `ground_truth/drafts/<page-id>.txt` seeded with run-0 text plus a notes template `<page-id>.notes.md`. **Additive**: already-selected pages and existing draft files are never overwritten. Returns `{"selected": int, "already": int, "drafts_written": int}`.
  - `sync_gt_status(ws: Workspace) -> dict` — marks `gt_pages` rows `done` when a non-empty final `ground_truth/<page-id>.txt` exists (sets `completed_at` once); also adopts final files never sampled (inserts as `done`, stratum `None`). Returns `{"selected": int, "done": int, "adopted": int}`.

**Human workflow this supports:** correct the draft against the page image, then save the finished transcription as `ground_truth/<page-id>.txt` (drafts stay put as provenance). `sync_gt_status` picks up completions.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gt.py`:

```python
from corpus_tools.gt import scaffold_sample, sync_gt_status
from corpus_tools.workspace import init_workspace


def _ws_with_pages(tmp_path, n_pages=6):
    ws = init_workspace(tmp_path / "ws", "t")
    run_dir = ws.run_dir("run0")
    run_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        cat.add_run({"run_id": "run0", "engine": "embedded", "engine_version": None,
                     "params_json": "{}", "recipe": None, "created_at": "t"})
        for i in range(1, n_pages + 1):
            pid = f"ab1234-p{i:03d}L"
            cat.add_page({"page_id": pid, "source_id": "ab1234ffff",
                          "pdf_page_index": i, "side": "L",
                          "image_path": f"pages/{pid}.png",
                          "width_px": 100, "height_px": 150})
            cat.update_page(pid, {"quality_score": 0.3 + 0.1 * i,
                                  "script": "simplified",
                                  "issue_label": "1979.1",
                                  "assessed_at": "t"})
            txt = run_dir / f"{pid}.txt"
            txt.write_text(f"run0 text {i}", encoding="utf-8")
            cat.add_run_page({"run_id": "run0", "page_id": pid,
                              "text_path": f"ocr/runs/run0/{pid}.txt",
                              "char_count": 10, "confidence": None})
    return ws


def test_scaffold_writes_drafts_and_catalog_rows(tmp_path):
    ws = _ws_with_pages(tmp_path)
    stats = scaffold_sample(ws, n=3, seed=1)
    assert stats["selected"] == 3 and stats["drafts_written"] == 3
    with ws.open_catalog() as cat:
        rows = cat.iter_gt_pages(status="selected")
    assert len(rows) == 3
    pid = rows[0]["page_id"]
    draft = ws.gt_drafts_dir / f"{pid}.txt"
    assert draft.read_text(encoding="utf-8").startswith("run0 text")
    assert (ws.gt_drafts_dir / f"{pid}.notes.md").exists()


def test_scaffold_is_additive_and_preserves_edits(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=3, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.gt_drafts_dir / f"{pid}.txt").write_text("my edits", encoding="utf-8")
    stats = scaffold_sample(ws, n=3, seed=1)
    assert stats["selected"] == 0 and stats["already"] == 3
    assert (ws.gt_drafts_dir / f"{pid}.txt").read_text(encoding="utf-8") == "my edits"


def test_sync_marks_done_and_adopts(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=2, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.ground_truth_dir / f"{pid}.txt").write_text("最终文本", encoding="utf-8")
    # an ad-hoc final file for a page never sampled
    (ws.ground_truth_dir / "ab1234-p006L.txt").write_text("adopted", encoding="utf-8")
    stats = sync_gt_status(ws)
    assert stats["done"] == 2 and stats["adopted"] == 1
    with ws.open_catalog() as cat:
        assert cat.get_gt_page(pid)["status"] == "done"
        assert cat.get_gt_page(pid)["completed_at"]
        assert cat.get_gt_page("ab1234-p006L")["status"] == "done"


def test_sync_ignores_empty_final_files(tmp_path):
    ws = _ws_with_pages(tmp_path)
    scaffold_sample(ws, n=1, seed=1)
    with ws.open_catalog() as cat:
        pid = cat.iter_gt_pages()[0]["page_id"]
    (ws.ground_truth_dir / f"{pid}.txt").write_text("  \n", encoding="utf-8")
    stats = sync_gt_status(ws)
    assert stats["done"] == 0
```

Note: `test_sync_marks_done_and_adopts` expects `done == 2` because the adopted file also counts toward `done`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gt.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_tools.gt`.

- [ ] **Step 3: Implement**

Add to `src/corpus_tools/workspace.py` alongside the other properties:

```python
    @property
    def ground_truth_dir(self) -> Path:
        return self.root / "ground_truth"

    @property
    def gt_drafts_dir(self) -> Path:
        return self.root / "ground_truth" / "drafts"
```

Create `src/corpus_tools/gt.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gt.py -q` — Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/gt.py src/corpus_tools/workspace.py tests/test_gt.py
git commit -m "feat: ground-truth sample scaffolding and completion sync"
```

---

### Task 5: Run evaluation (`evaluate.py`)

**Files:**
- Create: `src/corpus_tools/evaluate.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `Workspace.ground_truth_dir` (Task 4), `Catalog.iter_gt_pages` / `get_run_page` / `add_evaluation` (Task 1), `metrics.cer` (Task 2).
- Produces: `evaluate_run(ws: Workspace, run_id: str) -> dict` — for every `gt_pages` row with status `done`, computes CER of the run's text against the final GT file and upserts an `evaluations` row (`metric="cer"`, `value=cer`, `details_json` = JSON of `{"distance","sub","dele","ins","ref_chars"}`). Returns `{"evaluated": int, "skipped": list[str], "errors": list[str]}`; `skipped` holds page-ids with no run text or an empty reference; `errors` holds `"<page-id>: <message>"` strings for unexpected failures.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evaluate.py`:

```python
import json

from corpus_tools.evaluate import evaluate_run
from corpus_tools.workspace import init_workspace


def _ws(tmp_path):
    ws = init_workspace(tmp_path / "ws", "t")
    run_dir = ws.run_dir("run0")
    run_dir.mkdir(parents=True, exist_ok=True)
    with ws.open_catalog() as cat:
        cat.add_run({"run_id": "run0", "engine": "embedded", "engine_version": None,
                     "params_json": "{}", "recipe": None, "created_at": "t"})
        for i, hyp in [(1, "科学文艺"), (2, "科字文艺"), (3, None)]:
            pid = f"ab1234-p{i:03d}L"
            cat.add_page({"page_id": pid, "source_id": "s", "pdf_page_index": i,
                          "side": "L", "image_path": None,
                          "width_px": 1, "height_px": 1})
            cat.upsert_gt_page({"page_id": pid, "stratum": None, "status": "done",
                                "selected_at": "t", "completed_at": "t"})
            (ws.ground_truth_dir / f"{pid}.txt").write_text("科学文艺", encoding="utf-8")
            if hyp is not None:
                (run_dir / f"{pid}.txt").write_text(hyp, encoding="utf-8")
                cat.add_run_page({"run_id": "run0", "page_id": pid,
                                  "text_path": f"ocr/runs/run0/{pid}.txt",
                                  "char_count": len(hyp), "confidence": None})
    return ws


def test_evaluate_run_records_cer(tmp_path):
    ws = _ws(tmp_path)
    stats = evaluate_run(ws, "run0")
    assert stats["evaluated"] == 2
    assert stats["skipped"] == ["ab1234-p003L"]  # no run text
    with ws.open_catalog() as cat:
        perfect = cat.get_evaluation("run0", "ab1234-p001L", "cer")
        onesub = cat.get_evaluation("run0", "ab1234-p002L", "cer")
    assert perfect["value"] == 0.0
    assert onesub["value"] == 0.25
    assert json.loads(onesub["details_json"])["sub"] == 1


def test_evaluate_run_is_rerunnable(tmp_path):
    ws = _ws(tmp_path)
    evaluate_run(ws, "run0")
    # fix the GT, re-evaluate: value must update, no duplicate rows
    (ws.ground_truth_dir / "ab1234-p002L.txt").write_text("科字文艺", encoding="utf-8")
    stats = evaluate_run(ws, "run0")
    assert stats["evaluated"] == 2
    with ws.open_catalog() as cat:
        assert cat.get_evaluation("run0", "ab1234-p002L", "cer")["value"] == 0.0
        assert cat.count("evaluations") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_evaluate.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_tools.evaluate`.

- [ ] **Step 3: Implement**

Create `src/corpus_tools/evaluate.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_evaluate.py -q` — Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/evaluate.py tests/test_evaluate.py
git commit -m "feat: CER evaluation of OCR runs against ground truth"
```

---

### Task 6: Evaluation report (`report_eval.py`)

**Files:**
- Create: `src/corpus_tools/report_eval.py`
- Test: `tests/test_report_eval.py`

**Interfaces:**
- Consumes: `report._histogram_rows` and `report._CSS` (existing), `Catalog` reads, evaluations from Task 5.
- Produces: `write_eval_report(ws: Workspace, run_id: str) -> Path` — writes `reports/eval_<run_id>.html` containing: summary (pages evaluated, median/mean/p90 CER), CER histogram, per-stratum median table, quality-score-vs-CER calibration (Pearson r + pair table), and a worst-first per-page table with image links (`../pages/...`) and S/D/I counts. Raises `ValueError` if the run has no evaluations.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_eval.py`:

```python
import pytest

from corpus_tools.evaluate import evaluate_run
from corpus_tools.report_eval import write_eval_report

# reuse the workspace builder from the evaluate tests
from test_evaluate import _ws


def test_eval_report_written(tmp_path):
    ws = _ws(tmp_path)
    evaluate_run(ws, "run0")
    out = write_eval_report(ws, "run0")
    html_text = out.read_text(encoding="utf-8")
    assert out.name == "eval_run0.html"
    assert "median CER" in html_text
    assert "ab1234-p002L" in html_text


def test_eval_report_no_evaluations_raises(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(ValueError):
        write_eval_report(ws, "nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_eval.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_tools.report_eval`.

- [ ] **Step 3: Implement**

Create `src/corpus_tools/report_eval.py`:

```python
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
```

Note the summary line must literally contain the substring `median CER` (the test asserts on it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_eval.py -q` — Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/corpus_tools/report_eval.py tests/test_report_eval.py
git commit -m "feat: evaluation HTML report with stratified CER and calibration"
```

---

### Task 7: CLI subcommands

**Files:**
- Modify: `src/corpus_tools/__main__.py`
- Test: `tests/test_main.py` (append)

**Interfaces:**
- Consumes: `scaffold_sample` / `sync_gt_status` (Task 4), `evaluate_run` (Task 5), `write_eval_report` (Task 6).
- Produces four subcommands, matching the existing style (lazy imports, `--workspace` required, exit 1 on errors):
  - `python -m corpus_tools gt-sample --workspace W [--n 40] [--seed 1979]`
  - `python -m corpus_tools gt-status --workspace W`
  - `python -m corpus_tools evaluate --workspace W --run RUN_ID`
  - `python -m corpus_tools eval-report --workspace W --run RUN_ID`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_gt_and_evaluate_cli(tmp_path, capsys):
    from test_evaluate import _ws
    from corpus_tools.__main__ import main

    ws = _ws(tmp_path)
    root = str(ws.root)

    assert main(["gt-status", "--workspace", root]) == 0
    out = capsys.readouterr().out
    assert "done: 3" in out

    assert main(["gt-sample", "--workspace", root, "--n", "2"]) == 0

    assert main(["evaluate", "--workspace", root, "--run", "run0"]) == 0
    out = capsys.readouterr().out
    assert "evaluated: 2" in out

    assert main(["eval-report", "--workspace", root, "--run", "run0"]) == 0
    assert (ws.reports_dir / "eval_run0.html").exists()
```

(The `_ws` fixture builds three `done` GT pages, two of which have run-0 text — hence `done: 3` and `evaluated: 2`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -q`
Expected: new test FAILS (`argparse` error: invalid choice `gt-status`).

- [ ] **Step 3: Implement**

In `src/corpus_tools/__main__.py`, add subparsers after the `report` parser:

```python
    p = sub.add_parser("gt-sample", help="select ground-truth sample and scaffold drafts")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=1979)

    p = sub.add_parser("gt-status", help="sync ground-truth completion status")
    p.add_argument("--workspace", type=Path, required=True)

    p = sub.add_parser("evaluate", help="compute CER for a run against ground truth")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--run", required=True)

    p = sub.add_parser("eval-report", help="write evaluation HTML report")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--run", required=True)
```

And dispatch branches before the final `return 0`:

```python
    elif args.cmd == "gt-sample":
        from .gt import scaffold_sample
        from .workspace import load_workspace
        stats = scaffold_sample(load_workspace(args.workspace), n=args.n, seed=args.seed)
        print(f"selected: {stats['selected']}  already: {stats['already']}  "
              f"drafts: {stats['drafts_written']}")
    elif args.cmd == "gt-status":
        from .gt import sync_gt_status
        from .workspace import load_workspace
        stats = sync_gt_status(load_workspace(args.workspace))
        print(f"done: {stats['done']}  selected: {stats['selected']}  "
              f"adopted: {stats['adopted']}")
    elif args.cmd == "evaluate":
        from .evaluate import evaluate_run
        from .workspace import load_workspace
        stats = evaluate_run(load_workspace(args.workspace), args.run)
        print(f"evaluated: {stats['evaluated']}  skipped: {len(stats['skipped'])}  "
              f"errors: {len(stats['errors'])}")
        for pid in stats["skipped"]:
            print("SKIPPED:", pid)
        for e in stats["errors"]:
            print("ERROR:", e)
        if stats["errors"]:
            return 1
    elif args.cmd == "eval-report":
        from .report_eval import write_eval_report
        from .workspace import load_workspace
        out = write_eval_report(load_workspace(args.workspace), args.run)
        print(f"report: {out}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -q` — Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q` — Expected: all tests PASS (46 pre-existing + ~21 new).

- [ ] **Step 6: Commit**

```bash
git add src/corpus_tools/__main__.py tests/test_main.py
git commit -m "feat: gt-sample/gt-status/evaluate/eval-report CLI subcommands"
```

---

### Task 8: `corpus-evaluate` skill

**Files:**
- Create: `.claude/skills/corpus-evaluate/SKILL.md`

**Interfaces:**
- Consumes: the four CLI subcommands from Task 7.
- Produces: a thin orchestrator skill following the existing `corpus-ingest` / `corpus-assess` style.

- [ ] **Step 1: Write the skill**

Create `.claude/skills/corpus-evaluate/SKILL.md`:

```markdown
---
name: corpus-evaluate
description: Ground-truth workflow and CER measurement — select the stratified transcription sample, track hand-correction progress, evaluate an OCR run against ground truth, and generate the evaluation report. Use when the user wants to pick ground-truth pages, check transcription status, or measure OCR accuracy (CER).
---

# corpus-evaluate

Thin orchestrator over `corpus_tools`. Workspace: `workspace/` at the repo root
(ask if a different one is meant).

## Workflow

1. **Select the sample** (once, after the corpus is fully ingested and assessed):
   `python -m corpus_tools gt-sample --workspace workspace --n 40`
   Deterministic stratified sample (issue × script × quality band). Additive:
   re-running never removes or overwrites anything. Drafts seeded from run-0
   text land in `workspace/ground_truth/drafts/`.

2. **Hand-correction (human loop):** the user corrects each draft against the
   page image in `workspace/pages/` per
   `docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`, saving the
   final transcription as `workspace/ground_truth/<page-id>.txt`.
   When helping, show the page image alongside the draft; never silently
   "fix" text yourself — anchoring bias is the main quality risk.

3. **Check progress:**
   `python -m corpus_tools gt-status --workspace workspace`

4. **Evaluate a run** (baseline is run0):
   `python -m corpus_tools evaluate --workspace workspace --run run0`

5. **Report:**
   `python -m corpus_tools eval-report --workspace workspace --run run0`
   Open `workspace/reports/eval_run0.html`; relay median CER, worst pages, and
   the quality-score calibration (Pearson r) to the user.

## Notes

- CER is whitespace-insensitive (line breaks don't count as errors).
- Evaluations are re-runnable: fixing a GT file and re-running `evaluate`
  overwrites the old value.
- Exit code 1 means errors were printed — surface them, don't ignore.
```

- [ ] **Step 2: Verify the CLI examples in the skill work**

Run: `python -m corpus_tools gt-status --workspace workspace`
Expected: prints `done: 0  selected: 0  adopted: 0` (no sample drawn yet on the real workspace).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/corpus-evaluate/SKILL.md
git commit -m "feat: corpus-evaluate skill; phase 2 tooling complete"
```

---

## Self-Review (done at plan-writing time)

1. **Spec coverage:** protocol §1 (file naming/format) → Task 4 paths; §6 process (OCR-base drafts allowed, notes with method/confidence) → Task 4 drafts + notes template; design-spec Phase 2 ("sampling + measurement", "run 0 measured before any re-OCR") → Tasks 3/5; "calibrates proxy metrics early" → Task 6 Pearson calibration. Protocol §7 open questions are human-decision items, not code; they're noted in the skill's human-loop step.
2. **Placeholder scan:** none — every step carries full code.
3. **Type consistency:** `cer()` returns key `dele` (not `del`, a Python keyword) — used consistently in Tasks 2, 5, 6. `iter_gt_pages(status=...)` signature consistent across Tasks 1, 4, 5. `scaffold_sample`/`sync_gt_status` names consistent across Tasks 4, 7, 8. Test helper `_ws` imported cross-module in Tasks 6/7 relies on pytest's rootdir `tests/` being importable — matches the existing flat-test layout (`from test_evaluate import _ws` works because pytest inserts the test dir on `sys.path`).

## After the plan (operational, not tasks)

1. Run the full-corpus ingest + assess (231 PDFs) so the real sample covers all issues — likely an overnight, resumable job.
2. `gt-sample`, then the professor hand-corrects ~40 pages per the protocol (the protocol's two open questions in §7 should be decided before page one).
3. `evaluate --run run0` + `eval-report` → **the Phase 2 deliverable: the run-0 CER baseline.**
