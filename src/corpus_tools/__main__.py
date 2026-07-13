from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="corpus_tools")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace")
    p.add_argument("workspace", type=Path)
    p.add_argument("--name", required=True)

    p = sub.add_parser("ingest", help="ingest a folder of source PDFs")
    p.add_argument("source", type=Path)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None, help="max PDFs (for smoke tests)")

    p = sub.add_parser("assess", help="measure page quality metrics")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="re-assess already-assessed pages")

    p = sub.add_parser("report", help="write assessment HTML report")
    p.add_argument("--workspace", type=Path, required=True)

    p = sub.add_parser("gt-sample", help="select ground-truth sample and scaffold drafts")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=1979)

    p = sub.add_parser("gt-status", help="sync ground-truth completion status")
    p.add_argument("--workspace", type=Path, required=True)

    p = sub.add_parser("evaluate", help="compute CER for a run against ground truth")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--run", required=True)

    p = sub.add_parser("eval-report", help="write evaluation HTML report")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--run", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "init":
        from .workspace import init_workspace
        ws = init_workspace(args.workspace, args.name)
        print(f"workspace ready at {ws.root}")
    elif args.cmd == "ingest":
        from .ingest import ingest_folder
        from .workspace import load_workspace
        ws = load_workspace(args.workspace)
        stats = ingest_folder(ws, args.source, limit=args.limit)
        print(f"new sources: {stats['sources_new']}  skipped: {stats['sources_skipped']}  "
              f"pages: {stats['pages']}  errors: {len(stats['errors'])}")
        for e in stats["errors"]:
            print("ERROR:", e)
        if stats["errors"]:
            return 1
    elif args.cmd == "assess":
        from .assess_run import assess_workspace
        from .workspace import load_workspace
        ws = load_workspace(args.workspace)
        stats = assess_workspace(ws, limit=args.limit, force=args.force)
        print(f"assessed: {stats['assessed']}  errors: {len(stats['errors'])}")
        for e in stats["errors"]:
            print("ERROR:", e)
        if stats["errors"]:
            return 1
    elif args.cmd == "report":
        from .report import write_assess_report
        from .workspace import load_workspace
        out = write_assess_report(load_workspace(args.workspace))
        print(f"report: {out}")
    elif args.cmd == "gt-sample":
        from .gt import scaffold_sample
        from .workspace import load_workspace
        stats = scaffold_sample(load_workspace(args.workspace), n=args.n, seed=args.seed)
        print(f"selected: {stats['selected']}  already: {stats['already']}  "
              f"drafts: {stats['drafts_written']}")
    elif args.cmd == "gt-status":
        from .gt import sync_gt_status
        from .workspace import load_workspace
        stats = sync_gt_status(load_workspace(args.workspace))
        print(f"done: {stats['done']}  selected: {stats['selected']}  "
              f"adopted: {stats['adopted']}")
        for name in stats["strays"]:
            print("STRAY FILE (not a page):", name)
    elif args.cmd == "evaluate":
        from .evaluate import evaluate_run
        from .workspace import load_workspace
        stats = evaluate_run(load_workspace(args.workspace), args.run)
        print(f"evaluated: {stats['evaluated']}  skipped: {len(stats['skipped'])}  "
              f"errors: {len(stats['errors'])}")
        for pid in stats["skipped"]:
            print("SKIPPED:", pid)
        for e in stats["errors"]:
            print("ERROR:", e)
        if stats["errors"]:
            return 1
    elif args.cmd == "eval-report":
        from .report_eval import write_eval_report
        from .workspace import load_workspace
        out = write_eval_report(load_workspace(args.workspace), args.run)
        print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
