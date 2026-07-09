#!/usr/bin/env python3
"""Audit the "redirects" array in docs.json for four problem classes:

  shadowing         source matches a live nav-reachable page (exact, or a
                    :param*/:param wildcard source that covers live pages),
                    so the redirect can mask real content
  dead_destination  destination (anchor/query stripped, one redirect hop
                    resolved) is not a live page, not an orphan .mdx on disk,
                    not an external URL, and not a wildcard whose literal
                    base tree contains a live page
  duplicates        the same source appears more than once
  chains            destination is itself a redirect source (extra hop);
                    self-loops are flagged

Usage:
    python scripts/inventory/redirect_audit.py [--json] [--limit N]

Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import sys

import _lib


def _hop(dest: str, exact_sources: dict[str, str],
         wildcards: list[tuple[dict, object]]) -> str:
    """Resolve one redirect hop for a normalized internal destination."""
    if dest in exact_sources:
        return _lib.normalize_path(exact_sources[dest])
    for redirect, pattern in wildcards:
        if pattern.match(dest):
            # Substitute a single trailing catch-all when both sides use one.
            src_base = _lib.wildcard_base(redirect["source"])
            dst = _lib.normalize_path(redirect["destination"])
            if _lib.is_wildcard(dst):
                rest = dest[len(src_base):].lstrip("/") if src_base else dest
                return f"{_lib.wildcard_base(dst)}/{rest}".strip("/")
            return dst
    return dest


def build_report(ctx: _lib.Context) -> dict:
    redirects = ctx.docs_json.get("redirects", [])
    live = ctx.live_pages
    orphans = ctx.orphan_pages

    exact_sources: dict[str, str] = {}
    wildcards: list[tuple[dict, object]] = []
    seen_sources: dict[str, list[str]] = {}
    for r in redirects:
        src = _lib.normalize_path(r["source"])
        seen_sources.setdefault(src, []).append(r["destination"])
        if _lib.is_wildcard(r["source"]):
            wildcards.append((r, _lib.compile_source_pattern(r["source"])))
        else:
            exact_sources.setdefault(src, r["destination"])

    shadowing = []
    dead = []
    chains = []
    for r in redirects:
        src = _lib.normalize_path(r["source"])
        raw_dest = r["destination"]

        # (a) shadowing
        if _lib.is_wildcard(r["source"]):
            pattern = _lib.compile_source_pattern(r["source"])
            hits = sorted(p for p in live if pattern.match(p))
            if hits:
                shadowing.append({
                    "source": r["source"], "destination": raw_dest,
                    "live_pages_matched": len(hits), "sample": hits[:5],
                })
        elif src in live:
            shadowing.append({"source": r["source"], "destination": raw_dest,
                              "live_pages_matched": 1, "sample": [src]})

        if _lib.is_external(raw_dest):
            continue
        dest = _lib.normalize_path(raw_dest)

        # (d) chains (before hop resolution, so the hop itself is reported)
        next_dest = None
        if not _lib.is_wildcard(raw_dest):
            if dest in exact_sources:
                next_dest = exact_sources[dest]
            else:
                for wr, wp in wildcards:
                    if wp.match(dest):
                        next_dest = wr["destination"]
                        break
            if next_dest is not None:
                chains.append({
                    "source": r["source"], "destination": raw_dest,
                    "next_destination": next_dest,
                    "self_loop": _lib.normalize_path(next_dest) == src or dest == src,
                })

        # (b) dead destination
        if _lib.is_wildcard(raw_dest):
            base = _lib.wildcard_base(raw_dest)
            alive = any(p == base or p.startswith(base + "/") for p in live) \
                if base else bool(live)
            if not alive:
                dead.append({"source": r["source"], "destination": raw_dest,
                             "reason": f"no live page under wildcard base '/{base}'"})
            continue
        final = _hop(dest, exact_sources, wildcards)
        if not final or _lib.is_external(final):
            continue  # site root or external
        if _lib.is_wildcard(final):
            base = _lib.wildcard_base(final)
            if any(p == base or p.startswith(base + "/") for p in live):
                continue
        if final in live:
            continue
        if final in orphans or _lib.slug_file(final):
            continue
        entry = {"source": r["source"], "destination": raw_dest,
                 "reason": "no live page, no file on disk"}
        if final != dest:
            entry["resolved_via_hop_to"] = "/" + final
        dead.append(entry)

    duplicates = [{"source": "/" + src, "destinations": dests}
                  for src, dests in sorted(seen_sources.items())
                  if len(dests) > 1]

    return {
        "counts": {
            "redirects": len(redirects),
            "shadowing": len(shadowing),
            "dead_destination": len(dead),
            "duplicates": len(duplicates),
            "chains": len(chains),
        },
        "shadowing": shadowing,
        "dead_destination": dead,
        "duplicates": duplicates,
        "chains": chains,
    }


def main(argv=None) -> int:
    args = _lib.make_parser(__doc__.split("\n")[0]).parse_args(argv)
    report = build_report(_lib.Context())

    _lib.print_counts(report["counts"])
    _lib.print_list(
        "Shadowing (source covers a live page)",
        [f"{s['source']} -> {s['destination']}  (masks {s['live_pages_matched']}: {', '.join(s['sample'][:2])}...)"
         for s in report["shadowing"]], args.limit)
    _lib.print_list(
        "Dead destinations",
        [f"{d['source']} -> {d['destination']}" for d in report["dead_destination"]],
        args.limit)
    _lib.print_list(
        "Duplicate sources",
        [f"{d['source']}  -> {d['destinations']}" for d in report["duplicates"]],
        args.limit)
    _lib.print_list(
        "Chains (destination is itself redirected)",
        [f"{c['source']} -> {c['destination']} -> {c['next_destination']}"
         + ("  [SELF-LOOP]" if c["self_loop"] else "")
         for c in report["chains"]], args.limit)

    if args.json:
        path = _lib.write_report("redirect_audit", report)
        print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
