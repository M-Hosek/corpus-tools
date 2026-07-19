# corpus_tools — OCR Remediation Pipeline for Scanned Archival Corpora

A pipeline for turning ~3,900 pages of scanned, photocopied Chinese science-fiction
magazines (科学文艺 1979–1988, 少年科技 1977) with ~70%-accurate scanner OCR into an
analysis-grade text corpus. Built as a reusable Python package (`corpus_tools`)
driven by a small CLI, with Claude Code skills as thin orchestrators on top.

## Table of contents

- [Project goals](#project-goals)
- [Architecture at a glance](#architecture-at-a-glance)
- [Repository layout](#repository-layout)
- [Installation](#installation)
- [The workspace](#the-workspace)
- [The catalog (SQLite data model)](#the-catalog-sqlite-data-model)
- [Pipeline stages](#pipeline-stages)
  - [1. init — create a workspace](#1-init--create-a-workspace)
  - [2. ingest — PDFs in, pages out](#2-ingest--pdfs-in-pages-out)
  - [3. assess — per-page quality metrics](#3-assess--per-page-quality-metrics)
  - [4. report — assessment HTML report](#4-report--assessment-html-report)
  - [5. gt-sample — select the ground-truth sample](#5-gt-sample--select-the-ground-truth-sample)
  - [6. Hand-correction (the human loop)](#6-hand-correction-the-human-loop)
  - [7. gt-status — track transcription progress](#7-gt-status--track-transcription-progress)
  - [8. evaluate — CER against ground truth](#8-evaluate--cer-against-ground-truth)
  - [9. eval-report — evaluation HTML report](#9-eval-report--evaluation-html-report)
- [Key algorithms](#key-algorithms)
  - [Spread splitting (gutter detection)](#spread-splitting-gutter-detection)
  - [Run-0 text splitting](#run-0-text-splitting)
  - [Quality score](#quality-score)
  - [Script detection](#script-detection)
  - [Character error rate (CER)](#character-error-rate-cer)
  - [Stratified sampling](#stratified-sampling)
- [Design principles](#design-principles)
- [Claude Code skills](#claude-code-skills)
- [Testing](#testing)
- [Current status](#current-status)
- [Roadmap](#roadmap)

## Project goals

The source material is 231 PDFs (~5.7 GB) of flatbed scans of bound magazines.
Each PDF page is a **two-page spread** photographed at 300 DPI. The scanner
embedded an OCR text layer of roughly 70% character accuracy — good enough to
locate articles, nowhere near good enough for text analysis.

The pipeline exists to close that gap:

1. **Ingest** every scan losslessly and split spreads into individual pages.
2. **Assess** every page's physical quality so effort can be triaged.
3. **Measure** OCR accuracy rigorously against hand-corrected ground truth
   (target: median CER ≤ 2% on all but the hardest pages).
4. **Re-OCR** pages locally (PaddleOCR, CPU-only) and escalate only the hardest
   pages to manual transcription — no paid API OCR.
5. **Export** normalized, analysis-ready text.

Full design rationale: `docs/superpowers/specs/2026-07-12-ocr-corpus-pipeline-design.md`.
Ground-truth transcription protocol: `docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`.

## Architecture at a glance

```
incoming/  (read-only source PDFs)
    │
    ▼
┌────────────────────────────────────────────────────┐
│ corpus_tools (Python package, all logic lives here)│
│   CLI: python -m corpus_tools <subcommand>         │
└────────────────────────────────────────────────────┘
    │ writes
    ▼
workspace/                 file-based corpus workspace
├── catalog.db             SQLite catalog (single source of truth)
├── catalog_audit.log      append-only JSON log of every catalog write
├── originals/             checksummed copies of source PDFs (immutable)
├── pages/                 one PNG per split page
├── ocr/runs/run0/         embedded scanner OCR text, one .txt per page
├── ground_truth/          hand-corrected transcriptions + drafts/
├── reports/               generated HTML reports
├── preprocessed/          (Phase 3) cleaned page images
└── rebuilt/               (Phase 4) exported text
```

Three ideas hold this together:

- **The page is the atomic unit.** Every artifact — image, OCR text, quality
  metrics, ground truth, evaluation — keys off a stable `page_id`.
- **OCR output is an immutable, versioned "run".** The scanner's embedded text
  layer is ingested as `run0`; every future OCR attempt becomes `run1`, `run2`, …
  with its engine and parameters recorded. Runs are compared, never overwritten.
- **Skills orchestrate; the package computes.** The Claude Code skills
  (`corpus-ingest`, `corpus-assess`, `corpus-evaluate`) contain no logic — they
  run the CLI, verify results, and report. Everything testable lives in
  `src/corpus_tools/`.

## Repository layout

```
pdf_processing/
├── src/corpus_tools/
│   ├── __main__.py      CLI entry point (argparse, all subcommands)
│   ├── workspace.py     Workspace class, init/load, directory layout
│   ├── catalog.py       SQLite schema + audited write API
│   ├── ingest.py        PDF → originals copy, spread split, page PNGs, run0
│   ├── pdfio.py         pypdf helpers: page count, lossless image extraction
│   ├── spreads.py       gutter detection and spread splitting (OpenCV)
│   ├── run0.py          embedded OCR text extraction, split at the gutter
│   ├── assess.py        page metrics, script detection, quality score
│   ├── assess_run.py    assessment batch driver (resumable)
│   ├── report.py        assessment HTML report
│   ├── sampling.py      deterministic stratified sampling for ground truth
│   ├── gt.py            GT sample scaffolding + status sync
│   ├── metrics.py       whitespace-insensitive CER with edit-op counts
│   ├── evaluate.py      CER evaluation of a run against ground truth
│   └── report_eval.py   evaluation HTML report (stratified CER, calibration)
├── tests/               pytest suite (one test module per source module)
├── docs/superpowers/
│   ├── specs/           design spec + ground-truth protocol
│   └── plans/           phase implementation plans
├── .claude/skills/      corpus-ingest / corpus-assess / corpus-evaluate
├── incoming/            source scans (never modified, gitignored)
└── workspace/           the live corpus workspace (gitignored)
```

## Installation

Requires Python ≥ 3.12. Dependencies: `pypdf`, `Pillow`, `numpy`,
`opencv-python-headless`, `PyYAML` (and `pytest` for development).

```
pip install -e .[dev]
```

All commands below are run from the repo root; the live workspace is
`workspace/`.

## The workspace

A workspace is a plain directory created by `init`. `workspace.yaml` marks the
root and records the corpus name and native DPI (300). Everything the pipeline
produces lives under it; nothing outside it is ever written.

Two files matter most:

- **`catalog.db`** — the SQLite catalog. Every query about the corpus starts
  here.
- **`catalog_audit.log`** — an append-only JSONL log. Every write the catalog
  API performs (`upsert_source`, `add_page`, `update_page`, …) is recorded with
  a timestamp and its full payload, so the catalog's history is reconstructable
  and mistakes are diagnosable after the fact.

### Page identity

```
page_id = <first 6 hex chars of source PDF SHA-256>-p<NNN><side>
          e.g.  ca4071-p012R
```

- The hash prefix ties a page permanently to the exact bytes of its source PDF.
- `NNN` is the 1-based PDF page (spread) index.
- `side` is `L` / `R` for a split spread, or `F` (full) when no gutter was
  found — covers, foldouts, single-page scans.

## The catalog (SQLite data model)

| Table | One row per | Purpose |
|---|---|---|
| `sources` | source PDF | checksum identity, original path, issue label, page count, embedded-OCR flag |
| `pages` | split page | image path, dimensions, all assessment metrics, triage tier, issue label |
| `ocr_runs` | OCR attempt | engine, version, parameters, recipe; `run0` = scanner-embedded OCR |
| `run_pages` | (run, page) | path to that run's text for that page, char count, confidence |
| `gt_pages` | ground-truth page | stratum, status (`selected` → `done`), timestamps |
| `evaluations` | (run, page, metric) | metric value (e.g. CER) + details JSON (edit-op counts) |

Guard rails built into `catalog.py`:

- `update_page` only accepts a whitelisted set of mutable columns — identity
  fields (`page_id`, `source_id`, `side`, …) cannot be changed after insert.
- Page and run-page inserts are `INSERT OR IGNORE`; evaluations are
  `INSERT OR REPLACE` (re-evaluating after fixing a GT file overwrites the old
  value, by design).
- Every write is audited (see above).

## Pipeline stages

### 1. `init` — create a workspace

```
python -m corpus_tools init <workspace-path> --name <corpus-name>
```

Creates the directory tree, `workspace.yaml`, and the catalog schema.
Idempotent.

### 2. `ingest` — PDFs in, pages out

```
python -m corpus_tools ingest "incoming/sf magazines 2025" --workspace workspace [--limit N]
```

For each PDF found recursively under the source folder:

1. **Checksum** the file (SHA-256). Already-cataloged checksums are skipped
   entirely, so re-running on the same folder is always safe.
2. **Copy** it into `originals/<issue>/` (never moved, never modified). If a
   different file with the same name already exists there, the copy is
   disambiguated with a hash suffix rather than overwritten.
3. For each PDF page: **extract the embedded scan image losslessly** (no
   re-rendering — the largest embedded image is taken, with a guard that
   refuses multi-strip pages rather than silently dropping content),
   **split the spread** at the gutter, and save one PNG per side to `pages/`.
4. **Extract the embedded OCR text**, split at the same gutter x-coordinate,
   and store it as run `run0` — one `.txt` per page under `ocr/runs/run0/`.
5. Record everything in the catalog.

Errors on one PDF never stop the batch; they are collected and printed, and
the CLI exits 1 if any occurred. Ingest is resumable mid-PDF: a page is only
skipped if its catalog rows, PNG(s), and run-0 text files all exist (a lone
`L` without its `R` from an interrupted run is detected and redone).

Throughput: roughly 10–20 s per PDF on the current (CPU-only) machine.

### 3. `assess` — per-page quality metrics

```
python -m corpus_tools assess --workspace workspace [--limit N] [--force]
```

Measures every not-yet-assessed page (resumable; `--force` re-does all) and
writes the metrics onto the page row:

| Metric | Meaning |
|---|---|
| `skew_deg` | page rotation, estimated by maximizing row-profile sharpness over ±3° |
| `contrast` | 5th-to-95th percentile gray spread |
| `background_gray` | median gray of non-ink pixels |
| `ink_density` | fraction of ink pixels (Otsu threshold) |
| `noise` | residual std after median filtering |
| `script` | `simplified` / `traditional` / `unknown`, from run-0 text |
| `garbage_ratio` | fraction of run-0 characters outside expected CJK/ASCII ranges |
| `quality_score` | weighted 0–1 composite (see below) |

Roughly 1–3 s per page; a full-corpus pass is an hours-long background job.

### 4. `report` — assessment HTML report

```
python -m corpus_tools report --workspace workspace
```

Writes `workspace/reports/assess_report.html`: quality-score distribution,
script breakdown, per-issue statistics, and a gallery of the lowest-quality
pages for eyeball verification (blank pages? failed splits? upside-down scans?).

### 5. `gt-sample` — select the ground-truth sample

```
python -m corpus_tools gt-sample --workspace workspace --n 40 [--seed 1979]
```

Selects a deterministic stratified sample of assessed pages (see
[Stratified sampling](#stratified-sampling)), registers them in `gt_pages`, and
scaffolds two files per page in `ground_truth/drafts/`:

- `<page_id>.txt` — a draft **seeded from the run-0 text** (the transcriber
  corrects rather than types from scratch);
- `<page_id>.notes.md` — a notes template (date, method, confidence, remarks).

The command is **additive**: re-running never removes or overwrites anything;
already-selected pages are counted as `already` and existing drafts are left
untouched.

### 6. Hand-correction (the human loop)

For each sampled page, the transcriber corrects the draft against the page
image in `workspace/pages/` following the protocol in
`docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`, then saves the
final transcription as `workspace/ground_truth/<page_id>.txt` (drafts stay in
`drafts/`).

Core protocol rules: transcribe **as printed** (no normalization, no fixing the
magazine's own typos), and never let an assistant silently "improve" the text —
anchoring on OCR output is the main quality risk.

### 7. `gt-status` — track transcription progress

```
python -m corpus_tools gt-status --workspace workspace
```

Scans `ground_truth/` and syncs the catalog: non-empty final files flip their
page to `done`; final files for valid pages that were never formally sampled
are **adopted** into the GT set; files whose name is not a known page id are
reported as strays (and left alone).

### 8. `evaluate` — CER against ground truth

```
python -m corpus_tools evaluate --workspace workspace --run run0
```

For every `done` GT page, computes the character error rate of that run's text
against the ground truth and stores it (with substitution / deletion /
insertion counts) in `evaluations`. Pages the run has no text for are reported
as skipped. Re-running after fixing a GT file overwrites the stored value.

### 9. `eval-report` — evaluation HTML report

```
python -m corpus_tools eval-report --workspace workspace --run run0
```

Writes `workspace/reports/eval_<run>.html`: overall and per-stratum CER
(median, spread, worst pages), error-type breakdown, and a **calibration
check** — the Pearson correlation between each page's assessment
`quality_score` and its measured CER, which tells us whether the cheap image
metrics actually predict OCR difficulty (and can therefore be trusted for
triage).

## Key algorithms

### Spread splitting (gutter detection)

`spreads.py`. The content bounding box is found by Otsu thresholding plus
morphological opening; a region narrower than 1.1× its height is treated as a
single page (`F`), not a spread. Two complementary detectors then look for the
gutter in the central 35–65% band:

1. **Dark-valley detector** — for grayscale photocopies, the binding casts a
   shadow: the smoothed column-mean profile dips at least 20 gray levels below
   the page median. To reject dense ink columns (tables, bold headings) that
   also average dark, the candidate's *vertical* pixel std must be ≤ 60 — a
   real shadow is continuous-tone top to bottom (measured ~20–40 on real
   scans), while ink texture measures far higher (~124).
2. **Ink-valley detector** (fallback) — bilevel 0/255 scans (e.g. the 1979.1
   batch) have no shadow at all; their gutter is a *bright* band. This detector
   finds a wide run (≥ 1.5% of content width, ≥ 20 px) of near-zero ink
   density, wide enough that inter-column text gaps don't qualify, and cuts at
   the run's point nearest the content center. Blank regions are rejected
   (a valley proves nothing without ink around it).

If neither fires, the page is stored whole as side `F`.

### Run-0 text splitting

`run0.py`. The embedded OCR layer belongs to the whole spread, so it must be
split at the same gutter. pypdf's `extract_text` visitor reports each text
fragment's transform matrix; the fragment's x-position in PDF points is
compared against the gutter pixel column converted to points, assigning it to
the left or right page.

### Quality score

`assess.py`:

```
quality_score = 0.35 · min(contrast/180, 1)
             + 0.20 · (1 − min(noise/15, 1))
             + 0.15 · (1 − min(|skew|/3°, 1))
             + 0.30 · (1 − min(garbage_ratio/0.3, 1))
```

A 0–1 composite weighting image legibility (contrast, noise, skew) and run-0
text health (garbage ratio). It is intentionally cheap — its job is triage, and
the eval report's calibration section measures how well it predicts real CER.

### Script detection

`detect_script` counts characters from two disjoint sets of ideographs that
exist only in simplified or only in traditional form (国/國, 学/學, …). A page
needs ≥ 3 hits and a 2:1 majority to be classified; otherwise `unknown`.
In practice `unknown` means "run-0 text is empty or garbled" (blank pages,
covers, artwork — or text pages whose scanner OCR failed badly), not
"traditional script".

### Character error rate (CER)

`metrics.py`. Levenshtein distance over characters, **after stripping all
whitespace from both sides** — line breaks and spacing are layout, not content,
and must not count as errors. The DP tracks substitution / deletion / insertion
counts along the optimal path, so the eval report can say *how* a run fails,
not just how much. `CER = distance / len(reference)`; an empty reference is an
error (such pages are skipped in evaluation).

### Stratified sampling

`sampling.py`. Stratum = `issue_label × script × quality band`
(low < 0.5 ≤ mid < 0.75 ≤ high). Allocation: one slot per stratum first
(largest strata win when strata outnumber the sample size), remaining slots
proportional to stratum size. Selection within a stratum is
`random.Random(seed)` over pages sorted by id — **fully deterministic**: the
same corpus, `--n`, and `--seed` always select the same pages, so the sample is
reproducible and re-runs are no-ops.

## Design principles

- **Originals are read-only, forever.** Ingest copies; nothing downstream ever
  touches `originals/` or the `incoming/` source folder.
- **Everything is resumable.** Ingest, assessment, and sampling all detect
  existing work and continue; interrupting any batch loses at most one page of
  progress.
- **Store as printed, normalize at export.** OCR text and ground truth keep the
  glyphs the magazine printed; normalization (variant unification, punctuation)
  is deferred to the Phase 4 export step so no information is destroyed early.
- **Runs are immutable and comparable.** Each OCR attempt is a separate run
  with recorded parameters; evaluation makes runs comparable on identical
  ground truth.
- **Determinism where humans invest effort.** The GT sample is seeded and
  reproducible, because 40 hand-transcribed pages are the project's most
  expensive artifact.
- **Fail loudly, keep going.** Batch commands collect per-item errors, print
  them verbatim, and exit non-zero — one bad PDF never aborts a 231-PDF run,
  and errors are never summarized away.

## Claude Code skills

Thin orchestrators in `.claude/skills/`, meant to be invoked in Claude Code
sessions:

| Skill | Wraps | Adds |
|---|---|---|
| `corpus-ingest` | `init`, `ingest` | source-folder confirmation, error surfacing, catalog sanity checks (L/R/F shape) |
| `corpus-assess` | `assess`, `report` | background execution, report interpretation, lowest-quality-gallery eyeballing |
| `corpus-evaluate` | `gt-sample`, `gt-status`, `evaluate`, `eval-report` | the GT workflow script, anchoring-bias warnings, report relay |

## Testing

```
python -m pytest
```

73 tests, one module per source module (`tests/test_spreads.py`,
`tests/test_metrics.py`, …), covering gutter detection on synthetic spreads
(including the bilevel and dense-ink-column edge cases), CER edit-op
accounting, sampling determinism, ingest resume logic, GT adoption guards, and
both HTML reports.

A handful of integration tests use a real scanner-chunk PDF
(`tests/fixtures/sample_chunk.pdf`) that is **not distributed** with the
repository (the source scans are not redistributable); without it those tests
skip automatically and the rest of the suite runs normally.

## Current status

*(as of 2026-07-19)*

| Milestone | Status |
|---|---|
| Phase 1 — ingest + assess tooling | ✅ merged |
| Phase 2 — ground-truth & evaluation tooling | ✅ merged |
| Full corpus ingested | ✅ 231 PDFs → 1,994 spreads → 3,934 pages (1,940 L + 1,940 R + 54 F), 0 errors |
| Full corpus assessed | ✅ median quality 0.759; 90% simplified script; `unknown` ≈ blanks/covers/garbled run-0 |
| GT sample selected | ✅ 40 pages, all years 1977–1988, quality 0.662–0.816, drafts scaffolded |
| Hand-correction | ⏳ next — 0/40 done |
| run-0 baseline CER | ⏳ after transcription |

Notes: 1982 issues and scanner batch 0868 are absent from the source material
(expected). The 1979.1 batch is bilevel 0/255 — the reason the ink-valley
gutter detector exists.

## Roadmap

- **Phase 3 — preprocess / re-OCR / triage loop:** image cleanup (deskew,
  denoise, binarization recipes) into `preprocessed/`, local PaddleOCR runs
  (CPU, resumable batches) as `run1+`, triage tiers T1 (easy) → T4 (skip).
  Hard (T3) pages are transcribed manually in Claude Code sessions rather than
  paid API OCR; the T3 queue must be resumable across sessions.
- **Phase 4 — compare / export:** run comparison, best-text selection,
  normalization at export into `rebuilt/`.
- A coordinating app is deliberately deferred until one full manual pass of the
  pipeline is complete.
