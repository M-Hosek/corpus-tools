# Design: Chinese Magazine OCR Remediation Pipeline

**Date:** 2026-07-12
**Status:** Approved in brainstorm; pending review of written spec
**Project:** Rebuilding a reliable, analysis-grade text corpus from ~3,000+ pages of scanned, photocopied Chinese science fiction magazines with imperfect (~70% accurate) embedded OCR.

## 0. Source material findings (2026-07-12 inspection)

Inspection of the delivered corpus (231 PDFs, 5.67 GB, `incoming/sf magazines 2025/`) established:

- **Contents:** 科学文艺 (Kexue Wenyi) 1979.1–1988.6 plus 少年科技 (Shaonian Keji) 1977, one folder per issue, each issue split across ~4–6 scanner-batch-named PDF chunks (`NNNN_NNN.pdf`). **Folder name = issue identity** — cataloging is simpler than the "messy chunks" assumption. Gaps to confirm with owner: no 1982 folders; scan batch 0868 absent.
- **Scan format:** each PDF page is a **two-page spread** of the bound magazine on a flatbed (Canon; ~4299×3035 px RGB at native 300 DPI, 14.3×10.1 in landscape; occasional larger 16.5×11.7 in pages, likely covers/foldouts). Visible: dark scanner background and book edges around pages, center gutter shadow, mild page curvature near the spine, yellowed paper, some bleed-through. Print quality of the sample is good — clean typeset text, not degraded photocopy.
- **Embedded OCR (run 0):** present, simplified Chinese, with characteristic errors (component-split characters like 衤丙 for 柄, visually-similar substitutions 包/色, 超/起, stray Greek/symbol garbage θ ρ ¤). Consistent with the ~70% estimate on hard pages; likely better on clean body text. Reading order/column errors expected to be significant.

**Design consequences:** (a) ingest gains a **spread-splitting stage** — detect content region, split at the gutter, crop scanner background — so the atomic unit remains the *magazine page*, with page-ids like `<hash>-p003L`/`p003R`; printed page numbers (visible in scans) can be OCR'd to validate split/ordering. (b) Rendering DPI is moot: embedded 300 DPI scan images are **extracted losslessly**, not re-rendered. (c) Preprocessing priorities: gutter/edge masking, curvature-aware deskew, background flattening, bleed-through suppression.

## 1. Goals and constraints

**Primary deliverable:** an analysis-grade plain-text corpus suitable for digital-humanities work (quotation, word frequency, topic modeling). **Secondary deliverable:** rebuilt searchable PDFs. Accuracy therefore matters more than coverage; evaluation and human-correction loops are first-class components.

Constraints established during design:

- **OCR strategy:** local-first (PaddleOCR) for the bulk; cloud vision-language model escalation for hard pages only.
- **Material:** mixed corpus — simplified and traditional Chinese, mostly horizontal multi-column, some vertical text, images, photocopy degradation (skew, gray backgrounds, noise, faint characters, dark edges, gutter shadows, bleed-through).
- **Ground truth:** a stratified sample of ~30–50 pages will be hand-corrected to enable true character-error-rate (CER) measurement.
- **Compute:** this Windows 11 machine, CPU only. Batch jobs must be resumable and incremental.
- **Source data:** messy PDF chunks (inconsistent splitting, naming, possible overlaps) — cataloging is stage zero.
- **Preservation:** original PDFs and their OCR layers are read-only reference data forever. Every derived artifact records exactly how it was made.
- **Reuse:** components must transfer to future archives (different collections, possibly different languages).

## 2. Architecture (Approach A — chosen)

One Python package, **`corpus_tools`**, holds all real logic (PDF extraction, image preprocessing, OCR adapters, metrics, PDF rebuilding). Claude Code **skills are thin orchestrators** that invoke the library against a **corpus workspace**. A future CLI or app is the same library behind a different front end — that seam is deliberate.

Alternatives considered and rejected:

- **B — self-contained skills, no shared library:** fastest start but duplicates logic across skills, drifts, and must be refactored into a library anyway to become an app. Wrong for a multi-year research asset.
- **C — pipeline framework (DVC/Snakemake):** strongest formal provenance, but fights Windows, imposes its model on an exploratory workflow, and makes human-in-the-loop correction awkward. Its *discipline* (run manifests, immutable inputs, config recording) is adopted as convention instead.

## 3. Corpus workspace and data model

A workspace is one directory per corpus. This collection is workspace #1; future archives get new workspaces with the same tools.

