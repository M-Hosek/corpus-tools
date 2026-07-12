import shutil
from pathlib import Path

import corpus_tools.catalog as catalog_mod
import corpus_tools.ingest as ingest_mod
from corpus_tools.ingest import ingest_folder, sha256_file
from corpus_tools.pdfio import extract_spread_image as real_extract_spread_image
from corpus_tools.workspace import init_workspace

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_ingest_replaced_source_does_not_alias_old_content(tmp_path, sample_pdf):
    ws, src = _setup(tmp_path, sample_pdf)
    target = src / "kexue wenyi 1980.5" / "0838_043.pdf"
    first = ingest_folder(ws, src)
    assert first["sources_new"] == 1

    with ws.open_catalog() as cat:
        old_source_id = cat.iter_pages()[0]["source_id"]
    old_dest = ws.originals_dir / "kexue wenyi 1980.5" / "0838_043.pdf"
    assert old_dest.exists()
    old_dest_hash = sha256_file(old_dest)
    assert old_dest_hash == sha256_file(sample_pdf)

    # Replace the source file in place: same filename, different bytes.
    new_bytes = sample_pdf.read_bytes() + b"\n% different content, same name\n"
    target.write_bytes(new_bytes)
    new_source_id = sha256_file(target)
    assert new_source_id != old_source_id

    second = ingest_folder(ws, src)
    assert second["sources_new"] == 1
    assert not second["errors"]

    # Old original on disk is untouched by the second ingest.
    assert sha256_file(old_dest) == old_dest_hash

    with ws.open_catalog() as cat:
        new_src_row = cat.get_source(new_source_id)
        assert new_src_row is not None
        # New source got a disambiguated dest, not aliased onto the old file.
        new_dest = ws.root / new_src_row["rel_path"]
        assert new_dest != old_dest
        assert new_dest.exists()
        assert sha256_file(new_dest) == new_source_id

        new_pages = cat.iter_pages("source_id = ?", (new_source_id,))
        assert new_pages
        for p in new_pages:
            assert (ws.root / p["image_path"]).exists()


def test_ingest_resumes_after_crash_between_sides(tmp_path, sample_pdf, monkeypatch):
    """A crash right after committing side L (before side R is even attempted)
    must not permanently drop R: a lone {L} row for a pdf_page_index must be
    treated as incomplete and reprocessed."""
    ws, src = _setup(tmp_path, sample_pdf)
    real_add_page = catalog_mod.Catalog.add_page

    def flaky_add_page(self, page):
        if page["page_id"].endswith("R"):
            raise RuntimeError("boom-mid-page")
        return real_add_page(self, page)

    monkeypatch.setattr(catalog_mod.Catalog, "add_page", flaky_add_page)
    first = ingest_folder(ws, src)
    assert len(first["errors"]) == 1
    with ws.open_catalog() as cat:
        assert cat.count("sources") == 0
        pages = cat.iter_pages()
        assert pages  # at least side L got committed before the crash
        assert all(p["side"] != "R" for p in pages)

    monkeypatch.undo()
    second = ingest_folder(ws, src)
    assert second["sources_new"] == 1
    assert not second["errors"]
    with ws.open_catalog() as cat:
        assert cat.count("sources") == 1
        pages = cat.iter_pages()
        by_idx: dict[int, set] = {}
        for p in pages:
            by_idx.setdefault(p["pdf_page_index"], set()).add(p["side"])
        assert any(sides == {"L", "R"} for sides in by_idx.values()), \
            "fixture expected to contain at least one L/R spread page"
        for idx, sides in by_idx.items():
            assert sides in ({"L", "R"}, {"F"}), f"page {idx} incomplete: {sides}"
        for p in pages:
            assert (ws.root / p["image_path"]).exists()
            rp = cat.get_run_page("run0", p["page_id"])
            assert rp is not None
            assert (ws.root / rp["text_path"]).exists()


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
