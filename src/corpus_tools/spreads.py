from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Gutter must be at least this many gray levels darker than the page median.
GUTTER_MIN_DEPTH = 20
# A content region narrower than 1.1x its height is a single page, not a spread.
SPREAD_MIN_ASPECT = 1.1
# --- Ink-valley detection (bright gutters, e.g. bilevel scans) -------------
# Pixels darker than this count as ink (works for bilevel 0/255 scans and for
# grayscale text on light paper).
INK_THRESHOLD = 128
# A gutter column may carry at most this smoothed ink fraction.
GUTTER_MAX_INK = 0.02
# The low-ink band must be at least this fraction of the content width (and
# never narrower than GUTTER_MIN_RUN_PX) so narrow inter-column text gaps are
# not mistaken for the gutter.
GUTTER_MIN_RUN_FRAC = 0.015
GUTTER_MIN_RUN_PX = 20
# The page must contain some ink overall for a low-ink valley to be meaningful.
PAGE_MIN_INK = 0.01


def find_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int]:
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    ys, xs = np.where(mask != 0)
    if ys.size == 0:
        return (0, 0, gray.shape[1], gray.shape[0])
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _dark_valley_gutter(region: np.ndarray, w: int) -> int | None:
    """Gutter as a dark shadow valley in the column-mean profile.

    Works for grayscale photocopies where the binding casts a shadow that is
    clearly darker than the surrounding paper.
    """
    col = region.mean(axis=0)
    col = np.convolve(col, np.ones(31) / 31, mode="same")
    lo, hi = int(w * 0.35), int(w * 0.65)
    gx = lo + int(np.argmin(col[lo:hi]))
    if np.median(col) - col[gx] < GUTTER_MIN_DEPTH:
        return None
    return gx


def _ink_valley_gutter(region: np.ndarray, w: int) -> int | None:
    """Gutter as a wide ink-free band between two inked page halves.

    Bilevel (pure black/white) scans have no shadow valley: the gutter is a
    bright band, and smoothed column means barely dip under text.  Instead,
    look for a wide run of near-zero ink density crossing the central window.
    Narrow inter-column text gaps are rejected by a minimum band width.
    """
    ink = (region < INK_THRESHOLD).mean(axis=0)
    if float(np.median(ink)) < PAGE_MIN_INK:
        return None  # (nearly) blank region: a valley proves nothing
    smooth = np.convolve(ink, np.ones(15) / 15, mode="same")
    low = smooth <= GUTTER_MAX_INK
    lo, hi = int(w * 0.35), int(w * 0.65)
    min_run = max(GUTTER_MIN_RUN_PX, GUTTER_MIN_RUN_FRAC * w)
    center = w / 2

    # Runs of consecutive low-ink columns.
    edges = np.flatnonzero(np.diff(np.concatenate(
        ([False], low, [False])).astype(np.int8)))
    best: int | None = None
    best_dist = float("inf")
    for a, b in zip(edges[::2], edges[1::2]):  # run is [a, b)
        if b <= lo or a >= hi or (b - a) < min_run:
            continue
        # Cut at the run's point nearest the geometric centre of the content.
        gx = int(min(max(center, a), b - 1))
        dist = abs(gx - center)
        if dist < best_dist:
            best, best_dist = gx, dist
    return best


def find_gutter_x(gray: np.ndarray, bbox: tuple[int, int, int, int]) -> int | None:
    x, y, w, h = bbox
    if w < SPREAD_MIN_ASPECT * h:
        return None
    region = gray[y:y + h, x:x + w]
    gx = _dark_valley_gutter(region, w)
    if gx is None:
        gx = _ink_valley_gutter(region, w)
    if gx is None:
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