```
workspace/
  workspace.yaml          # corpus name, defaults (DPI, language hints), pinned tool versions
  originals/              # source PDFs exactly as received — read-only, SHA-256 checksummed
  catalog.db              # SQLite: single source of truth for all state
  pages/                  # one PNG per page at fixed DPI, named by page-id
  preprocessed/<recipe>/  # cleaned images, one folder per named preprocessing recipe
  ocr/runs/<run-id>/      # per-run: per-page text/hOCR + manifest.json (engine, version, params, input hashes, timestamp)
  ground_truth/           # hand-corrected transcriptions, one per page-id
  reports/                # generated HTML/markdown reports
  rebuilt/                # output PDFs with new text layers
```

**The page is the atomic unit.** Each page receives a stable ID on ingest (source-file hash prefix + page number, e.g. `b3f2a1-p017`). All downstream state hangs off page-IDs, which makes messy source chunking a non-problem: cataloging maps chaos to page-IDs once; later corrections to issue/article mapping are catalog edits, requiring no artifact regeneration.

**Catalog (SQLite)** — four record kinds:

1. **Sources** — original PDF: checksum, page count, embedded-OCR presence, ingest date.
2. **Pages** — page-id, source + page number, detected properties (skew, contrast stats, noise, script, orientation, has-images), quality score, triage tier, human-assigned metadata (issue, article, notes).
3. **OCR runs** — run-id, engine + version, parameters, preprocessing recipe, input hashes, timestamp. The embedded scanner OCR is ingested as **run 0**, compared on equal footing, never overwritten.
4. **Evaluations** — metric results per (run, page) against ground truth or proxies.

SQLite is chosen over JSON/CSV for real queryability at this scale, single-file portability, direct readability from Python/R, and archival durability (a Library of Congress recommended storage format). Every mutation is also appended to a plain-text audit log so the catalog is reconstructible.

## 4. Skill roster

Eight skills, thin orchestrators over `corpus_tools`:

| Skill | Responsibility | Input | Output |
|---|---|---|---|
| `corpus-ingest` | Messy PDFs → cataloged workspace. Checksums, duplicate detection, page-ID minting, run-0 extraction. Idempotent. | Folder of PDFs + workspace | `originals/`, `pages/`, run 0, populated catalog |
| `corpus-assess` | Measure before changing: skew, contrast, noise, script, orientation, run-0 confidence proxies. First skill run on any future archive. | Workspace or page filter | Per-page properties in catalog + HTML report with thumbnails, histograms, proposed tiering |
| `corpus-triage` | Assign treatment tier per page. Tiers are catalog data, re-computable without redoing work; report shows samples per tier. | Assessment data + thresholds | Tier per page: **T1** keep run 0 · **T2** re-OCR locally after preprocessing · **T3** escalate to cloud · **T4** human eyes |
| `corpus-preprocess` | Cleaned images under named, versioned recipes (declared configs, not ad-hoc flags) so recipes are A/B-testable and citable. | Page filter + recipe | `preprocessed/<recipe>/` + recipe record in catalog |
| `corpus-ocr` | Run an engine, producing a new immutable run. Resumable batches for overnight CPU runs. | Page filter + engine + recipe | New `ocr/runs/<run-id>/` with text, coordinates, confidence, manifest |
| `corpus-compare` | Character-level diffs between runs; records a per-page **selection** of best run in the catalog. Selection is human-editable. | ≥2 run-ids + page filter | Diff reports, summary stats, selection records |
| `corpus-evaluate` | Ground-truth CER measurement (stratified by tier/script/source) and calibration of proxy metrics against true CER. Also drives ground-truth sample selection and correction workflow. | Run-id (+ ground truth) | Evaluation records + calibration report |
| `corpus-export` | Build deliverables from selections. Never modifies upstream state. | Page filter + format | Rebuilt searchable PDFs; plain-text corpus with per-page provenance headers |

**Coordinator:** deliberately absent for now. The catalog is the coordination mechanism — all skills read/write state through it, so a future orchestration layer (skill, CLI, or app) is a loop over catalog queries calling the same library. It will be designed after one full corpus has been processed manually, from observed usage patterns.

**Deliberate deferrals:** ground-truth creation is folded into `corpus-evaluate` (mostly a human task); LLM-based post-correction of OCR text is deferred to its own design conversation after real error patterns are visible, because a model "correcting" text can silently rewrite it — methodologically delicate for a corpus.

## 5. Risks and edge cases

