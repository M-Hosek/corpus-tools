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
