#!/usr/bin/env python3
"""Merge proposed Examples routes and approved migration redirects into docs.json."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from migration_manifest import load_migration_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROPOSAL = Path(__file__).resolve().parent / "out" / "nav-examples-tab.json"
DEFAULT_PLAN = Path(__file__).resolve().parent / "out" / "sync-plan.json"
DEFAULT_REDIRECTS = Path(__file__).resolve().parent / "out" / "redirects.json"
DEFAULT_MIGRATION_MANIFEST = Path(__file__).resolve().parent / "migration-routes.json"


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


def remove_routes(items, retired):
    """Remove approved legacy routes and any groups left empty by the cleanup."""
    cleaned = []
    for item in items:
        if isinstance(item, str):
            if item not in retired:
                cleaned.append(item)
            continue
        child = copy.deepcopy(item)
        child["pages"] = remove_routes(child["pages"], retired)
        if child["pages"]:
            cleaned.append(child)
    return cleaned


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
    parser.add_argument("--redirects", type=Path, default=DEFAULT_REDIRECTS)
    parser.add_argument(
        "--migration-manifest",
        type=Path,
        default=DEFAULT_MIGRATION_MANIFEST,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify navigation and managed redirects; never write docs.json",
    )
    args = parser.parse_args()

    docs_path = args.docs_root / "docs.json"
    docs = json.loads(docs_path.read_text())
    proposed = json.loads(args.proposal.read_text())
    plan = json.loads(args.plan.read_text())
    generated_redirect_rows = json.loads(args.redirects.read_text())
    manifest = load_migration_manifest(args.migration_manifest)
    if proposed.get("tab") != "Examples" or not isinstance(proposed.get("groups"), list):
        raise RuntimeError("proposal is not an Examples tab")
    if not isinstance(generated_redirect_rows, list):
        raise RuntimeError("generated redirects must be a list")

    migration_slugs = set(manifest.targets)
    desired_redirects = {
        "/" + slug: "/" + manifest.targets[slug][0][1]
        for slug in manifest.redirect_slugs
    }
    generated_redirects: dict[str, str] = {}
    for row in generated_redirect_rows:
        if not isinstance(row, dict) or set(row) != {"source", "destination"}:
            raise RuntimeError(f"invalid generated redirect row: {row!r}")
        source = row["source"]
        destination = row["destination"]
        if source in generated_redirects:
            raise RuntimeError(f"duplicate generated redirect source: {source}")
        generated_redirects[source] = destination
    generated_managed = {
        source: destination
        for source, destination in generated_redirects.items()
        if source.removeprefix("/") in migration_slugs
    }
    if generated_managed != desired_redirects:
        raise RuntimeError("generated migration redirects differ from the manifest")

    existing_redirect_rows = docs.get("redirects")
    if not isinstance(existing_redirect_rows, list):
        raise RuntimeError("docs.json redirects must be a list")
    existing_redirects: dict[str, str] = {}
    for row in existing_redirect_rows:
        if not isinstance(row, dict) or set(row) != {"source", "destination"}:
            raise RuntimeError(f"invalid docs.json redirect row: {row!r}")
        source = row["source"]
        if source in existing_redirects:
            raise RuntimeError(f"duplicate docs.json redirect source: {source}")
        existing_redirects[source] = row["destination"]
    existing_managed = {
        source: destination
        for source, destination in existing_redirects.items()
        if source.removeprefix("/") in migration_slugs
    }

    original_tab = examples_tab(docs)
    original_index, _ = route_index(original_tab)
    migration_routes_in_nav = sorted(set(original_index) & migration_slugs)
    current_tab = copy.deepcopy(original_tab)
    current_tab["groups"] = remove_routes(current_tab["groups"], migration_slugs)
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
        redirect_mismatch = existing_managed != desired_redirects
        if additions or missing_groups or migration_routes_in_nav or redirect_mismatch:
            print(
                f"error: docs.json is missing {len(additions)} proposed Examples routes "
                f"and {len(missing_groups)} proposed groups; "
                f"contains {len(migration_routes_in_nav)} legacy navigation routes; "
                f"managed redirects match={not redirect_mismatch}",
            )
            return 1
        print(
            f"Examples navigation converged: {len(current_order)} routes; "
            f"{len(current_groups)} groups; {len(retained)} retained outside the proposal; "
            f"{len(desired_redirects)} migration redirects; 0 legacy navigation routes"
        )
        return 0

    merged = copy.deepcopy(docs)
    merged_tab = examples_tab(merged)
    merged_tab["groups"] = remove_routes(merged_tab["groups"], migration_slugs)
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

    merged["redirects"] = [
        row
        for row in existing_redirect_rows
        if row["source"].removeprefix("/") not in migration_slugs
    ] + [
        {"source": source, "destination": desired_redirects[source]}
        for source in sorted(desired_redirects)
    ]

    docs_path.write_text(json.dumps(merged, indent=2) + "\n")
    print(
        f"Examples navigation merged: {len(current_order)} current + "
        f"{len(additions)} additions = {len(merged_order)} routes; "
        f"{len(retained)} current-only routes retained; {len(merged_groups)} groups; "
        f"removed {len(migration_routes_in_nav)} legacy routes; "
        f"synced {len(desired_redirects)} migration redirects"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
