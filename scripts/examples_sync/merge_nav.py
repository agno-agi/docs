#!/usr/bin/env python3
"""Merge proposed Examples routes into docs.json without removing or moving live routes."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROPOSAL = Path(__file__).resolve().parent / "out" / "nav-examples-tab.json"
DEFAULT_PLAN = Path(__file__).resolve().parent / "out" / "sync-plan.json"


def walk_routes(items, path=()):
    for item in items:
        if isinstance(item, str):
            yield item, path
            continue
        if not isinstance(item, dict) or not isinstance(item.get("group"), str):
            raise RuntimeError(f"unsupported Examples navigation item: {item!r}")
        pages = item.get("pages")
        if not isinstance(pages, list):
            raise RuntimeError(f"navigation group has no pages list: {item['group']}")
        yield from walk_routes(pages, path + (item["group"],))


def route_index(tab):
    rows = list(walk_routes(tab["groups"]))
    routes = [route for route, _ in rows]
    duplicates = sorted(route for route, count in Counter(routes).items() if count > 1)
    if duplicates:
        raise RuntimeError(f"duplicate Examples routes: {duplicates}")
    return dict(rows), routes


def validate_group_names(items, path=()):
    names = [item["group"] for item in items if isinstance(item, dict)]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise RuntimeError(f"duplicate sibling groups at {path}: {duplicates}")
    for item in items:
        if isinstance(item, dict):
            validate_group_names(item["pages"], path + (item["group"],))


def group_paths(items, path=()):
    for item in items:
        if isinstance(item, dict):
            child_path = path + (item["group"],)
            yield child_path
            yield from group_paths(item["pages"], child_path)


def child_sequences(items, path=()):
    yield path, [
        ("group", item["group"]) if isinstance(item, dict) else ("page", item)
        for item in items
    ]
    for item in items:
        if isinstance(item, dict):
            yield from child_sequences(item["pages"], path + (item["group"],))


def ensure_group(groups, path):
    current = groups
    node = None
    for name in path:
        matches = [
            item
            for item in current
            if isinstance(item, dict) and item.get("group") == name
        ]
        if len(matches) > 1:
            raise RuntimeError(f"duplicate sibling group while merging {path}: {name}")
        if matches:
            node = matches[0]
        else:
            node = {"group": name, "pages": []}
            current.append(node)
        current = node["pages"]
    return node


def examples_tab(docs):
    matches = [
        tab
        for tab in docs["navigation"]["tabs"]
        if tab.get("tab") == "Examples"
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one Examples tab, found {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any proposed route is absent; never write docs.json",
    )
    args = parser.parse_args()

    docs_path = args.docs_root / "docs.json"
    docs = json.loads(docs_path.read_text())
    proposed = json.loads(args.proposal.read_text())
    plan = json.loads(args.plan.read_text())
    if proposed.get("tab") != "Examples" or not isinstance(proposed.get("groups"), list):
        raise RuntimeError("proposal is not an Examples tab")

    current_tab = examples_tab(docs)
    proposed_tab = {"tab": "Examples", "groups": proposed["groups"]}
    validate_group_names(current_tab["groups"])
    validate_group_names(proposed_tab["groups"])
    current_index, current_order = route_index(current_tab)
    proposed_index, proposed_order = route_index(proposed_tab)
    current_groups = set(group_paths(current_tab["groups"]))
    proposed_groups = set(group_paths(proposed_tab["groups"]))
    current_sequences = dict(child_sequences(current_tab["groups"]))

    planned_new = {
        entry["slug"]
        for entry in plan["new_pages"] + plan["knowledge_restructure"]["new_tree"]
    }
    if not planned_new <= set(proposed_index):
        raise RuntimeError(
            "plan-declared NEW routes are absent from the navigation proposal: "
            f"{sorted(planned_new - set(proposed_index))}"
        )

    moved = sorted(
        route
        for route in set(current_index) & set(proposed_index)
        if current_index[route] != proposed_index[route]
    )
    if moved:
        raise RuntimeError(f"proposal moves existing routes between groups: {moved}")

    additions = [route for route in proposed_order if route not in current_index]
    retained = [route for route in current_order if route not in proposed_index]
    unexpected_additions = sorted(set(additions) - planned_new)
    if unexpected_additions:
        raise RuntimeError(
            f"proposal would re-add routes not classified NEW: {unexpected_additions}"
        )
    if args.check:
        missing_groups = sorted(proposed_groups - current_groups)
        if additions or missing_groups:
            print(
                f"error: docs.json is missing {len(additions)} proposed Examples routes "
                f"and {len(missing_groups)} proposed groups",
            )
            return 1
        print(
            f"Examples navigation converged: {len(current_order)} routes; "
            f"{len(current_groups)} groups; {len(retained)} retained outside the proposal"
        )
        return 0

    merged = copy.deepcopy(docs)
    merged_tab = examples_tab(merged)
    for route in additions:
        group_path = proposed_index[route]
        group = ensure_group(merged_tab["groups"], group_path)
        group["pages"].append(route)

    merged_index, merged_order = route_index(merged_tab)
    merged_groups = set(group_paths(merged_tab["groups"]))
    merged_sequences = dict(child_sequences(merged_tab["groups"]))
    expected = set(current_index) | set(proposed_index)
    if set(merged_index) != expected:
        raise RuntimeError(
            "merged route set differs from the exact current/proposed union"
        )
    if [route for route in merged_order if route in current_index] != current_order:
        raise RuntimeError("merge changed the order of existing routes")
    for route, path in current_index.items():
        if merged_index[route] != path:
            raise RuntimeError(f"merge moved current route: {route}")
    if merged_groups != current_groups | proposed_groups:
        raise RuntimeError("merged group set differs from the exact current/proposed union")
    for path, sequence in current_sequences.items():
        if merged_sequences[path][: len(sequence)] != sequence:
            raise RuntimeError(f"merge reordered current children in group: {path}")

    docs_path.write_text(json.dumps(merged, indent=2) + "\n")
    print(
        f"Examples navigation merged: {len(current_order)} current + "
        f"{len(additions)} additions = {len(merged_order)} routes; "
        f"{len(retained)} current-only routes retained; {len(merged_groups)} groups"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
