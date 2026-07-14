#!/usr/bin/env python3
"""Build the Examples-tab resync plan: classify every docs example page and
every cookbook file, and emit the artifacts needed to execute the sync.

Usage:
    python scripts/examples_sync/plan.py [--docs-root DIR] [--agno-root DIR] [--out DIR]

Defaults: docs root is the repo root (two levels above this file), agno root
is the AGNO_REPO env var or the ./agno symlink at the repo root.

Outputs (in --out, default: scripts/examples_sync/out/):
    sync-plan.json         every page + cookbook file, classified
    nav-examples-tab.json  proposed docs.json Examples-tab groups subtree
    redirects.json         {source, destination} for every slug that moves or dies

Classes:
    KEEP_VERBATIM    page's code block == cookbook source (modulo whitespace)
    REGEN            source exists at the referenced path, content drifted
    REMAP_REGEN      source relocated; old + new cookbook path recorded
    PRESERVE_CURATED hand-written page (setup prose, <Steps>, extra sections,
                     or a nav index page); never regenerate
    DELETE           source gone with no successor, or orphan not worth keeping
    NEW              cookbook file with no page; slug proposed

The examples/knowledge/* section is handled as a RESTRUCTURE (decided by the
repo owner): old pages are replaced by a tree mirroring the v2.7 cookbook
layout (01_getting_started .. 05_integrations), with redirects.

This script only reads the repos. It never writes outside --out.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import generate  # the page generator; shared title/slug helpers

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGNO = Path(os.environ.get("AGNO_REPO") or REPO_ROOT / "agno")
OUT_DIR = Path(__file__).resolve().parent / "out"

# ---------------------------------------------------------------------------
# Scope and slug conventions
# ---------------------------------------------------------------------------

# Cookbook top-level dir -> docs slug segment(s) under examples/.
TOP_MAP = {
    "00_quickstart": "basics",
    "02_agents": "agents",
    "03_teams": "teams",
    "04_workflows": "workflows",
    "05_agent_os": "agent-os",
    "06_storage": "storage",
    "07_knowledge": "knowledge",
    "08_learning": "learning",
    "09_evals": "evals",
    "10_reasoning": "reasoning",
    "11_memory": "memory",
    "12_context": "context",
    "90_models": "models",
    "91_tools": "tools",
    "93_components": "components",
    "integrations": "integrations",
    "observability": "integrations/observability",
}

# Mid-path dir aliases observed in the existing slug convention.
DIR_ALIAS = {
    "mongo": "mongodb",
    "async_mongo": "async-mongodb",
}

# Dirs that are never examples.
SKIP_DIR_PARTS = {
    "__pycache__", "09_archive", "testing_resources", "tmp", "data",
    "demo-wiki", "demo-wiki-dual", "demo-wiki-git", "demo-wiki-notion",
    "demo-wiki-web", ".venv", ".venvs", "node_modules",
}
SKIP_FILES = {"__init__.py", "conftest.py"}

# New v2.7 areas the repo owner called out; NEW entries there get priority.
PRIORITY_PREFIXES = (
    "12_context/",
    "04_workflows/08_human_in_the_loop/",
    "02_agents/17_fallback_models/", "02_agents/18_checkpointing/",
    "02_agents/19_regenerate/", "02_agents/20_time_travel/",
    "02_agents/21_fork_session/",
    "03_teams/17_fallback_models/", "03_teams/23_checkpointing/",
    "03_teams/23_remote_agents/", "03_teams/24_regenerate/",
    "03_teams/25_time_travel/", "03_teams/26_fork_session/",
    "09_evals/suite/", "05_agent_os/rbac/", "05_agent_os/mcp_demo/",
    "91_tools/mcp/bgpt.py",
)

# Where to root nav groups for cookbook dirs that have no pages today.
NAV_SEEDS = {
    "12_context": ["Context", "Context Providers"],
    "integrations": ["More", "Integrations"],
    "observability": ["More", "Integrations", "Observability"],
}

SIM_ACCEPT = 0.55   # basename match: accept relocation at/above this ratio
KNOWLEDGE_REDIRECT_SIM = 0.5

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_page(text: str) -> dict:
    """Extract the bits of an example page the classifier needs."""
    page: dict = {"code": None, "ref": None, "mangled_fence": False}
    m = FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text
    page["frontmatter"] = m.group(1) if m else ""

    lines = body.splitlines()
    # locate python code block, fence-aware
    code, mangled = extract_python_block(lines)
    page["code"] = code
    page["mangled_fence"] = mangled

    # source ref, in priority order:
    # 1. `source: cookbook/...` frontmatter (written by generate.py; its
    #    presence marks the page as machine-generated, never curated)
    # 2. legacy run-block heuristic: cd + python inside the same bash block
    page["src_field"] = False
    sm = re.search(r"^source: cookbook/(\S+)\s*$", page["frontmatter"], re.M)
    if sm:
        page["ref"] = sm.group(1)
        page["src_field"] = True
    import posixpath
    for block in re.findall(r"^```bash\s*\n(.*?)^```\s*$", body, re.M | re.S):
        if page["ref"]:
            break
        cd = re.search(r"^cd agno/cookbook/(\S+)", block, re.M)
        py = re.search(r"^(?:python|python3)\s+(\S+\.py)\s*$", block, re.M)
        if cd and py:
            arg = py.group(1)
            if arg.startswith("cookbook/"):
                ref = arg[len("cookbook/"):]
            else:
                ref = posixpath.normpath(posixpath.join(cd.group(1), arg))
            page["ref"] = ref
            break

    # curated signals, computed on text outside fenced code blocks
    outside_lines = []
    fence_len = 0
    for ln in lines:
        m = re.match(r"^(`{3,})", ln.strip())
        if m:
            if fence_len == 0:
                fence_len = len(m.group(1))
            elif len(m.group(1)) >= fence_len and not ln.strip().strip("`"):
                fence_len = 0
            continue
        if fence_len == 0:
            outside_lines.append(ln)
    outside = "\n".join(outside_lines)
    headings = re.findall(r"^#{2,3}\s+(.+?)\s*$", outside, re.M)
    page["extra_headings"] = [h for h in headings if h.lower() != "run the example"]
    page["has_steps"] = "<Steps>" in outside
    first_fence = next((i for i, ln in enumerate(lines) if ln.startswith("```")), len(lines))
    paras = 0
    prev_blank = True
    for ln in lines[:first_fence]:
        if ln.strip():
            if prev_blank:
                paras += 1
            prev_blank = False
        else:
            prev_blank = True
    page["intro_paragraphs"] = paras
    return page


def extract_python_block(lines: list[str]) -> tuple[str | None, bool]:
    """First python code block; recovers blocks broken by fences inside
    docstrings (the old generator bug). Returns (code, was_mangled)."""
    start = end = None
    fence = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(`{3,})python\b", ln)
        if m:
            start, fence = i, m.group(1)
            break
    if start is None:
        return None, False
    closes = [j for j in range(start + 1, len(lines)) if re.fullmatch(r"`{3,}", lines[j].strip()) and len(lines[j].strip()) >= len(fence)]
    if not closes:
        return "\n".join(lines[start + 1:]), True
    end = closes[0]
    code = "\n".join(lines[start + 1:end])
    if code.count('"""') % 2 == 0 and code.count("'''") % 2 == 0:
        return code, False
    # unbalanced docstring: the closing fence we found is inside the
    # docstring. Extend through further fences until quotes balance.
    for j in closes[1:]:
        code = "\n".join(lines[start + 1:j])
        if code.count('"""') % 2 == 0 and code.count("'''") % 2 == 0:
            return code, True
    return code, True


