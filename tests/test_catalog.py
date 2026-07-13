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
