#!/usr/bin/env python3
"""Report every .mdx page not reachable from docs.json navigation (orphans),
and every navigation entry with no file on disk (the reverse check).

Pages are .mdx files anywhere in the repo except _snippets/ and anything
gitignored (agno/ symlink, node_modules, ...). A nav entry "foo/bar" maps to
foo/bar.mdx (or foo/bar.md).

Usage:
    python scripts/inventory/orphans.py [--json] [--limit N]

Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import sys

import _lib


def build_report(ctx: _lib.Context) -> dict:
    orphans = sorted(ctx.orphan_pages)
    missing = sorted(ctx.nav_missing_file)
    return {
        "counts": {
            "mdx_pages_on_disk": len(ctx.page_files),
            "nav_entries_total": len(ctx.nav_entries),
            "nav_entries_unique": len(ctx.nav_set),
            "nav_reachable_pages": len(ctx.live_pages),
            "orphan_pages": len(orphans),
            "nav_entries_missing_file": len(missing),
        },
        "orphan_pages": [s + ".mdx" for s in orphans],
        "nav_entries_missing_file": missing,
    }


def main(argv=None) -> int:
    args = _lib.make_parser(__doc__.split("\n")[0]).parse_args(argv)
    report = build_report(_lib.Context())

    _lib.print_counts(report["counts"])
    _lib.print_list("Orphan pages (on disk, not in docs.json navigation)",
                    report["orphan_pages"], args.limit)
    _lib.print_list("Nav entries with no file on disk",
                    report["nav_entries_missing_file"], args.limit)

    if args.json:
        path = _lib.write_report("orphans", report)
        print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
