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
    # No text is lost by splitting. Exact word-count equality does not hold:
    # visitor_text() emits one joined-by-"\n" fragment per content-stream text
    # run, while plain extract_text() merges same-line runs using its own
    # layout heuristics, so split() token counts differ (often the L/R sum is
    # higher than the full-page count, never meaningfully lower). Per the
    # task-7 brief, relax to a lower-bound check that no text is dropped.
    assert len(out["L"].split()) + len(out["R"].split()) >= 0.98 * len(full.split())
