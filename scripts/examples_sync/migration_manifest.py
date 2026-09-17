"""Load and validate the reviewed legacy-route migration contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


EXPECTED_SCHEMA_VERSION = 3
EXPECTED_SOURCE_REF = "v3.0.4"
EXPECTED_SOURCE_EVIDENCE = {
    "agno_agentos_migration_ledger": {
        "commit_sha": "4cafec3d48c956fffaac6278ed0860e0d22e4fed",
        "remote_url": "https://github.com/agno-agi/specs.git",
        "resource": "cookbooks/05_agent_os/path-map.md",
    }
}


@dataclass(frozen=True)
class MigrationManifest:
    targets: dict[str, tuple[tuple[str, str], ...]]
    direct_successors: dict[str, dict]
    no_direct_successors: dict[str, dict]
    approved_fallback_redirects: frozenset[str]
    chooser_pages: frozenset[str]
    notice_pages: frozenset[str]

    @property
    def redirect_slugs(self) -> frozenset[str]:
        return frozenset(self.direct_successors) | self.approved_fallback_redirects

    @property
    def retained_page_slugs(self) -> frozenset[str]:
        return self.chooser_pages | self.notice_pages


def _string_set(value: object, label: str) -> frozenset[str]:
    assert isinstance(value, list), f"{label} must be a list"
    assert all(isinstance(item, str) for item in value), (
        f"{label} must contain only strings"
    )
    values = frozenset(value)
    assert len(values) == len(value), f"{label} contains duplicates"
    return values


def _safe_internal_slug(value: object, label: str) -> str:
    assert isinstance(value, str) and value and value == value.strip(), (
        f"{label} must be a non-empty string without surrounding whitespace"
    )
    parts = value.split("/")
    assert (
        not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in parts)
        and not any(character.isspace() or character in "?#\\" for character in value)
    ), f"unsafe internal docs slug for {label}: {value!r}"
    return value


def load_migration_manifest(path: Path) -> MigrationManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw.get("schema_version") == EXPECTED_SCHEMA_VERSION, (
        "migration manifest schema_version is not 3"
    )
    assert raw.get("source_ref") == EXPECTED_SOURCE_REF, (
        "migration manifest source_ref drifted"
    )
    assert raw.get("source_evidence") == EXPECTED_SOURCE_EVIDENCE, (
        "AgentOS migration ledger evidence drifted"
    )

    raw_routes = raw.get("routes")
    assert isinstance(raw_routes, dict), "migration manifest routes must be an object"
    targets: dict[str, tuple[tuple[str, str], ...]] = {}
    for slug, raw_targets in raw_routes.items():
        slug = _safe_internal_slug(slug, "migration route")
        assert slug.startswith("examples/"), f"invalid migration slug: {slug!r}"
        assert isinstance(raw_targets, list) and raw_targets, (
            f"migration route has no targets: {slug}"
        )
        normalized: list[tuple[str, str]] = []
        for target in raw_targets:
            assert isinstance(target, dict), f"invalid migration target row: {slug}"
            task = target.get("task")
            destination = target.get("target")
            assert (
                isinstance(task, str)
                and task.strip() == task
                and task
                and "\n" not in task
                and "|" not in task
            ), f"invalid migration task: {slug}"
            destination = _safe_internal_slug(
                destination,
                f"migration destination for {slug}",
            )
            normalized.append((task, destination))
        destinations = [destination for _, destination in normalized]
        assert len(destinations) == len(set(destinations)), (
            f"migration route repeats a destination: {slug}"
        )
        targets[slug] = tuple(normalized)

    direct_successors = raw.get("direct_successors")
    no_direct_successors = raw.get("no_direct_successors")
    assert isinstance(direct_successors, dict), "direct-successor evidence is missing"
    assert isinstance(no_direct_successors, dict), "no-direct-successor evidence is missing"
    assert len(targets) == 271, f"expected 271 migration routes, found {len(targets)}"
    assert len(direct_successors) == 154, (
        f"expected 154 direct successors, found {len(direct_successors)}"
    )
    assert len(no_direct_successors) == 117, (
        f"expected 117 no-direct routes, found {len(no_direct_successors)}"
    )
    assert not (set(direct_successors) & set(no_direct_successors)), (
        "migration evidence partitions overlap"
    )
    assert set(targets) == set(direct_successors) | set(no_direct_successors), (
        "migration evidence does not partition every route"
    )

    policy = raw.get("route_policy")
    assert isinstance(policy, dict), "migration route_policy must be an object"
    approved = _string_set(
        policy.get("approved_single_fallback_redirects"),
        "approved_single_fallback_redirects",
    )
    chooser_pages = _string_set(policy.get("chooser_pages"), "chooser_pages")
    notice_pages = _string_set(policy.get("notice_pages"), "notice_pages")
    assert not (approved & chooser_pages or approved & notice_pages or chooser_pages & notice_pages), (
        "migration route_policy partitions overlap"
    )
    assert set(no_direct_successors) == approved | chooser_pages | notice_pages, (
        "migration route_policy does not classify every no-direct route"
    )
    assert all(len(targets[slug]) == 1 for slug in approved), (
        "approved fallback redirects must have exactly one target"
    )
    assert all(len(targets[slug]) >= 2 for slug in chooser_pages), (
        "chooser pages must have at least two targets"
    )
    assert all(len(targets[slug]) >= 1 for slug in notice_pages), (
        "notice pages must have at least one target"
    )
    assert all(len(targets[slug]) == 1 for slug in direct_successors), (
        "direct successors must have exactly one target"
    )

    for slug, row in direct_successors.items():
        assert isinstance(row, dict), f"invalid direct-successor evidence: {slug}"
        assert targets[slug] == ((row.get("task"), row.get("target")),), (
            f"direct-successor target drifted: {slug}"
        )
        successor_source = row.get("successor_source")
        assert isinstance(successor_source, str) and successor_source.startswith("cookbook/"), (
            f"direct-successor source is invalid: {slug}"
        )
    for slug, row in no_direct_successors.items():
        assert isinstance(row, dict) and isinstance(row.get("evidence"), dict), (
            f"invalid no-direct-successor evidence: {slug}"
        )
        related = row.get("related_current_targets")
        if related is not None:
            assert isinstance(related, list) and related, (
                f"invalid related-current targets: {slug}"
            )
            expected = tuple((item.get("task"), item.get("target")) for item in related)
            assert targets[slug] == expected, f"related-current target drifted: {slug}"

    return MigrationManifest(
        targets=targets,
        direct_successors=direct_successors,
        no_direct_successors=no_direct_successors,
        approved_fallback_redirects=approved,
        chooser_pages=chooser_pages,
        notice_pages=notice_pages,
    )
