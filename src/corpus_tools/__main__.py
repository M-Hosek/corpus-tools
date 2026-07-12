from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
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

    args = ap.parse_args()
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
    elif args.cmd == "assess":
        from .assess_run import assess_workspace
        from .workspace import load_workspace
        ws = load_workspace(args.workspace)
        stats = assess_workspace(ws, limit=args.limit, force=args.force)
        print(f"assessed: {stats['assessed']}  errors: {len(stats['errors'])}")
        for e in stats["errors"]:
            print("ERROR:", e)


if __name__ == "__main__":
    main()
