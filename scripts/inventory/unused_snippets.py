#!/usr/bin/env python3
"""Report _snippets/ files included by zero nav-reachable pages.

Inclusion is <Snippet file="name.mdx" /> (file attr relative to _snippets/,
subdirs allowed) and is followed transitively: snippets can include snippets.
A snippet whose only route to a page goes through orphan pages is UNUSED;
each unused snippet is classified as "used_only_by_orphans" (with the orphan
pages that use it) or "used_by_nothing" (no page reaches it at all, though
other dead snippets may still include it).

Also reports dangling includes: <Snippet file="..."> refs with no file on disk.

Usage:
    python scripts/inventory/unused_snippets.py [--json] [--limit N]

Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import sys

import _lib


def build_report(ctx: _lib.Context) -> dict:
    snippets = set(ctx.snippet_files)
    live = ctx.live_pages
    orphans = ctx.orphan_pages

    # Invert the page -> transitive-snippets relation.
    users: dict[str, set[str]] = {s: set() for s in snippets}
    for slug, rel in ctx.page_files.items():
        for snip in ctx.snippets_of(rel):
            users.setdefault(snip, set()).add(slug)

    # Which snippets include which (for used_by_nothing context).
    included_by: dict[str, set[str]] = {s: set() for s in snippets}
    for src in sorted(snippets):
        for snip in ctx.snippet_direct.get(src, []):
            if snip in included_by:
                included_by[snip].add(src)

    unused = []
    n_orphan_only = n_nothing = 0
    for snip in sorted(snippets):
        pages = users.get(snip, set())
        if pages & live:
            continue
        if pages:
            n_orphan_only += 1
            unused.append({
                "snippet": snip,
                "status": "used_only_by_orphans",
                "orphan_pages": sorted(p + ".mdx" for p in pages),
            })
        else:
            n_nothing += 1
            entry = {"snippet": snip, "status": "used_by_nothing"}
            if included_by[snip]:
                entry["included_only_by_dead_snippets"] = sorted(included_by[snip])
            unused.append(entry)

    dangling = sorted({
        f"{src} -> {snip}"
        for src, refs in ctx.snippet_direct.items()
        for snip in refs
        if not (_lib.DOCS_ROOT / snip).is_file()
    })

    return {
        "counts": {
            "snippet_files": len(snippets),
            "used_by_live_pages": len(snippets) - n_orphan_only - n_nothing,
            "unused_total": n_orphan_only + n_nothing,
            "used_only_by_orphans": n_orphan_only,
            "used_by_nothing": n_nothing,
            "dangling_includes": len(dangling),
        },
        "unused_snippets": unused,
        "dangling_includes": dangling,
    }


def main(argv=None) -> int:
    args = _lib.make_parser(__doc__.split("\n")[0]).parse_args(argv)
    report = build_report(_lib.Context())

    _lib.print_counts(report["counts"])
    items = [f"{u['snippet']}  [{u['status']}]" for u in report["unused_snippets"]]
    _lib.print_list("Unused snippets", items, args.limit)
    if report["dangling_includes"]:
        _lib.print_list("Dangling <Snippet> includes (no file on disk)",
                        report["dangling_includes"], args.limit)

    if args.json:
        path = _lib.write_report("unused_snippets", report)
        print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
