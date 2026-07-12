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
