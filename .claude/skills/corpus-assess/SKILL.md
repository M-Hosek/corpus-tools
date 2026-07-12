---
name: corpus-assess
description: Measure per-page quality (skew, contrast, noise, script, garbage ratio, quality score) for ingested corpus pages and generate the HTML assessment report. Use after corpus-ingest, or when the user asks about scan/OCR quality.
---

# Corpus Assess

Assessment is resumable: only unassessed pages are processed; `--force` re-does everything.

## Steps

1. Run (background; roughly 1–3 s per page on this CPU — a full 3,600-page corpus is an hours-long job):
   `python -m corpus_tools assess --workspace <workspace-path>`
   For a quick look, use `--limit 200` first.
2. Generate the report: `python -m corpus_tools report --workspace <workspace-path>`
3. Open `reports/assess_report.html`, and summarize for the user:
   - quality_score distribution shape (uniform? bimodal? long tail?)
   - script breakdown (this corpus should be overwhelmingly simplified; a large 'unknown' share usually means empty/garbled run-0 text, not traditional script)
   - anything alarming in the lowest-quality gallery (blank pages, failed splits, upside-down scans)
4. Report errors verbatim.

## Rules

- Assessment writes only to the catalog and `reports/` — if anything tries to modify `pages/` or `originals/`, stop.
