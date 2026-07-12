from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_run0_text(pdf_path: Path, page_index: int,
                      gutter_x_px: int | None, image_width_px: int) -> dict[str, str]:
    page = PdfReader(pdf_path).pages[page_index - 1]
    if gutter_x_px is None:
        return {"F": (page.extract_text() or "").strip()}

    gutter_pt = gutter_x_px / image_width_px * float(page.mediabox.width)
    frags: dict[str, list[str]] = {"L": [], "R": []}

    def visitor(text, cm, tm, font_dict, font_size):
        if not text.strip():
            return
        x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
        frags["L" if x < gutter_pt else "R"].append(text)

    page.extract_text(visitor_text=visitor)
    return {side: "\n".join(parts).strip() for side, parts in frags.items()}
