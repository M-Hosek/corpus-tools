import numpy as np
import pytest
from PIL import Image, ImageDraw

from corpus_tools.assess import (detect_script, estimate_skew, garbage_ratio,
                                 measure_page, quality_score)


def make_text_page(angle: float = 0.0) -> np.ndarray:
    """Bright page with dark horizontal text-like bars, optionally rotated."""
    im = Image.new("L", (1200, 1600), 235)
    d = ImageDraw.Draw(im)
    for y in range(150, 1450, 40):
        d.rectangle([100, y, 1100, y + 14], fill=25)
    if angle:
        im = im.rotate(angle, fillcolor=235, resample=Image.BILINEAR)
    return np.array(im)


@pytest.mark.parametrize("angle", [0.0, 1.5, -2.0])
def test_estimate_skew(angle):
    est = estimate_skew(make_text_page(angle))
    assert abs(est - angle) <= 0.3


def test_measure_page_fields():
    m = measure_page(make_text_page())
    assert set(m) == {"skew_deg", "contrast", "background_gray", "ink_density", "noise"}
    assert m["background_gray"] > 200
    assert 0.05 < m["ink_density"] < 0.6
    assert m["contrast"] > 150


def test_detect_script():
    assert detect_script("这是一个关于科学的故事，我们的时代会发展。") == "simplified"
    assert detect_script("這是一個關於科學的故事，我們的時代會發展。") == "traditional"
    assert detect_script("山中有水。") == "unknown"
    assert detect_script("") == "unknown"


def test_garbage_ratio():
    assert garbage_ratio("这是干净的中文。") == 0.0
    assert garbage_ratio("abc 123 中文") == 0.0
    r = garbage_ratio("中文θρ¤∶≡中文")   # 5 garbage of 9 non-space chars ≈ 0.56
    assert 0.4 < r < 0.6


def test_quality_score_orders_pages():
    good = quality_score(dict(contrast=180, noise=2.0, skew_deg=0.2, garbage_ratio=0.02))
    bad = quality_score(dict(contrast=60, noise=12.0, skew_deg=2.5, garbage_ratio=0.30))
    assert 0.0 <= bad < good <= 1.0
