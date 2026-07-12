---
name: corpus-ingest
description: Ingest scanned source PDFs into a corpus workspace — checksums, spread splitting, page images, embedded OCR as run 0. Use when the user wants to add new scanned PDFs to the corpus or create a new workspace.
---

# Corpus Ingest

Ingest source PDFs into a workspace. All logic lives in `corpus_tools`; this skill orchestrates the CLI and verifies results.

## Steps

1. If no workspace exists yet: `python -m corpus_tools init <workspace-path> --name <corpus-name>`
2. Confirm the source folder with the user, then run (background for large batches; ~10–20 s per PDF on this CPU):
   `python -m corpus_tools ingest "<source-folder>" --workspace <workspace-path>`
3. Verify, and report to the user:
   - stats line printed by the CLI (`new sources / skipped / pages / errors`)
   - every error line, verbatim — never summarize errors away
   - sanity check in SQLite: `python -c "import sqlite3; c=sqlite3.connect(r'<ws>/catalog.db'); print(c.execute('SELECT COUNT(*) FROM sources').fetchone(), c.execute('SELECT side, COUNT(*) FROM pages GROUP BY side').fetchall())"`
   - expected shape: most pages are L/R pairs; a small number of F pages (covers/foldouts) is normal. A large F count suggests gutter detection is failing — open 2–3 F page PNGs and inspect before proceeding.
4. Re-running on the same folder is safe (checksummed sources are skipped).

## Rules

- Never modify or delete anything in the source folder or `originals/`.
- If a PDF errors, ingest continues; collect the errors and report them — do not retry blindly.
