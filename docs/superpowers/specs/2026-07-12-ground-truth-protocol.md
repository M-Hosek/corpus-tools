# Ground-Truth Transcription Protocol (draft)

**Date:** 2026-07-12 · **Status:** Draft — review before correcting the first page.

Purpose: consistent hand-corrected transcriptions of the ~30–50 sample pages. Every accuracy figure in this project is computed against these files, so consistency here matters more than speed. When in doubt, add a note rather than guess silently.

## 1. Unit and file format

- One UTF-8 plain-text file per page, named by page-id: `ground_truth/<page-id>.txt`.
- Optional companion notes file `<page-id>.notes.md` for anything unusual (damage, ambiguity, layout oddities).

## 2. What to transcribe

- **All body text, headlines, bylines, captions, and page furniture (page numbers, running heads)** — each on its own line(s), in natural reading order (see §4). Rationale: OCR output includes these, so ground truth must too, or CER is inflated by "errors" that are really scope mismatches.
- **Do not transcribe** text inside illustrations/artwork (sound effects in comics, lettering in ads' images) unless it is typeset text. Note its presence in the notes file instead.
- Tables: transcribe cell text row by row, cells separated by a single tab.

## 3. Characters

- **Transcribe the glyph actually printed**, not its modern or normalized form. Traditional stays traditional; variant forms (旣, 爲, 硏…) are kept as printed. This matches the project's store-as-printed glyph policy; normalization happens only at export.
- If a variant glyph cannot be typed, use the closest encodable form and record the substitution in the notes file.
- **Illegible character:** `□` (U+25A1 WHITE SQUARE), one per illegible character. If the character count itself is uncertain, best estimate + note.
- **Partially legible but confidently inferable from context:** transcribe the inferred character — the printed page *does* say it; the photocopy merely obscures it. If not confident, use `□`.
- Numerals and Latin letters: as printed (full-width vs. half-width as printed, if distinguishable; if not distinguishable, default to half-width and note the convention was applied).

## 4. Reading order and line breaks

- Follow natural reading order: for multi-column horizontal pages, complete each column top-to-bottom before moving to the next (right-to-left or left-to-right as the layout dictates); vertical text columns right-to-left.
- **Preserve the printed line breaks** (one printed line = one line in the file). Rationale: line-level alignment makes CER computation and error inspection far easier, and joining lines is trivial later; re-splitting is not.
- Blank line between blocks (paragraphs, columns, captions, headlines).
- Where reading order is genuinely ambiguous (pull-quotes, sidebars), pick a reasonable order and record the choice in notes — evaluation will use order-tolerant alignment for these pages.

## 5. Punctuation and spacing

- Punctuation as printed: full-width Chinese punctuation (，。「」《》…) stays full-width; do not convert quote styles (「」 vs. “”) — transcribe what is printed.
- No spaces between Chinese characters. Spaces in Latin-script passages as printed.
- Emphasis marks (着重号, dots/lines beside characters) are not transcribed; note their extent in the notes file.

## 6. Process

1. Work from the rendered page image in `pages/` (not the OCR text) at full zoom.
2. Starting from the run-0 OCR text as a base *is allowed* to save typing, **but read every character against the image** — anchoring bias (accepting a plausible-but-wrong OCR character) is the main quality risk of this shortcut. For badly degraded pages, transcribe from scratch.
3. Second pass: re-read the finished transcription against the image once, ideally after a break.
4. Record per page in the notes file: transcription date, whether OCR-base or from-scratch, and estimated confidence (high/medium/low).

## 7. Open questions (resolve before starting)

- Full-width vs. half-width digits: some 1980s–90s typesetting is genuinely ambiguous at photocopy quality. Proposed default: as printed when clear, half-width otherwise.
- Whether to transcribe advertisements at all, or mark ad-only pages as out of corpus scope.
