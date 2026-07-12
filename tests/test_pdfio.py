from corpus_tools.pdfio import extract_spread_image, pdf_has_text, pdf_page_count


def test_page_count_positive(sample_pdf):
    assert pdf_page_count(sample_pdf) >= 1


def test_extract_spread_image_is_large_scan(sample_pdf):
    im = extract_spread_image(sample_pdf, 1)
    assert im.width > 2000 and im.height > 2000  # native ~300 DPI scan


def test_has_text(sample_pdf):
    assert pdf_has_text(sample_pdf) is True