- **Binarization is the highest-risk preprocessing step.** Thin strokes of faint characters die under thresholding, and a character minus one stroke is a *different valid character* — undetectable downstream. Use adaptive methods (Sauvola), A/B every recipe against ground truth, and always test a "no binarization" recipe (modern engines often prefer grayscale).
- **Layout analysis will fail more often than character recognition.** Multi-column reading order, text wrap around images, pull-quotes, vertical passages inside horizontal pages. Scrambled reading order is corrosive to an analysis corpus even when every character is right. Strongest argument for the T3 cloud tier (VLMs handle reading order well). Expect layout, not recognition, to dominate errors on visually clean pages.
- **Script and variant characters.** Per-page script detection can err; engines silently normalize variants (旣→既, 爲→為/为). **Glyph policy (decided):** store what the OCR produced, record script per page, normalize only as an export-time option — keeps the decision reversible.
- **Photocopy-specific degradation:** gutter shadows and dark edges (mask carefully — spine-adjacent text is real), bleed-through OCR'd as garbage, moiré from screened images, duplicated/skipped pages from the copying process (caught at ingest/catalog).
- **Cloud model drift:** a T3 run made in 2026 is not re-runnable in 2028. Mitigation: manifests record model ID + date; all raw outputs kept forever — the data stays reproducible even when the process isn't.
- **Human-correction bottleneck:** ground-truthing 30–50 pages of dense Chinese text is real hours; it is explicitly budgeted, as it underwrites every accuracy claim.

## 6. Evaluation criteria

| Skill | Working well means |
|---|---|
| ingest | 100% of source PDFs cataloged or explicitly logged failed/duplicate with reason; checksums verify; page counts match; re-run is a no-op |
| assess | On a random 30-page sample, detected skew/script/orientation agree with human judgment ≥95%; fast enough to run first on any archive |
| triage | Calibration: ≥90% of T1 pages truly acceptable CER; T4 catches everything weird |
| preprocess | A recipe is good iff it reduces CER on ground truth vs. raw images, same engine — measured, never visual-prettiness |
| ocr | Local re-OCR beats run 0 on T2; cloud beats local on T3; interrupted runs resume without loss/duplication. Target: **median CER ≤ 2% on T1–T3 pages** |
| compare | Automatic winner agrees with true best run ≥90% on ground truth; disagreements surfaced |
| evaluate | Calibrated proxy metrics measurably correlate with true CER (correlation itself reported — a methods-section detail) |
| export | PDFs open everywhere; search finds known text; text layer aligns with image; corpus files carry complete provenance headers |

**Corpus-level acceptance:** the evidenced statement "X% of pages meet CER ≤ Y" — a sentence that goes directly into a methods section.

## 7. Build order

1. **Phase 1 — See the corpus:** `corpus-ingest`, then `corpus-assess`. Forces the data model to be real; produces a quality report over all pages. Highest information value per hour — may revise the 70% estimate in either direction and reshape later phases.
2. **Phase 2 — Establish ground truth:** `corpus-evaluate` (sampling + measurement). Stratified ~30–50 page sample, hand-corrected; run 0 measured against it *before any re-OCR* — the baseline for every later improvement claim. Calibrates proxy metrics early.
3. **Phase 3 — Improvement loop:** `corpus-preprocess`, `corpus-ocr`, `corpus-triage`, exercised on the ground-truth sample first (recipes × engines on ~40 pages, measure, pick winners, set thresholds from evidence), then bulk. Full-corpus runs happen exactly once, with defensible settings.
4. **Phase 4 — Selection and deliverables:** `corpus-compare`, `corpus-export`.

Coordinator/app layer: designed after Phase 4 from actual usage.

## 8. Decisions

**Decided:**

1. **Workspace location:** C: drive on this machine (225 GB free; estimated footprint 30–80 GB). Source PDFs staged in `incoming\` under the repo root; the copy remaining on the professor's other computer serves as the off-machine backup of originals. Irreplaceable artifacts: `originals/`, `catalog.db`, `ground_truth/`, `ocr/runs/`. Regenerable: `pages/`, `preprocessed/`.
2. **Glyph policy:** store as-OCR'd; normalize at export time only.

3. **Rendering DPI:** resolved — scans are native 300 DPI embedded images; extract losslessly rather than re-render.
4. **Sample-PDF review:** done 2026-07-12; findings in §0.

**Pending (none block Phase 1 implementation start):**

5. **Cloud provider/budget for T3:** Claude vision API is the natural fit; budget decision deferred until assess reveals the size of the T3 population.
6. **Ground-truth transcription protocol:** one-page written convention (illegible-character placeholder `□`, line breaks, punctuation variants) to be drafted and agreed before correcting page one. Draft: `docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`.
