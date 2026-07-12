from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Gutter must be at least this many gray levels darker than the page median.
GUTTER_MIN_DEPTH = 20
# A content region narrower than 1.1x its height is a single page, not a spread.
SPREAD_MIN_ASPECT = 1.1


def find_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int]:
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return (0, 0, gray.shape[1], gray.shape[0])
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
            int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))


def find_gutter_x(gray: np.ndarray, bbox: tuple[int, int, int, int]) -> int | None:
    x, y, w, h = bbox
    if w < SPREAD_MIN_ASPECT * h:
        return None
    region = gray[y:y + h, x:x + w]
    col = region.mean(axis=0)
    col = np.convolve(col, np.ones(31) / 31, mode="same")
    lo, hi = int(w * 0.35), int(w * 0.65)
    gx = lo + int(np.argmin(col[lo:hi]))
    if np.median(col) - col[gx] < GUTTER_MIN_DEPTH:
        return None
    return x + gx


def split_spread(img: Image.Image) -> tuple[list[tuple[str, Image.Image]], int | None]:
    gray = np.array(img.convert("L"))
    bbox = find_content_bbox(gray)
    x, y, w, h = bbox
    gx = find_gutter_x(gray, bbox)
    if gx is None:
        return [("F", img.crop((x, y, x + w, y + h)))], None
    return [("L", img.crop((x, y, gx, y + h))),
            ("R", img.crop((gx, y, x + w, y + h)))], gx
