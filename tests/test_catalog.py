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
