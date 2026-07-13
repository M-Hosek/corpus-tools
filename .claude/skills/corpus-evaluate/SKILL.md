---
name: corpus-evaluate
description: Ground-truth workflow and CER measurement — select the stratified transcription sample, track hand-correction progress, evaluate an OCR run against ground truth, and generate the evaluation report. Use when the user wants to pick ground-truth pages, check transcription status, or measure OCR accuracy (CER).
---

# corpus-evaluate

Thin orchestrator over `corpus_tools`. Workspace: `workspace/` at the repo root
(ask if a different one is meant).

## Workflow

1. **Select the sample** (once, after the corpus is fully ingested and assessed):
   `python -m corpus_tools gt-sample --workspace workspace --n 40`
   Deterministic stratified sample (issue × script × quality band). Additive:
   re-running never removes or overwrites anything. Drafts seeded from run-0
   text land in `workspace/ground_truth/drafts/`.

2. **Hand-correction (human loop):** the user corrects each draft against the
   page image in `workspace/pages/` per
   `docs/superpowers/specs/2026-07-12-ground-truth-protocol.md`, saving the
   final transcription as `workspace/ground_truth/<page-id>.txt`.
   When helping, show the page image alongside the draft; never silently
   "fix" text yourself — anchoring bias is the main quality risk.

3. **Check progress:**
   `python -m corpus_tools gt-status --workspace workspace`

4. **Evaluate a run** (baseline is run0):
   `python -m corpus_tools evaluate --workspace workspace --run run0`

5. **Report:**
   `python -m corpus_tools eval-report --workspace workspace --run run0`
   Open `workspace/reports/eval_run0.html`; relay median CER, worst pages, and
   the quality-score calibration (Pearson r) to the user.

## Notes

- CER is whitespace-insensitive (line breaks don't count as errors).
- Evaluations are re-runnable: fixing a GT file and re-running `evaluate`
  overwrites the old value.
- Exit code 1 means errors were printed — surface them, don't ignore.
