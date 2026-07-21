#!/usr/bin/env python3
"""Post-generation pass: de-duplicate page titles within a nav group.

Generic docstring first lines ("Example AgentOS app where the agent has
MCPTools") repeat across sibling cookbook files and produce indistinguishable
sidebar entries. For every title that appears more than once within one nav
group, retitle ALL of its pages from the cookbook file stem (smart_title). If
stems still collide, prefix with the parent directory title. Placeholder
descriptions that embed the old title are updated to match.

Idempotent and deterministic; run after drive_sync.py. Reads the plan from
out/sync-plan.json (run plan.py first). --check reports retitles without
writing.

Usage:
    python scripts/examples_sync/dedupe_titles.py [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate as gen  # noqa: E402

DOCS_ROOT = HERE.parents[1]
PLAN_PATH = HERE / "out" / "sync-plan.json"

TITLE_RE = re.compile(r'^title: "(.*)"$', re.M)


def read_title(path: Path) -> str | None:
    m = TITLE_RE.search(path.read_text(encoding="utf-8"))
    return m.group(1).replace('\\"', '"') if m else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report retitles without writing")
    args = ap.parse_args()

    if not PLAN_PATH.is_file():
        raise SystemExit(f"error: {PLAN_PATH} not found; run plan.py first")
    plan = json.loads(PLAN_PATH.read_text())

    entries: list[tuple[str, str, tuple[str, ...]]] = []  # (slug, cookbook_path, group)
    for e in plan["pages"]:
        cls = e["class"]
        if cls in ("KEEP_VERBATIM", "REGEN"):
            entries.append((e["slug"], e["cookbook_path"], tuple(e.get("group") or ())))
        elif cls == "REMAP_REGEN":
            entries.append((e["slug"], e["new_cookbook_path"], tuple(e.get("group") or ())))
    for e in plan["new_pages"]:
        entries.append((e["slug"], e["cookbook_path"], tuple(e.get("nav_group") or ())))
    for e in plan["knowledge_restructure"]["new_tree"]:
        entries.append((e["slug"], e["cookbook_path"], ()))

    # group key: nav group when known, else the slug's parent directory
    groups: dict[tuple, list[tuple[str, str, Path, str]]] = defaultdict(list)
    for slug, cb, group in entries:
        path = DOCS_ROOT / f"{slug}.mdx"
        if not path.is_file():
            continue
        title = read_title(path)
        if title is None:
            continue
        key = group if group else ("_dir",) + tuple(slug.split("/")[:-1])
        groups[key].append((slug, cb, path, title))

    renamed: list[tuple[str, str, str]] = []
    for key, pages in sorted(groups.items()):
        counts: dict[str, int] = defaultdict(int)
        for _, _, _, title in pages:
            counts[title] += 1
        dupes = {t for t, n in counts.items() if n > 1}
        if not dupes:
            continue
        # first pass: stem-derived titles for every duplicated page
        new_titles: dict[str, str] = {}
        for slug, cb, path, title in pages:
            if title in dupes:
                new_titles[slug] = gen.smart_title(Path(cb).stem)
        # second pass: disambiguate stems that still collide inside the group
        final: dict[str, int] = defaultdict(int)
        for slug, _, _, title in pages:
            final[new_titles.get(slug, title)] += 1
        for slug, cb, path, title in pages:
            if slug not in new_titles:
                continue
            new = new_titles[slug]
            if final[new] > 1:
                parent = gen.smart_title(re.sub(r"^\d+[a-z]?_", "", Path(cb).parent.name))
                new = f"{parent} {new}"
            if new == title:
                continue
            if not args.check:
                text = path.read_text(encoding="utf-8")
                text = text.replace(f"title: {gen.yaml_str(title)}", f"title: {gen.yaml_str(new)}", 1)
                old_placeholder = f"description: {gen.yaml_str(f'Runnable cookbook example: {title}.')}"
                new_placeholder = f"description: {gen.yaml_str(f'Runnable cookbook example: {new}.')}"
                text = text.replace(old_placeholder, new_placeholder, 1)
                path.write_text(text, encoding="utf-8")
            renamed.append((slug, title, new))

    verb = "would retitle" if args.check else "retitled"
    print(f"{verb} {len(renamed)} pages")
    for slug, old, new in renamed:
        print(f"  {slug}: {old!r} -> {new!r}")


if __name__ == "__main__":
    main()
