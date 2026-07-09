#!/usr/bin/env python3
"""Check internal links and anchors across all nav-reachable pages and the
_snippets/ files they include.

Links come from markdown [text](target) and href="target" where target starts
with "/" (root-relative internal). Code fences, inline code, and frontmatter
are ignored. Each link is classified as:

  broken                path is no live page, no orphan, no file on disk,
                        and no redirect covers it
  broken_anchor         path is fine but /page#anchor names no heading
                        (slugified GitHub/Mintlify style, including headings
                        in included snippets); reference-api/** targets are
                        skipped (generated pages)
  links_to_orphan       path is an .mdx on disk that navigation cannot reach
  resolves_via_redirect path only works because a redirect source (exact or
                        wildcard) covers it; works today, should be updated

Usage:
    python scripts/inventory/link_check.py [--json] [--limit N]

Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import sys

import _lib


def _iter_targets(rel: str):
    """Yield (line_number, raw_target) for internal link targets in rel."""
    seen = set()
    for i, line in enumerate(_lib.blank_noncontent_lines(_lib.read_text(rel)), 1):
        line = _lib.INLINE_CODE_RE.sub("", line)
        targets = [m.group(1).strip("<>") for m in _lib.MD_LINK_RE.finditer(line)]
        targets += _lib.HREF_RE.findall(line)
        for t in targets:
            if t.startswith("/") and not t.startswith("//") and (i, t) not in seen:
                seen.add((i, t))
                yield i, t


def build_report(ctx: _lib.Context) -> dict:
    live = ctx.live_pages
    orphans = ctx.orphan_pages
    redirects = ctx.docs_json.get("redirects", [])
    exact_sources = {}
    wildcard_sources = []
    for r in redirects:
        if _lib.is_wildcard(r["source"]):
            wildcard_sources.append((r, _lib.compile_source_pattern(r["source"])))
        else:
            exact_sources[_lib.normalize_path(r["source"])] = r["destination"]

    # Scan set: every live page plus every snippet a live page includes.
    scan: list[str] = []
    snippets_used: set[str] = set()
    for slug in sorted(live):
        rel = _lib.slug_file(slug)
        scan.append(rel)
        snippets_used |= ctx.snippets_of(rel)
    scan.extend(sorted(snippets_used))

    anchor_cache: dict[str, tuple[set, set]] = {}
    broken, broken_anchors, to_orphan, via_redirect = [], [], [], []
    checked = 0

    for rel in scan:
        for line, target in _iter_targets(rel):
            checked += 1
            path = _lib.normalize_path(target)
            anchor = target.split("#", 1)[1] if "#" in target else None
            entry = {"file": rel, "line": line, "target": target}

            if not path:  # "/" or "/#anchor": site root
                continue

            if path in live:
                if anchor and not path.startswith("reference-api/"):
                    if path not in anchor_cache:
                        anchor_cache[path] = _lib.page_anchors(
                            _lib.slug_file(path), ctx)
                    exact, loose = anchor_cache[path]
                    a = anchor.split("?")[0]
                    if a not in exact and _lib._loose(a) not in loose:
                        broken_anchors.append(entry)
                continue

            if not path.endswith((".mdx", ".md")) and (_lib.DOCS_ROOT / path).is_file():
                continue  # asset link (image, video, openapi.json, ...)

            if path in orphans:
                to_orphan.append(entry)
                continue

            redirected_to = None
            if path in exact_sources:
                redirected_to = exact_sources[path]
            else:
                for r, pattern in wildcard_sources:
                    if pattern.match(path):
                        redirected_to = r["destination"]
                        break
            if redirected_to is not None:
                via_redirect.append({**entry, "redirects_to": redirected_to})
                continue

            broken.append(entry)

    return {
        "counts": {
            "pages_scanned": len(live),
            "snippets_scanned": len(snippets_used),
            "internal_links_checked": checked,
            "broken_links": len(broken),
            "broken_anchors": len(broken_anchors),
            "links_to_orphan": len(to_orphan),
            "resolves_via_redirect": len(via_redirect),
        },
        "broken_links": broken,
        "broken_anchors": broken_anchors,
        "links_to_orphan": to_orphan,
        "resolves_via_redirect": via_redirect,
    }


def _fmt(entries):
    return [f"{e['file']}:{e['line']}  ->  {e['target']}" for e in entries]


def main(argv=None) -> int:
    args = _lib.make_parser(__doc__.split("\n")[0]).parse_args(argv)
    report = build_report(_lib.Context())

    _lib.print_counts(report["counts"])
    _lib.print_list("Broken links", _fmt(report["broken_links"]), args.limit)
    _lib.print_list("Broken anchors", _fmt(report["broken_anchors"]), args.limit)
    _lib.print_list("Links to orphan pages", _fmt(report["links_to_orphan"]), args.limit)
    _lib.print_list("Working only via redirect", _fmt(report["resolves_via_redirect"]),
                    args.limit)

    if args.json:
        path = _lib.write_report("link_check", report)
        print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
