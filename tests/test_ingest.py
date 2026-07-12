import shutil

import corpus_tools.ingest as ingest_mod
from corpus_tools.ingest import ingest_folder, sha256_file
from corpus_tools.pdfio import extract_spread_image as real_extract_spread_image
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


def test_ingest_resumes_after_partial_failure(tmp_path, sample_pdf, monkeypatch):
    ws, src = _setup(tmp_path, sample_pdf)

    def flaky_extract_spread_image(pdf_path, page_index):
        if page_index == 2:
            raise RuntimeError("boom")
        return real_extract_spread_image(pdf_path, page_index)

    monkeypatch.setattr(ingest_mod, "extract_spread_image", flaky_extract_spread_image)
    first = ingest_folder(ws, src)
    assert len(first["errors"]) == 1
    with ws.open_catalog() as cat:
        assert cat.count("sources") == 0

    monkeypatch.undo()
    second = ingest_folder(ws, src)
    assert second["sources_new"] == 1
    with ws.open_catalog() as cat:
        assert cat.count("sources") == 1
        pages = cat.iter_pages()
        source_id = pages[0]["source_id"]
        src_row = cat.get_source(source_id)
        assert src_row is not None
        n = src_row["page_count"]
        seen_indices = [p["pdf_page_index"] for p in pages]
        for idx in range(1, n + 1):
            assert seen_indices.count(idx) >= 1
        # no duplicate page_ids
        page_ids = [p["page_id"] for p in pages]
        assert len(page_ids) == len(set(page_ids))
        for p in pages:
            assert (ws.root / p["image_path"]).exists()
            rp = cat.get_run_page("run0", p["page_id"])
            assert rp is not None
            assert (ws.root / rp["text_path"]).exists()
