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
