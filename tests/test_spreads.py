import numpy as np
from PIL import Image

from corpus_tools.spreads import find_content_bbox, find_gutter_x, split_spread

BG, PAGE, GUTTER = 30, 225, 90


def make_spread(w=1500, h=1000, gutter_w=24) -> Image.Image:
    """Dark background, two bright pages, dark-ish gutter between them."""
    a = np.full((h, w), BG, dtype=np.uint8)
    # content region inset 60 px from each edge
    a[60:h - 60, 60:w - 60] = PAGE
    mid = w // 2
    a[60:h - 60, mid - gutter_w // 2: mid + gutter_w // 2] = GUTTER
    return Image.fromarray(a).convert("RGB")


def make_single(w=800, h=1000) -> Image.Image:
    a = np.full((h, w), BG, dtype=np.uint8)
    a[50:h - 50, 50:w - 50] = PAGE
    return Image.fromarray(a).convert("RGB")


def test_content_bbox_excludes_background():
    gray = np.array(make_spread().convert("L"))
    x, y, w, h = find_content_bbox(gray)
    assert 40 <= x <= 70 and 40 <= y <= 70
    assert 1360 <= w <= 1420 and 860 <= h <= 920


def test_gutter_found_near_center():
    gray = np.array(make_spread().convert("L"))
    gx = find_gutter_x(gray, find_content_bbox(gray))
    assert gx is not None
    assert abs(gx - 750) < 30


def test_split_spread_returns_two_bright_halves():
    parts, gx = split_spread(make_spread())
    assert [s for s, _ in parts] == ["L", "R"]
    assert gx is not None
    for _, im in parts:
        arr = np.array(im.convert("L"))
        assert arr.mean() > 150          # mostly page, little background
        assert 600 < im.width < 800      # roughly half of the 1380px content


def test_single_page_not_split():
    parts, gx = split_spread(make_single())
    assert [s for s, _ in parts] == ["F"]
    assert gx is None


# --- Bilevel scans (real ca4071-style sources) ---------------------------
# Photocopied bound magazines scanned as pure black/white: white paper to the
# image edge, black text, and a bright (white) gutter band -- no dark shadow
# valley for the mean-intensity detector to find.

def _draw_text_lines(a: np.ndarray, x0: int, x1: int) -> None:
    h = a.shape[0]
    for ty in range(200, h - 200, 30):
        a[ty:ty + 14, x0:x1] = 0


def make_bilevel_spread(w=3600, h=2600, gutter_w=130, gutter_frac=0.5,
                        col_gap_w=40) -> Image.Image:
    """White paper, black text lines, pure-white gutter; only values 0/255.

    Each page half has two text columns separated by a narrow gap, so the
    detector must prefer the wide gutter band over narrow inter-column gaps.
    """
    a = np.full((h, w), 255, dtype=np.uint8)
    gx = int(w * gutter_frac)
    margin = 120
    for lo, hi in [(margin, gx - gutter_w // 2), (gx + gutter_w // 2, w - margin)]:
        mid = (lo + hi) // 2
        _draw_text_lines(a, lo, mid - col_gap_w // 2)
        _draw_text_lines(a, mid + col_gap_w // 2, hi)
    return Image.fromarray(a).convert("RGB")


def make_bilevel_single(w=1760, h=2500) -> Image.Image:
    """Portrait bilevel page with two text columns and white background."""
    a = np.full((h, w), 255, dtype=np.uint8)
    _draw_text_lines(a, 120, w // 2 - 30)
    _draw_text_lines(a, w // 2 + 30, w - 120)
    return Image.fromarray(a).convert("RGB")


def test_bilevel_spread_white_gutter_found():
    img = make_bilevel_spread()
    gray = np.array(img.convert("L"))
    gx = find_gutter_x(gray, find_content_bbox(gray))
    assert gx is not None
    assert abs(gx - 1800) < 70          # inside the 130px gutter band at center


def test_bilevel_spread_off_center_gutter_beats_column_gap():
    # Gutter at 42% of width; a narrow inter-column gap falls inside the
    # central search window and must NOT be chosen (and must not block a find).
    img = make_bilevel_spread(gutter_frac=0.42)
    gray = np.array(img.convert("L"))
    gx = find_gutter_x(gray, find_content_bbox(gray))
    assert gx is not None
    band_lo = int(3600 * 0.42) - 65
    band_hi = int(3600 * 0.42) + 65
    assert band_lo <= gx <= band_hi


def test_bilevel_spread_split_sides():
    parts, gx = split_spread(make_bilevel_spread())
    assert [s for s, _ in parts] == ["L", "R"]
    assert gx is not None


def test_bilevel_single_page_not_split():
    parts, gx = split_spread(make_bilevel_single())
    assert [s for s, _ in parts] == ["F"]
    assert gx is None
