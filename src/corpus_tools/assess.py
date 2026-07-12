from __future__ import annotations

import cv2
import numpy as np

# Characters that exist only in one script (common in 1980s magazine prose).
_SIMP = set("国发对说们时会学过还进动书长门问题体万与义乐传报讯电见观现连线")
_TRAD = set("國發對說們時會學過還進動書長門問題體萬與義樂傳報訊電見觀現連線")

_CJK_OK = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF),          # unified ideographs
    (0x3000, 0x303F), (0xFF00, 0xFFEF),          # CJK punct, full-width forms
    (0x2018, 0x201D), (0x2026, 0x2026),          # quotes, ellipsis
)


def estimate_skew(gray: np.ndarray) -> float:
    scale = 1000 / gray.shape[1]
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = ink.shape
    best_angle, best_score = 0.0, -1.0
    for ang in np.arange(-3.0, 3.01, 0.25):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h))
        prof = rot.sum(axis=1).astype(np.float64)
        score = float(((prof[1:] - prof[:-1]) ** 2).sum())
        if score > best_score:
            best_score, best_angle = score, float(ang)
    # best_angle is the correction that sharpens row profiles; the page's own
    # skew is its negation (positive = content rotated counterclockwise).
    return -best_angle


def measure_page(gray: np.ndarray) -> dict:
    p5, p95 = np.percentile(gray, [5, 95])
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink_mask = binary == 0
    background = float(np.median(gray[~ink_mask])) if (~ink_mask).any() else float(p95)
    denoised = cv2.medianBlur(gray, 3)
    noise = float((gray.astype(np.int16) - denoised.astype(np.int16)).std())
    return {
        "skew_deg": estimate_skew(gray),
        "contrast": float(p95 - p5),
        "background_gray": background,
        "ink_density": float(ink_mask.mean()),
        "noise": noise,
    }


def detect_script(text: str) -> str:
    s = sum(c in _SIMP for c in text)
    t = sum(c in _TRAD for c in text)
    if s >= 3 and s > 2 * t:
        return "simplified"
    if t >= 3 and t > 2 * s:
        return "traditional"
    return "unknown"


def garbage_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    def ok(c: str) -> bool:
        o = ord(c)
        if o < 128:
            return True
        return any(lo <= o <= hi for lo, hi in _CJK_OK)
    return sum(not ok(c) for c in chars) / len(chars)


def quality_score(fields: dict) -> float:
    contrast = min(fields["contrast"] / 180.0, 1.0)
    noise = 1.0 - min(fields["noise"] / 15.0, 1.0)
    skew = 1.0 - min(abs(fields["skew_deg"]) / 3.0, 1.0)
    clean = 1.0 - min(fields["garbage_ratio"] / 0.3, 1.0)
    return round(0.35 * contrast + 0.2 * noise + 0.15 * skew + 0.3 * clean, 4)
