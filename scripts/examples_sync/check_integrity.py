#!/usr/bin/env python3
"""Post-sync integrity checks for an examples sync run.

Reads the plan from out/sync-plan.json (run plan.py first) and verifies:
  (a) frontmatter shape, fence balance, and source field on every generated page
  (b) every cookbook path referenced under examples/ exists in the cookbook
  (c) every generated page carries the complete, byte-matching cookbook source
  (d) curated_source bindings carry the complete cookbook source
  (e) file inventory report (mdx count, stray non-mdx files, git status summary)
  (f) PRESERVE_CURATED and external one-off pages protected by final-output locks

Writes out/integrity-log.json; exits 1 if any check fails.

Usage:
    python scripts/examples_sync/check_integrity.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate as gen  # noqa: E402
from migration_manifest import load_migration_manifest  # noqa: E402

DOCS_ROOT = HERE.parents[1]
AGNO_ROOT = Path(os.environ.get("AGNO_REPO") or DOCS_ROOT / "agno")
COOKBOOK = AGNO_ROOT / "cookbook"
OUT_DIR = HERE / "out"
PLAN_PATH = OUT_DIR / "sync-plan.json"
PRESERVE_STATE_PATH = OUT_DIR / "preserve-curated-state.json"
PRESERVE_BASELINE_PATH = HERE / "preserve-curated-baseline.json"
MIGRATION_MANIFEST_PATH = HERE / "migration-routes.json"
APPLY_ONEOFFS_PATH = HERE / "apply_oneoffs.py"

source_tag_result = subprocess.run(
    ["git", "-C", str(AGNO_ROOT), "describe", "--tags", "--exact-match", "HEAD"],
    capture_output=True,
    text=True,
    check=False,
)
if source_tag_result.returncode != 0:
    raise SystemExit(f"error: Agno source HEAD is not an exact tag: {AGNO_ROOT}")
EXPECTED_SOURCE_REF = source_tag_result.stdout.strip()

if not PLAN_PATH.is_file():
    raise SystemExit(f"error: {PLAN_PATH} not found; run plan.py first")
plan = json.loads(PLAN_PATH.read_text())

gen_tasks: list[tuple[str, str, str]] = []
for e in plan["pages"]:
    if e["class"] in ("KEEP_VERBATIM", "REGEN"):
        gen_tasks.append((e["slug"], e["cookbook_path"], e["class"]))
    elif e["class"] == "REMAP_REGEN":
        gen_tasks.append((e["slug"], e["new_cookbook_path"], e["class"]))
for e in plan["new_pages"]:
    gen_tasks.append((e["slug"], e["cookbook_path"], "NEW"))
for e in plan["knowledge_restructure"]["new_tree"]:
    gen_tasks.append((e["slug"], e["cookbook_path"], "NEW_KNOWLEDGE"))

problems: list[str] = []


def fences_balanced(text: str) -> bool:
    open_len = 0
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^(`{3,})", stripped)
        if not m:
            continue
        run = len(m.group(1))
        if open_len == 0:
            open_len = run
        elif stripped == "`" * run and run >= open_len:
            open_len = 0
    return open_len == 0


def extract_python_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(`{3,})python(?:\s+(.*?))?\s*$", lines[i].strip())
        if not m:
            i += 1
            continue
        run = len(m.group(1))
        for j in range(i + 1, len(lines)):
            s = lines[j].strip()
            if s == "`" * len(s) and len(s) >= run and s.startswith("`"):
                blocks.append(((m.group(2) or "").strip(), "\n".join(lines[i + 1 : j])))
                i = j + 1
                break
        else:
            return blocks
    return blocks


def extract_first_code_block(text: str) -> str | None:
    blocks = extract_python_blocks(text)
    return blocks[0][1] if blocks else None


# ---------------------------------------------------------------------------
# (a) frontmatter + fence balance + source field on every generated page
# ---------------------------------------------------------------------------
fm_re = re.compile(r"\A---\ntitle: \"(.+)\"\ndescription: \"(.*)\"\nsource: (\S+)\n---\n", re.S)
a_bad = []
for slug, rel, cls in gen_tasks:
    p = DOCS_ROOT / f"{slug}.mdx"
    if not p.is_file():
        a_bad.append((slug, "file missing"))
        continue
    text = p.read_text(encoding="utf-8")
    m = fm_re.match(text)
    if not m:
        a_bad.append((slug, "frontmatter shape wrong"))
        continue
    if not m.group(1).strip() or not m.group(2).strip():
        a_bad.append((slug, "empty title/description"))
    elif m.group(2).startswith("Runnable cookbook example:"):
        a_bad.append((slug, "placeholder description"))
    if m.group(3) != f"cookbook/{rel}":
        a_bad.append((slug, f"source field {m.group(3)!r} != planned cookbook/{rel}"))
    if not fences_balanced(text):
        a_bad.append((slug, "unbalanced code fences"))
print(f"(a) frontmatter+fences: {len(gen_tasks)} pages checked, {len(a_bad)} bad")
for s, why in a_bad[:20]:
    print("   BAD:", s, "--", why)
problems += [f"(a) {s}: {w}" for s, w in a_bad]

# ---------------------------------------------------------------------------
# (b) every cookbook path referenced anywhere under examples/ exists
# ---------------------------------------------------------------------------
ref_res = [
    re.compile(r"^source: (cookbook/\S+)$", re.M),
    re.compile(r"^curated_source: (cookbook/\S+)$", re.M),
    re.compile(r"cd agno/(cookbook/[^\s`\"']+)"),
]
source_url_re = re.compile(
    r"github\.com/agno-agi/agno/(?:blob|tree)/([^/\s]+)/(cookbook/[^)\s\"'`]+)"
)
gen_slugs = {t[0] for t in gen_tasks}
intentional_absent_refs = {
    (entry["slug"], entry["cookbook_path"])
    for entry in plan["pages"]
    if entry.get("subtype") == "post-tag-source"
}
planned_delete_slugs = {
    entry["slug"] for entry in plan["pages"] if entry["class"] == "DELETE"
}
b_bad_gen, b_bad_other, b_pending_delete = [], [], []


def record_dead_ref(slug: str, ref: str) -> None:
    problem = (slug, f"dead ref {ref}")
    if slug in planned_delete_slugs:
        b_pending_delete.append(problem)
    elif slug in gen_slugs:
        b_bad_gen.append(problem)
    else:
        b_bad_other.append(problem)


all_mdx = sorted((DOCS_ROOT / "examples").rglob("*.mdx"))
for p in all_mdx:
    slug = str(p.relative_to(DOCS_ROOT)).removesuffix(".mdx")
    text = p.read_text(encoding="utf-8")
    has_curated_source = re.search(r"^curated_source:\s+", text, re.M) is not None
    for rx in ref_res:
        for ref in rx.findall(text):
            ref = ref.rstrip(".,)")
            tail = ref.removeprefix("cookbook/")
            target = COOKBOOK / tail
            if (
                not (target.is_file() or target.is_dir())
                and (slug, tail) not in intentional_absent_refs
            ):
                record_dead_ref(slug, ref)
    for source_ref, ref in source_url_re.findall(text):
        ref = ref.rstrip(".,)")
        tail = ref.removeprefix("cookbook/")
        target = COOKBOOK / tail
        if (
            not (target.is_file() or target.is_dir())
            and (slug, tail) not in intentional_absent_refs
        ):
            record_dead_ref(slug, ref)
        if (slug in gen_slugs or has_curated_source) and source_ref != EXPECTED_SOURCE_REF:
            (b_bad_gen if slug in gen_slugs else b_bad_other).append(
                (slug, f"source link ref {source_ref!r} != {EXPECTED_SOURCE_REF!r}")
            )
print(f"(b) cookbook refs: {len(all_mdx)} files scanned; "
      f"{len(b_bad_gen)} problems in generated pages, "
      f"{len(b_bad_other)} in preserved pages; "
      f"{len(b_pending_delete)} refs isolated to {len({slug for slug, _ in b_pending_delete})} "
      "planned DELETE routes")
for slug, problem in (b_bad_gen + b_bad_other)[:25]:
    print("   BAD:", slug, "--", problem)
problems += [f"(b) generated {slug}: {problem}" for slug, problem in b_bad_gen]
problems += [f"(b) preserved {slug}: {problem}" for slug, problem in b_bad_other]
problems += [f"(b) planned DELETE {slug}: {problem}" for slug, problem in b_pending_delete]

# ---------------------------------------------------------------------------
# (c) every generated page carries the complete cookbook source
# ---------------------------------------------------------------------------
c_bad = []
source_fences_checked = 0
for slug, rel, cls in gen_tasks:
    p = DOCS_ROOT / f"{slug}.mdx"
    target = COOKBOOK / rel
    if not p.is_file():
        c_bad.append((slug, "page missing"))
        continue
    if not target.is_file():
        c_bad.append((slug, f"cookbook/{rel} missing"))
        continue
    source_text = target.read_text(encoding="utf-8")
    siblings = gen.collect_siblings(target, source_text)
    expected = [("", source_text.strip("\n"))] + [
        (sibling.name, sibling.read_text(encoding="utf-8").strip("\n"))
        for sibling in siblings
    ]
    blocks = extract_python_blocks(p.read_text(encoding="utf-8"))
    source_fences_checked += len(expected)
    if len(blocks) != len(expected):
        c_bad.append((slug, f"expected {len(expected)} source fences, found {len(blocks)}"))
        continue
    if blocks[0][1] != expected[0][1]:
        c_bad.append((slug, f"primary code block != cookbook/{rel}"))
    for (label, code), (expected_label, want) in zip(blocks[1:], expected[1:]):
        if label != expected_label:
            c_bad.append((slug, f"helper fence label {label!r} != {expected_label!r}"))
        if code != want:
            c_bad.append((slug, f"helper code block != cookbook/{rel.rsplit('/', 1)[0]}/{expected_label}"))
print(
    f"(c) generated source fidelity: {len(gen_tasks)} pages and "
    f"{source_fences_checked} source fences checked, {len(c_bad)} bad"
)
for slug, why in c_bad:
    print("   BAD:", slug, "--", why)
problems += [f"(c) {slug}: {why}" for slug, why in c_bad]

# ---------------------------------------------------------------------------
# (d) curated_source bindings carry the complete cookbook source
# ---------------------------------------------------------------------------
d_bound = []
d_bad = []
for p in all_mdx:
    text = p.read_text(encoding="utf-8")
    match = re.search(r"^curated_source: cookbook/(\S+)\s*$", text, re.M)
    if not match:
        continue
    rel = match.group(1)
    slug = str(p.relative_to(DOCS_ROOT)).removesuffix(".mdx")
    d_bound.append(slug)
    target = COOKBOOK / rel
    code = extract_first_code_block(text)
    if not target.is_file():
        d_bad.append((slug, f"missing cookbook/{rel}"))
    elif code is None:
        d_bad.append((slug, "no Python code fence"))
    elif code.strip("\n") != target.read_text(encoding="utf-8").strip("\n"):
        d_bad.append((slug, f"code block != cookbook/{rel}"))
print(f"(d) curated_source: {len(d_bound)} bindings checked, {len(d_bad)} bad")
for slug, why in d_bad:
    print("   BAD:", slug, "--", why)
problems += [f"(d) {slug}: {why}" for slug, why in d_bad]

# ---------------------------------------------------------------------------
# (e) file inventory and untracked generated-output gate
# ---------------------------------------------------------------------------
n_files = len(all_mdx)
non_mdx = [str(p) for p in (DOCS_ROOT / "examples").rglob("*") if p.is_file() and p.suffix != ".mdx"]
print(f"(e) files under examples/: {n_files} mdx; non-mdx files: {len(non_mdx)}")
for f in non_mdx[:10]:
    print("   NON-MDX:", f)
problems += [f"(e) non-mdx file under examples/: {f}" for f in non_mdx]

# --untracked-files=all: plain --porcelain collapses fully-untracked
# directories into one "dir/" entry, undercounting the ?? files.
status = subprocess.run(
    ["git", "-C", str(DOCS_ROOT), "status", "--porcelain", "--untracked-files=all"],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
st = Counter()
outside = []
for line in status:
    code, path = line[:2].strip(), line[3:]
    if path.startswith("examples/"):
        st[code] += 1
    else:
        outside.append((code, path))
print(f"(e) git status under examples/: {dict(st)}; entries outside examples/: {len(outside)}")
tracked_raw = subprocess.run(
    [
        "git",
        "-C",
        str(DOCS_ROOT),
        "ls-files",
        "-z",
        "--",
        "examples",
    ],
    capture_output=True,
    check=True,
).stdout
tracked_examples = {
    os.fsdecode(item) for item in tracked_raw.split(b"\0") if item
}
filesystem_examples = {
    path.relative_to(DOCS_ROOT).as_posix() for path in all_mdx
}
untracked_examples = sorted(
    filesystem_examples - tracked_examples
)
for path in untracked_examples[:10]:
    print("   UNTRACKED:", path)
problems += [
    f"(e) untracked generated file under examples/: {path}"
    for path in untracked_examples
]

# ---------------------------------------------------------------------------
# (f) PRESERVE_CURATED generation boundary and final-state fingerprints
# ---------------------------------------------------------------------------
f_bad: list[str] = []
state_external_paths: set[str] = set()
preserve_entries = {
    entry["slug"]: entry
    for entry in plan["pages"]
    if entry["class"] == "PRESERVE_CURATED"
}
if not PRESERVE_STATE_PATH.is_file():
    f_bad.append("preserve-curated-state.json missing; run apply_oneoffs.py")
else:
    state = json.loads(PRESERVE_STATE_PATH.read_text(encoding="utf-8"))
    expected_plan_hash = hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()
    if state.get("schema_version") != 2:
        f_bad.append("preserve state schema_version is not 2")
    if state.get("plan_sha256") != expected_plan_hash:
        f_bad.append("preserve state does not bind the current sync plan")
    if state.get("apply_oneoffs_sha256") != hashlib.sha256(
        APPLY_ONEOFFS_PATH.read_bytes()
    ).hexdigest():
        f_bad.append("preserve state does not bind the current one-off script")
    if state.get("migration_manifest_sha256") != hashlib.sha256(
        MIGRATION_MANIFEST_PATH.read_bytes()
    ).hexdigest():
        f_bad.append("preserve state does not bind the current migration manifest")
    external_page_rows = [
        row
        for row in state.get("external_pages", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    ]
    external_rows = {
        row.get("path"): row
        for row in external_page_rows
    }
    state_external_paths = set(external_rows)
    if len(external_page_rows) != len(external_rows):
        f_bad.append("preserve state contains duplicate external-page rows")
    for path in sorted(state_external_paths):
        if path.startswith("/") or path.startswith("examples/") or not path.endswith(".mdx"):
            f_bad.append(f"{path}: invalid external one-off path")
        row = external_rows.get(path)
        if row is None:
            continue
        final = row.get("final_sha256")
        if not isinstance(final, str) or re.fullmatch(r"[0-9a-f]{64}", final) is None:
            f_bad.append(f"{path}: invalid external final_sha256")
            continue
        target = DOCS_ROOT / path
        if not target.is_file():
            f_bad.append(f"{path}: external one-off page missing")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != final:
            f_bad.append(f"{path}: current bytes differ from external final hash")
    state_page_rows = [
        row
        for row in state.get("pages", [])
        if isinstance(row, dict) and isinstance(row.get("slug"), str)
    ]
    state_rows = {
        row.get("slug"): row
        for row in state_page_rows
    }
    if len(state_page_rows) != len(state_rows):
        f_bad.append("preserve state contains duplicate curated-page rows")
    if set(state_rows) != set(preserve_entries):
        f_bad.append("preserve state slug set differs from the current plan")
    for slug, entry in preserve_entries.items():
        planned = entry.get("content_sha256")
        if not isinstance(planned, str) or re.fullmatch(r"[0-9a-f]{64}", planned) is None:
            f_bad.append(f"{slug}: invalid planned content_sha256")
            continue
        row = state_rows.get(slug)
        if row is None:
            continue
        if row.get("planned_sha256") != planned:
            f_bad.append(f"{slug}: state planned hash differs from plan")
        final = row.get("final_sha256")
        if not isinstance(final, str) or re.fullmatch(r"[0-9a-f]{64}", final) is None:
            f_bad.append(f"{slug}: invalid final_sha256")
            continue
        if row.get("changed_by_oneoffs") != (planned != final):
            f_bad.append(f"{slug}: changed_by_oneoffs is inconsistent")
        path = DOCS_ROOT / f"{slug}.mdx"
        if not path.is_file():
            f_bad.append(f"{slug}: final page missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != final:
            f_bad.append(f"{slug}: current bytes differ from recorded final hash")
print(f"(f) PRESERVE_CURATED: {len(preserve_entries)} slugs, {len(f_bad)} fingerprint problems")
for problem in f_bad[:20]:
    print("   BAD:", problem)
problems += [f"(f) {problem}" for problem in f_bad]

# ---------------------------------------------------------------------------
# (f2) tracked final-output baseline for curated and external one-off pages
# ---------------------------------------------------------------------------
f2_bad: list[str] = []
expected_baseline_paths = {
    f"{slug}.mdx" for slug in preserve_entries
}


def baseline_rows(field: str, expected_paths: set[str]) -> dict[str, str]:
    raw_rows = baseline.get(field)
    if not isinstance(raw_rows, list):
        f2_bad.append(f"baseline {field} must be a list")
        return {}
    rows: dict[str, str] = {}
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            f2_bad.append(f"baseline {field}[{index}] has invalid fields")
            continue
        path = row.get("path")
        digest = row.get("sha256")
        if not isinstance(path, str) or not path or path.startswith("/"):
            f2_bad.append(f"baseline {field}[{index}] has invalid path")
            continue
        if path in rows:
            f2_bad.append(f"baseline {field} contains duplicate path: {path}")
            continue
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            f2_bad.append(f"baseline {path} has invalid sha256")
            continue
        rows[path] = digest
    if set(rows) != expected_paths:
        f2_bad.append(
            f"baseline {field} path set differs: "
            f"missing={sorted(expected_paths - rows.keys())[:10]}, "
            f"unexpected={sorted(rows.keys() - expected_paths)[:10]}"
        )
    return rows


baseline: dict[str, object] = {}
if not PRESERVE_BASELINE_PATH.is_file():
    f2_bad.append(
        "preserve-curated-baseline.json missing; refresh it only after reviewed final edits"
    )
else:
    loaded_baseline = json.loads(PRESERVE_BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded_baseline, dict):
        f2_bad.append("preserve baseline must be an object")
    else:
        baseline = loaded_baseline
        if baseline.get("schema_version") != 1:
            f2_bad.append("preserve baseline schema_version is not 1")
        if baseline.get("source_ref") != EXPECTED_SOURCE_REF:
            f2_bad.append(
                f"preserve baseline source_ref {baseline.get('source_ref')!r} "
                f"!= {EXPECTED_SOURCE_REF!r}"
            )
        preserve_baseline = baseline_rows("preserve_curated", expected_baseline_paths)
        external_baseline = baseline_rows("external_oneoffs", state_external_paths)
        for path, expected in sorted({**preserve_baseline, **external_baseline}.items()):
            target = DOCS_ROOT / path
            if not target.is_file():
                f2_bad.append(f"baseline page missing: {path}")
            elif hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                f2_bad.append(f"{path}: current bytes differ from tracked baseline")
print(
    f"(f2) tracked preserve baseline: {len(expected_baseline_paths)} curated and "
    f"{len(state_external_paths)} external paths; {len(f2_bad)} problems"
)
for problem in f2_bad[:20]:
    print("   BAD:", problem)
problems += [f"(f2) {problem}" for problem in f2_bad]

# ---------------------------------------------------------------------------
# (g) migration redirects and hidden pages are manifest-owned and graph-safe
# ---------------------------------------------------------------------------
g_bad: list[str] = []
internal_link_re = re.compile(r'''(?:\]\(/|href=["']/)([^\s)"'#?]+)''')
manifest = load_migration_manifest(MIGRATION_MANIFEST_PATH)
migration_slugs = set(manifest.targets)
retained_slugs = set(manifest.retained_page_slugs)
redirect_slugs = set(manifest.redirect_slugs)
unreviewed_delete_slugs = sorted(planned_delete_slugs - redirect_slugs)
if unreviewed_delete_slugs:
    g_bad.append(
        "planned DELETE routes lack reviewed redirect policy: "
        f"{unreviewed_delete_slugs[:10]}"
    )


def reaches_concrete_page(
    slug: str,
    visiting: frozenset[str] = frozenset(),
) -> bool:
    if slug in visiting or slug in migration_slugs:
        return False
    path = DOCS_ROOT / f"{slug}.mdx"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if not slug.endswith("/overview") or "```" in text:
        return True
    children = {
        link
        for link in internal_link_re.findall(text)
        if (DOCS_ROOT / f"{link}.mdx").is_file()
    }
    next_visiting = visiting | {slug}
    return any(reaches_concrete_page(child, next_visiting) for child in children)


docs_json = json.loads((DOCS_ROOT / "docs.json").read_text(encoding="utf-8"))
examples_tabs = [
    tab for tab in docs_json["navigation"]["tabs"] if tab.get("tab") == "Examples"
]
if len(examples_tabs) != 1:
    g_bad.append(f"expected one Examples tab, found {len(examples_tabs)}")


def navigation_routes(items: object) -> list[str]:
    routes: list[str] = []
    if isinstance(items, str):
        return [items]
    if isinstance(items, list):
        for item in items:
            routes.extend(navigation_routes(item))
    elif isinstance(items, dict):
        routes.extend(navigation_routes(items.get("pages", [])))
    return routes


nav_routes = (
    navigation_routes(examples_tabs[0].get("groups", [])) if len(examples_tabs) == 1 else []
)
legacy_nav_routes = sorted(set(nav_routes) & migration_slugs)
if legacy_nav_routes:
    g_bad.append(f"migration routes remain in navigation: {legacy_nav_routes[:10]}")

raw_redirects = docs_json.get("redirects")
redirect_rows = raw_redirects if isinstance(raw_redirects, list) else []
if not isinstance(raw_redirects, list):
    g_bad.append("docs.json redirects must be a list")
redirect_sources = [
    row.get("source") for row in redirect_rows if isinstance(row, dict)
]
duplicate_redirects = sorted(
    source for source, count in Counter(redirect_sources).items() if count > 1
)
if duplicate_redirects:
    g_bad.append(f"duplicate docs.json redirect sources: {duplicate_redirects[:10]}")
actual_managed_redirects = {
    row.get("source"): row.get("destination")
    for row in redirect_rows
    if isinstance(row, dict)
    and isinstance(row.get("source"), str)
    and row["source"].removeprefix("/") in migration_slugs
}
expected_managed_redirects = {
    "/" + slug: "/" + manifest.targets[slug][0][1]
    for slug in redirect_slugs
}
if actual_managed_redirects != expected_managed_redirects:
    g_bad.append(
        "managed migration redirects differ: "
        f"missing={sorted(expected_managed_redirects.keys() - actual_managed_redirects.keys())[:10]}, "
        f"unexpected={sorted(actual_managed_redirects.keys() - expected_managed_redirects.keys())[:10]}, "
        f"wrong={sorted(source for source in expected_managed_redirects.keys() & actual_managed_redirects.keys() if expected_managed_redirects[source] != actual_managed_redirects[source])[:10]}"
    )

rendered_migrations = {
    str(path.relative_to(DOCS_ROOT).with_suffix(""))
    for path in all_mdx
    if re.search(
        r'^description: "(?:Current alternatives|Migration notice) for the retired ',
        path.read_text(encoding="utf-8"),
        re.M,
    )
}
if rendered_migrations != retained_slugs:
    g_bad.append(
        "migration manifest/page membership differs: "
        f"missing={sorted(retained_slugs - rendered_migrations)[:10]}, "
        f"unmanaged={sorted(rendered_migrations - retained_slugs)[:10]}"
    )

for slug in sorted(redirect_slugs):
    if (DOCS_ROOT / f"{slug}.mdx").exists():
        g_bad.append(f"{slug}: redirect route retains a page file")
for slug in sorted(retained_slugs):
    path = DOCS_ROOT / f"{slug}.mdx"
    if not path.is_file():
        g_bad.append(f"{slug}: retained migration page missing")
        continue
    source_text = path.read_text(encoding="utf-8")
    if "\x60\x60\x60" in source_text:
        g_bad.append(f"{slug}: migration page contains a code fence")
    if re.search(r"^(?:source|curated_source):", source_text, re.M):
        g_bad.append(f"{slug}: migration page retains a source binding")
    expected_prefix = (
        'description: "Current alternatives for the retired '
        if slug in manifest.chooser_pages
        else 'description: "Migration notice for the retired '
    )
    if expected_prefix not in source_text:
        g_bad.append(f"{slug}: retained migration page has the wrong disposition copy")
    page_links = set(internal_link_re.findall(source_text))
    missing_targets = {
        target for _, target in manifest.targets[slug] if target not in page_links
    }
    if missing_targets:
        g_bad.append(f"{slug}: migration page omits targets {sorted(missing_targets)}")

repo_mdx_raw = subprocess.run(
    [
        "git",
        "-C",
        str(DOCS_ROOT),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "*.mdx",
    ],
    capture_output=True,
    check=True,
).stdout
all_repo_mdx = [
    DOCS_ROOT / os.fsdecode(item)
    for item in repo_mdx_raw.split(b"\0")
    if item and (DOCS_ROOT / os.fsdecode(item)).is_file()
]
for path in all_repo_mdx:
    source_slug = str(path.relative_to(DOCS_ROOT).with_suffix(""))
    links = set(internal_link_re.findall(path.read_text(encoding="utf-8")))
    legacy_links = sorted(links & migration_slugs)
    if legacy_links:
        g_bad.append(f"{source_slug}: links to legacy migration routes {legacy_links[:10]}")

overview_targets: set[str] = set()
for slug, targets in sorted(manifest.targets.items()):
    direct = manifest.direct_successors.get(slug)
    if direct is not None:
        target = direct["target"]
        target_path = DOCS_ROOT / f"{target}.mdx"
        if target_path.is_file():
            source_matches = re.findall(
                r"^(?:source|curated_source):\s*(cookbook/\S+)\s*$",
                target_path.read_text(encoding="utf-8"),
                re.M,
            )
            if source_matches != [direct["successor_source"]]:
                g_bad.append(f"{slug}: direct-successor source binding drifted: {target}")
    for _, target in targets:
        target_path = DOCS_ROOT / f"{target}.mdx"
        if not target_path.is_file():
            g_bad.append(f"{slug}: migration target missing: {target}")
            continue
        if target in migration_slugs:
            g_bad.append(f"{slug}: target is another migration route: {target}")
            continue
        target_links = set(
            internal_link_re.findall(target_path.read_text(encoding="utf-8"))
        )
        if slug in target_links:
            g_bad.append(f"{target}: links back to migration route {slug}")
        if target.endswith("/overview"):
            overview_targets.add(target)
            if not reaches_concrete_page(target):
                g_bad.append(f"{slug}: overview cannot reach a concrete current page: {target}")

print(
    f"(g) migration graph: {len(manifest.targets)} routes, "
    f"{len(redirect_slugs)} redirects, {len(retained_slugs)} hidden pages, "
    f"{len(overview_targets)} overview targets; {len(g_bad)} problems"
)
for problem in g_bad[:20]:
    print("   BAD:", problem)
problems += [f"(g) {problem}" for problem in g_bad]

print()
print(f"TOTAL PROBLEMS: {len(problems)}")
OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "integrity-log.json").write_text(json.dumps({
    "problems": problems,
    "b_bad_preserved": b_bad_other,
    "status_counts": dict(st),
    "outside_entries": len(outside),
}, indent=2))
sys.exit(1 if problems else 0)