def norm_code(code: str) -> str:
    lines = [ln.rstrip() for ln in code.strip("\n").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def content_hash(code: str) -> str:
    return hashlib.sha256(norm_code(code).encode()).hexdigest()


def similarity(a: str, b: str) -> float:
    sm = difflib.SequenceMatcher(None, a, b)
    if sm.real_quick_ratio() < 0.4 or sm.quick_ratio() < 0.4:
        return 0.0
    return sm.ratio()


def strip_num(part: str) -> str:
    return re.sub(r"^\d+[a-z]?_", "", part)


def slug_for(cb_rel: str) -> str:
    """Proposed docs slug for a cookbook-relative path (existing convention:
    numbered prefixes stripped, underscores to hyphens)."""
    parts = cb_rel.split("/")
    top = TOP_MAP[parts[0]]
    mids = []
    for p in parts[1:-1]:
        p = DIR_ALIAS.get(p, strip_num(p).replace("_", "-"))
        mids.append(p)
    stem = strip_num(Path(parts[-1]).stem).replace("_", "-")
    return "/".join(["examples", *top.split("/"), *mids, stem])


GROUP_TITLE_OVERRIDES = {
    "vector_dbs": "Vector Databases",  # style guide: "vector db" -> "vector database"
    "human_in_the_loop": "Human in the Loop",
    "mcp_demo": "MCP Demo",
}


def group_title(dir_part: str) -> str:
    if dir_part in GROUP_TITLE_OVERRIDES:
        return GROUP_TITLE_OVERRIDES[dir_part]
    return generate.smart_title(strip_num(dir_part))


# ---------------------------------------------------------------------------
# Nav walking
# ---------------------------------------------------------------------------

def walk_nav(groups: list, fn, path: tuple = ()):  # fn(slug, group_path)
    for g in groups:
        if isinstance(g, dict):
            walk_nav(g.get("pages", []), fn, path + (g.get("group", "?"),))
        else:
            fn(g, path)


def prune_nav(groups: list, keep: set) -> list:
    out = []
    for g in groups:
        if isinstance(g, dict):
            pages = prune_nav(g.get("pages", []), keep)
            if pages:
                g = dict(g, pages=pages)
                out.append(g)
        elif g in keep:
            out.append(g)
    return out


def find_group(groups: list, path: list) -> dict | None:
    cur = groups
    node = None
    for name in path:
        node = next((g for g in cur if isinstance(g, dict) and g.get("group") == name), None)
        if node is None:
            return None
        cur = node.get("pages", [])
    return node


def ensure_group(groups: list, path: list) -> dict:
    cur = groups
    node = None
    for name in path:
        node = next((g for g in cur if isinstance(g, dict) and g.get("group") == name), None)
        if node is None:
            node = {"group": name, "pages": []}
            cur.append(node)
        cur = node.setdefault("pages", [])
    return node


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs-root", type=Path, default=REPO_ROOT)
    ap.add_argument("--agno-root", type=Path, default=DEFAULT_AGNO)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    docs, agno, out = args.docs_root, args.agno_root, args.out
    out.mkdir(parents=True, exist_ok=True)

    # ---- inputs ----------------------------------------------------------
    docs_json = json.loads((docs / "docs.json").read_text())
    tab = next(t for t in docs_json["navigation"]["tabs"] if t.get("tab") == "Examples")

    nav_slugs: list[str] = []
    nav_group_of: dict[str, tuple] = {}
    walk_nav(tab["groups"], lambda s, p: (nav_slugs.append(s), nav_group_of.__setitem__(s, p)))

    page_files = {str(p.relative_to(docs))[:-4]: p for p in sorted((docs / "examples").rglob("*.mdx"))}
    all_slugs = sorted(set(nav_slugs) | set(page_files))

    # cookbook index
    cookbook = agno / "cookbook"
    cb_files: dict[str, str] = {}  # rel path -> normalized content
    for top in sorted(TOP_MAP):
        base = cookbook / top
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = str(p.relative_to(cookbook))
            parts = set(rel.split("/"))
            if parts & SKIP_DIR_PARTS or p.name in SKIP_FILES:
                continue
            cb_files[rel] = norm_code(p.read_text(encoding="utf-8", errors="replace"))
    cb_hash = {}
    for rel, code in cb_files.items():
        cb_hash.setdefault(content_hash(code), []).append(rel)
    # index by numeral-stripped stem so renumbered files still match
    # (03_teams/task_mode/04_async_task_mode.py -> 03_teams/02_modes/tasks/07_async_task_mode.py)
    cb_by_stem: dict[str, list[str]] = {}
    for rel in cb_files:
        cb_by_stem.setdefault(strip_num(Path(rel).stem), []).append(rel)

    knowledge_new_files = sorted(r for r in cb_files if r.startswith("07_knowledge/") and Path(r).stem != "utils")

    # ---- parse pages ------------------------------------------------------
    pages: dict[str, dict] = {}
    for slug in all_slugs:
        f = page_files.get(slug)
        if f is None:
            continue
        info = parse_page(f.read_text(encoding="utf-8", errors="replace"))
        info["slug"] = slug
        info["in_nav"] = slug in nav_slugs
        pages[slug] = info

    # inbound links (to judge orphans)
    linked: set[str] = set()
    link_re = re.compile(r"\(/(examples/[a-z0-9\-/]+)[)#]")
    for f in page_files.values():
        linked.update(link_re.findall(f.read_text(encoding="utf-8", errors="replace")))

    # ---- classification ---------------------------------------------------
    results: list[dict] = []
    claimed: dict[str, str] = {}  # cookbook rel -> slug that consumes it

    def is_index(info) -> bool:
        return info["slug"].endswith("/overview") or (info["code"] is None and info["ref"] is None)

    def is_curated(info) -> bool:
        if info.get("src_field"):
            return False  # `source:` frontmatter marks a generated page
        if info["mangled_fence"]:
            return False  # broken generated page; signals are unreliable
        return (
            info["has_steps"]
            or len(info["extra_headings"]) > 0
            or (info["ref"] is None and info["code"] is not None)
            or info["intro_paragraphs"] >= 2
        )

    def remap(info) -> tuple[str | None, float]:
        """Find the relocated source for a page whose ref is gone."""
        code = norm_code(info["code"]) if info["code"] else ""
        if not code:
            return None, 0.0
        h = content_hash(code)
        if h in cb_hash:
            return sorted(cb_hash[h])[0], 1.0
        stem = strip_num(Path(info["ref"]).stem) if info["ref"] else None
        cands = list(cb_by_stem.get(stem, [])) if stem else []
        best, best_r = None, 0.0
        for cand in sorted(cands):
            r = similarity(code, cb_files[cand])
            if r > best_r:
                best, best_r = cand, r
        return (best, best_r) if best_r >= SIM_ACCEPT else (None, best_r)

    knowledge_old: list[dict] = []
    for slug in all_slugs:
        info = pages[slug]
        entry = {
            "slug": slug,
            "in_nav": info["in_nav"],
            "group": list(nav_group_of.get(slug, ())),
        }
        if slug.startswith("examples/knowledge/") and not info.get("src_field"):
            # Legacy (pre-restructure) knowledge page: handled in the
            # restructure pass. Generated pages (`source:` frontmatter)
            # classify normally like any other section.
            knowledge_old.append(info)
            continue

        if is_index(info):
            if info["in_nav"]:
                entry.update({"class": "PRESERVE_CURATED", "subtype": "index"})
            elif slug in linked:
                entry.update({"class": "PRESERVE_CURATED", "subtype": "index-hidden",
                              "note": "not in nav but linked from nav pages"})
            else:
                entry.update({"class": "DELETE", "subtype": "orphan-index",
                              "note": "overview page not in nav and not linked"})
            results.append(entry)
            continue

        ref = info["ref"]
        src = cb_files.get(ref) if ref else None
        if ref and src is not None:
            mangled = info["mangled_fence"] or "```" in src
            if is_curated(info):
                entry.update({"class": "PRESERVE_CURATED", "cookbook_path": ref})
            elif not info["in_nav"]:
                entry.update({"class": "DELETE", "subtype": "orphan",
                              "cookbook_path": ref,
                              "note": "duplicate/orphaned generated page"})
            elif norm_code(info["code"] or "") == src and not mangled:
                entry.update({"class": "KEEP_VERBATIM", "cookbook_path": ref})
            else:
                entry.update({"class": "REGEN", "cookbook_path": ref})
                if mangled:
                    entry["mangled"] = True
            if entry["class"] != "DELETE":
                claimed.setdefault(ref, slug)
        elif ref:  # ref points at a path that no longer exists
            new_ref, ratio = remap(info)
            if new_ref:
                entry.update({"class": "PRESERVE_CURATED" if is_curated(info) else "REMAP_REGEN",
                              "cookbook_path": ref, "new_cookbook_path": new_ref,
                              "similarity": round(ratio, 3)})
                if entry["class"] == "PRESERVE_CURATED":
                    entry["note"] = "curated page; update its source link to new_cookbook_path by hand"
                claimed.setdefault(new_ref, slug)
            elif is_curated(info):
                entry.update({"class": "PRESERVE_CURATED", "cookbook_path": ref,
                              "note": "curated; referenced cookbook path is gone"})
            else:
                entry.update({"class": "DELETE", "cookbook_path": ref,
                              "similarity": round(ratio, 3),
                              "note": "source gone, no successor found"})
        else:  # no ref at all: curated or content-match
            code = info["code"]
            h = content_hash(code) if code else None
            if h and h in cb_hash:
                new_ref = sorted(cb_hash[h])[0]
                entry.update({"class": "REMAP_REGEN", "cookbook_path": None,
                              "new_cookbook_path": new_ref, "similarity": 1.0,
                              "note": "no run block; source found by content match"})
                claimed.setdefault(new_ref, slug)
            elif is_curated(info) and (info["in_nav"] or slug in linked):
                entry.update({"class": "PRESERVE_CURATED"})
            elif info["in_nav"]:
                entry.update({"class": "PRESERVE_CURATED",
                              "note": "in nav, no cookbook source identified; review by hand"})
            else:
                entry.update({"class": "DELETE", "subtype": "orphan",
                              "note": "orphan with no cookbook source"})
        results.append(entry)

    # ---- knowledge restructure -------------------------------------------
    # knowledge_nav mirrors the full 07_knowledge tree (drives the nav
    # subtree); new_tree carries only the files no existing page claims
    # (drives generation). After the restructure has been executed once,
    # new_tree only picks up cookbook files added since.
    knowledge_plan = {"new_tree": [], "old_pages": []}
    knowledge_nav: list[dict] = []
    for rel in knowledge_new_files:
        slug = claimed.get(rel) or slug_for(rel)
        knowledge_nav.append({"cookbook_path": rel, "slug": slug})
        if rel not in claimed:
            knowledge_plan["new_tree"].append({"cookbook_path": rel, "slug": slug})
            claimed.setdefault(rel, slug)
    new_knowledge_slugs = {e["cookbook_path"]: e["slug"] for e in knowledge_nav}

    knowledge_overview = "examples/knowledge/overview"
    new_by_leaf = {s.rsplit("/", 1)[1]: s for s in sorted(new_knowledge_slugs.values())}
    # Old knowledge sub-section -> best new landing page. The v2.7 knowledge
    # cookbook is a near-total rewrite (max content similarity 0.54), so
    # redirects are by topic, not content.
    KNOWLEDGE_SECTION_MAP = {
        "chunking": "examples/knowledge/building-blocks/chunking-strategies",
        "embedders": "examples/knowledge/building-blocks/embedders",
        "filters": "examples/knowledge/building-blocks/filtering",
        "search-type": "examples/knowledge/building-blocks/hybrid-search",
        "custom-retriever": "examples/knowledge/advanced/custom-retriever",
        "knowledge-tools": "examples/knowledge/advanced/knowledge-tools",
        "protocol": "examples/knowledge/advanced/knowledge-protocol",
        "os": "examples/knowledge/production/agent-os",
        "quickstart": "examples/knowledge/getting-started/basic-rag",
        "readers": "examples/knowledge/integrations/readers/documents",
        "cloud": "examples/knowledge/integrations/cloud/aws",
        "vector-db": "examples/knowledge/integrations/vector-dbs/managed",
    }
    for info in knowledge_old:
        slug = info["slug"]
        if slug == knowledge_overview:
            results.append({"slug": slug, "in_nav": info["in_nav"],
                            "group": list(nav_group_of.get(slug, ())),
                            "class": "PRESERVE_CURATED", "subtype": "index",
                            "note": "knowledge landing page; rewrite for the new tree"})
            continue
        code = norm_code(info["code"]) if info["code"] else ""
        dest, best_r, how = None, 0.0, "section"
        if code:
            h = content_hash(code)
            exact = [r for r in cb_hash.get(h, []) if r.startswith("07_knowledge/")]
            if exact:
                dest, best_r, how = new_knowledge_slugs.get(sorted(exact)[0]), 1.0, "content"
            else:
                cand_r, cand = 0.0, None
                for rel in knowledge_new_files:
                    r = similarity(code, cb_files[rel])
                    if r > cand_r:
                        cand_r, cand = r, new_knowledge_slugs[rel]
                if cand_r >= KNOWLEDGE_REDIRECT_SIM:
                    dest, best_r, how = cand, cand_r, "content"
        if dest is None:
            leaf = slug.rsplit("/", 1)[1]
            if leaf in new_by_leaf:
                dest, how = new_by_leaf[leaf], "leaf-name"
            else:
                section = slug.split("/")[2]
                dest = KNOWLEDGE_SECTION_MAP.get(section, knowledge_overview)
                # per-DB vector db pages: qdrant/pgvector keep their own page
                for db, target in (("qdrant", "qdrant"), ("pgvector", "pgvector"),
                                   ("lance", "local"), ("chroma", "local")):
                    if section == "vector-db" and db in leaf:
                        dest = f"examples/knowledge/integrations/vector-dbs/{target}"
                        break
        results.append({"slug": slug, "in_nav": info["in_nav"],
                        "group": list(nav_group_of.get(slug, ())),
                        "class": "DELETE", "subtype": "knowledge-restructure",
                        "redirect_to": dest, "match": how,
                        "similarity": round(best_r, 3)})
        knowledge_plan["old_pages"].append({"slug": slug, "redirect_to": dest,
                                            "match": how, "similarity": round(best_r, 3)})

    # ---- NEW pages ---------------------------------------------------------
    surviving = {e["slug"] for e in results if e["class"] != "DELETE"}
    surviving |= {e["slug"] for e in knowledge_plan["new_tree"]}

    # slug-based claim: an unclaimed cookbook file whose conventional slug is
    # an existing surviving page belongs to that page (covers curated pages
    # with hand-written run blocks the ref parser can't see)
    entry_by_slug = {e["slug"]: e for e in results}
    for rel in sorted(cb_files):
        if rel in claimed or rel.startswith("07_knowledge/"):
            continue
        slug = slug_for(rel)
        e = entry_by_slug.get(slug)
        if e and e["class"] != "DELETE":
            claimed[rel] = slug
            if not e.get("cookbook_path") and not e.get("new_cookbook_path"):
                e["new_cookbook_path"] = rel
                e["note"] = (e.get("note", "") + " matched by slug convention").strip()

    new_entries: list[dict] = []
    conflicts: list[dict] = []
    for rel in sorted(cb_files):
        if rel in claimed or rel.startswith("07_knowledge/"):
            continue
        slug = slug_for(rel)
        if slug in surviving:
            conflicts.append({"cookbook_path": rel, "slug": slug,
                              "note": "proposed slug taken by an unrelated page; resolve by hand"})
            continue
        priority = rel.startswith(PRIORITY_PREFIXES)
        new_entries.append({"cookbook_path": rel, "slug": slug, "priority": priority})
        surviving.add(slug)

    # ---- proposed nav ------------------------------------------------------
    keep_slugs = {e["slug"] for e in results if e["class"] != "DELETE" and e["in_nav"]}
    groups = prune_nav(copy.deepcopy(tab["groups"]), keep_slugs)

    # replace the Context > Knowledge subtree
    knowledge_group = find_group(groups, ["Context", "Knowledge"])
    if knowledge_group is not None:
        tree: dict[tuple, list] = {}
        for e in knowledge_nav:
            mids = tuple(e["cookbook_path"].split("/")[1:-1])
            tree.setdefault(mids, []).append(e["slug"])
        knowledge_group["pages"] = [knowledge_overview]
        for mids in sorted(tree):
            node = knowledge_group
            for part in mids:
                node = ensure_group(node["pages"], [group_title(part)])
            node["pages"].extend(tree[mids])

    # Each nav group gets a canonical cookbook dir: the common dir prefix of
    # its member pages' sources. A NEW file goes into the group with the
    # longest canonical dir that prefixes the file's dir; remaining dir
    # components become nested subgroups.
    group_dirs: dict[tuple, list[list[str]]] = {}
    dir_votes: dict[str, dict[tuple, int]] = {}
    for e in results:
        cb = e.get("new_cookbook_path") or e.get("cookbook_path")
        if not cb or e["class"] == "DELETE" or not e["in_nav"] or not e["group"]:
            continue
        d = str(Path(cb).parent)
        g = tuple(e["group"])
        dir_votes.setdefault(d, {})
        dir_votes[d][g] = dir_votes[d].get(g, 0) + 1
        parts = d.split("/")
        for i in range(1, len(g) + 1):
            group_dirs.setdefault(g[:i], []).append(parts)
    dir_group = {d: max(v.items(), key=lambda kv: (kv[1], kv[0]))[0] for d, v in dir_votes.items()}

    def common_dir(dirs: list[list[str]]) -> list[str]:
        """Dir prefix shared by >=80% of members. Tolerates the odd page
        whose source lives in another cookbook area without letting a large
        subgroup (e.g. 40% of pages in one subdir) pull the prefix deeper."""
        prefix: list[str] = []
        pool = dirs
        while True:
            depth = len(prefix)
            counter: dict[str, int] = {}
            for d in pool:
                if len(d) > depth:
                    counter[d[depth]] = counter.get(d[depth], 0) + 1
            if not counter:
                break
            nxt, votes = max(counter.items(), key=lambda kv: (kv[1], kv[0]))
            if votes * 5 < len(pool) * 4:
                break
            prefix.append(nxt)
            pool = [d for d in pool if len(d) > depth and d[depth] == nxt]
        return prefix

    canonical = {g: common_dir(ds) for g, ds in group_dirs.items()}

    unplaced = []
    for e in new_entries:
        rel = e["cookbook_path"]
        d = str(Path(rel).parent)
        parts = d.split("/")
        target: list[str] | None = None
        extra: list[str] = []
        if d in dir_group:
            target = list(dir_group[d])
        else:
            best: tuple | None = None
            best_len = 0
            for g, cdir in canonical.items():
                if cdir and len(cdir) <= len(parts) and parts[:len(cdir)] == cdir:
                    # longest canonical dir wins; ties go to the shallower group
                    if len(cdir) > best_len or (len(cdir) == best_len and best is not None and (len(g), g) < (len(best), best)):
                        best, best_len = g, len(cdir)
            if best is not None:
                target = list(best)
                extra = [group_title(p) for p in parts[best_len:]]
            else:
                seed = NAV_SEEDS.get(parts[0])
                if seed is None:
                    unplaced.append(e)
                    continue
                target = list(seed)
                extra = [group_title(p) for p in parts[1:]]
        node = ensure_group(groups, target + extra)
        node["pages"].append(e["slug"])
        e["nav_group"] = target + extra

    # ---- redirects ---------------------------------------------------------
    live = {e["slug"] for e in results if e["class"] != "DELETE"}
    live |= {e["slug"] for e in knowledge_plan["new_tree"]}
    live |= {e["slug"] for e in new_entries}

    def fallback_dest(slug: str) -> str:
        parts = slug.split("/")
        for i in range(len(parts) - 1, 1, -1):
            cand = "/".join(parts[:i]) + "/overview"
            if cand in live:
                return cand
        return "examples/introduction"

    redirects = []
    for e in results:
        if e["class"] != "DELETE":
            continue
        if e["slug"] in live:
            continue  # a NEW page takes over this slug; no redirect needed
        dest = e.get("redirect_to") or fallback_dest(e["slug"])
        if dest not in live:  # never redirect to a dead page
            dest = fallback_dest(e["slug"])
        redirects.append({"source": "/" + e["slug"], "destination": "/" + dest})
    redirects.sort(key=lambda r: r["source"])

    # ---- outputs -----------------------------------------------------------
    counts: dict[str, int] = {}
    for e in results:
        counts[e["class"]] = counts.get(e["class"], 0) + 1
    counts["NEW"] = len(new_entries) + len(knowledge_plan["new_tree"])

    plan = {
        "docs_root": str(docs),
        "agno_root": str(agno),
        "counts": counts,
        "stats": {
            "nav_pages": len(nav_slugs),
            "example_files": len(page_files),
            "orphan_files": len(page_files) - len(set(nav_slugs) & set(page_files)),
            "cookbook_files_in_scope": len(cb_files),
            "new_priority": sum(1 for e in new_entries if e["priority"]),
            "mangled_pages": sum(1 for e in results if e.get("mangled")),
            "slug_conflicts": len(conflicts),
            "unplaced_new": len(unplaced),
        },
        "pages": results,
        "new_pages": new_entries,
        "knowledge_restructure": knowledge_plan,
        "conflicts": conflicts,
        "unplaced_new": unplaced,
        "bounds": "examples/ tab only; deploy/, TBD/ and other tabs untouched",
    }
    (out / "sync-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (out / "nav-examples-tab.json").write_text(json.dumps({"tab": "Examples", "groups": groups}, indent=2) + "\n")
    (out / "redirects.json").write_text(json.dumps(redirects, indent=2) + "\n")

    print("counts:", json.dumps(counts, indent=2))
    print("stats:", json.dumps(plan["stats"], indent=2))
    print(f"wrote {out}/sync-plan.json, nav-examples-tab.json, redirects.json")


if __name__ == "__main__":
    main()
