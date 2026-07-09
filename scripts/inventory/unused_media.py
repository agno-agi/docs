#!/usr/bin/env python3
"""Report files under images/ and videos/ referenced by zero files in the repo.

References are found by scanning every .mdx, .md, .css, .js, .json, and .html
file (docs.json included) for substrings that look like media paths
(images/... or videos/...), which covers src= attributes, markdown image
syntax, frontmatter fields, docs.json logo/favicon/og values, and plain path
mentions. Matching is on the path suffix, so "/images/foo.png",
"images/foo.png", and "https://host/images/foo.png" all count.

Usage:
    python scripts/inventory/unused_media.py [--json] [--limit N]

Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import re
import sys

import _lib

MEDIA_DIRS = ("images/", "videos/")
# A media-ish path: starts at images/ or videos/, runs until a character that
# cannot be part of a path in any of the scanned syntaxes.
MEDIA_REF_RE = re.compile(r"(?:images|videos)/[^\s\"'()<>\[\]{}`\\,;|]+")
CORPUS_EXTS = (".mdx", ".md", ".css", ".js", ".json", ".html")


def build_report(ctx: _lib.Context) -> dict:
    media = [f for f in ctx.files if f.startswith(MEDIA_DIRS)]
    corpus = [f for f in ctx.files
              if f.endswith(CORPUS_EXTS) and not f.startswith(MEDIA_DIRS)]

    referenced: set[str] = set()
    for rel in corpus:
        for m in MEDIA_REF_RE.findall(_lib.read_text(rel)):
            referenced.add(m.rstrip(".,:;!?*"))

    unused = []
    total_bytes = 0
    for rel in sorted(media):
        if rel in referenced:
            continue
        size = (_lib.DOCS_ROOT / rel).stat().st_size
        total_bytes += size
        unused.append({"file": rel, "bytes": size})

    return {
        "counts": {
            "media_files": len(media),
            "referenced": len(media) - len(unused),
            "unused": len(unused),
            "reclaimable_bytes": total_bytes,
        },
        "reclaimable_human": _lib.human_bytes(total_bytes),
        "unused_files": unused,
    }


def main(argv=None) -> int:
    args = _lib.make_parser(__doc__.split("\n")[0]).parse_args(argv)
    report = build_report(_lib.Context())

    _lib.print_counts(report["counts"])
    print(f"  reclaimable        {report['reclaimable_human']}")
    items = [f"{u['file']}  ({_lib.human_bytes(u['bytes'])})"
             for u in report["unused_files"]]
    _lib.print_list("Unused media files", items, args.limit)

    if args.json:
        path = _lib.write_report("unused_media", report)
        print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
