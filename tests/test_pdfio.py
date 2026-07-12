import pytest
from PIL import Image

import corpus_tools.pdfio as pdfio_mod
from corpus_tools.pdfio import extract_spread_image, pdf_has_text, pdf_page_count


class _FakeImageFile:
    def __init__(self, image):
        self.image = image


class _FakePage:
    def __init__(self, images):
        self.images = images


class _FakeReader:
    def __init__(self, images):
        self.pages = [_FakePage(images)]


def test_extract_spread_image_raises_on_split_strips(monkeypatch):
    # Two comparably-sized images: looks like a scanner stored the page as
    # two strips rather than one image plus a tiny speck.
    strip_a = Image.new("L", (2000, 1000))
    strip_b = Image.new("L", (2000, 900))
    reader = _FakeReader([_FakeImageFile(strip_a), _FakeImageFile(strip_b)])
    monkeypatch.setattr(pdfio_mod, "PdfReader", lambda path: reader)

    with pytest.raises(ValueError, match="strips"):
        extract_spread_image("dummy.pdf", 1)


def test_extract_spread_image_allows_tiny_secondary_image(monkeypatch):
    # One dominant scan plus a tiny icon/speck should not trip the guard.
    big = Image.new("L", (3000, 2000))
    speck = Image.new("L", (20, 20))
    reader = _FakeReader([_FakeImageFile(big), _FakeImageFile(speck)])
    monkeypatch.setattr(pdfio_mod, "PdfReader", lambda path: reader)

    result = extract_spread_image("dummy.pdf", 1)
    assert result is big


def test_page_count_positive(sample_pdf):
    assert pdf_page_count(sample_pdf) >= 1


def test_extract_spread_image_is_large_scan(sample_pdf):
    im = extract_spread_image(sample_pdf, 1)
    assert im.width > 2000 and im.height > 2000  # native ~300 DPI scan


def test_has_text(sample_pdf):
    assert pdf_has_text(sample_pdf) is True
