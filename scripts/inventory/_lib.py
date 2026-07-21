#!/usr/bin/env python3
"""Shared helpers for the inventory toolkit: repo file listing, docs.json
navigation reachability, the snippet inclusion graph, redirect pattern
matching, and heading/anchor extraction. Imported by every script in
scripts/inventory/; not runnable on its own.

All paths are repo-relative POSIX strings. All outputs are deterministic
(sorted, no timestamps).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"

# Fallback excludes when git is unavailable (mirrors .gitignore's top level).
_WALK_SKIP = {"node_modules", ".git", "agno", "tmp", "projects", "specs", ".idea"}

SNIPPET_DIR = "_snippets"
SNIPPET_RE = re.compile(r'<Snippet\s[^>]*?file="([^"]+)"')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CUSTOM_ID_RE = re.compile(r"\s*\{#([^}]+)\}\s*$")
HTML_ID_RE = re.compile(r'\bid="([^"]+)"')
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


# ---------------------------------------------------------------------------
# Repo files
# ---------------------------------------------------------------------------

def repo_files() -> list[str]:
    """Every non-gitignored file in the repo (tracked + untracked), sorted.

    Uses `git ls-files` so .gitignore is honored exactly (this excludes the
    agno/ symlink, node_modules, tmp, out/ dirs, ...). Falls back to a
    filesystem walk with a hardcoded skip list if git is unavailable.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(DOCS_ROOT), "ls-files",
             "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, check=True,
        )
        rels = {p for p in proc.stdout.decode("utf-8").split("\0") if p}
        # Drop tracked-but-deleted entries and directory symlinks.
        return sorted(p for p in rels if (DOCS_ROOT / p).is_file())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        found = []
        for path in DOCS_ROOT.rglob("*"):
            rel = path.relative_to(DOCS_ROOT)
            if any(part in _WALK_SKIP or part.startswith(".") for part in rel.parts):
                continue
            if path.is_file() and not path.is_symlink():
                found.append(rel.as_posix())
        return sorted(found)


_text_cache: dict[str, str] = {}


def read_text(rel: str) -> str:
    """Read a repo file once; cached for the life of the process."""
    if rel not in _text_cache:
        _text_cache[rel] = (DOCS_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    return _text_cache[rel]


# ---------------------------------------------------------------------------
# docs.json navigation
# ---------------------------------------------------------------------------

def load_docs_json() -> dict:
    return json.loads(read_text("docs.json"))


def nav_page_entries(docs: dict | None = None) -> list[str]:
    """Every page path string in docs.json navigation, in order, with dupes.

    Walks the whole navigation tree so any Mintlify nesting works
    (tabs/groups/dropdowns/anchors/versions/languages): a page is any string
    leaf found inside a "pages" (or "root") subtree. Strings under "href",
    "openapi", "icon", titles, etc. are not pages. External URLs and anchors
    are normalized away.
    """
    docs = docs if docs is not None else load_docs_json()
    found: list[str] = []

    def walk(node, in_pages: bool):
        if isinstance(node, str):
            if in_pages and not node.startswith(("http://", "https://")):
                entry = node.split("#")[0].strip("/")
                if entry:
                    found.append(entry)
        elif isinstance(node, list):
            for item in node:
                walk(item, in_pages)
        elif isinstance(node, dict):
            for key, val in node.items():
                if key in ("pages", "root"):
                    walk(val, True)
                elif key == "href":
                    continue
                else:
                    walk(val, False)

    walk(docs.get("navigation", {}), False)
    return found


def page_slug(rel: str) -> str:
    """foo/bar.mdx -> foo/bar."""
    for ext in (".mdx", ".md"):
        if rel.endswith(ext):
            return rel[: -len(ext)]
    return rel


def slug_file(slug: str) -> str | None:
    """foo/bar -> foo/bar.mdx if it exists on disk (else .md, else None)."""
    for ext in (".mdx", ".md"):
        rel = slug + ext
        if (DOCS_ROOT / rel).is_file():
            return rel
    return None


# ---------------------------------------------------------------------------
# Shared context: reachability + snippet graph
# ---------------------------------------------------------------------------

class Context:
    """Lazily computed shared state so run_all.py does the work once."""

    def __init__(self):
        self._files = None
        self._docs = None
        self._nav = None
        self._snippet_direct = None
        self._snippet_closure: dict[str, frozenset[str]] = {}

    @property
    def files(self) -> list[str]:
        if self._files is None:
            self._files = repo_files()
        return self._files

    @property
    def docs_json(self) -> dict:
        if self._docs is None:
            self._docs = load_docs_json()
        return self._docs

    @property
    def nav_entries(self) -> list[str]:
        """All nav page strings, in order, with duplicates."""
        if self._nav is None:
            self._nav = nav_page_entries(self.docs_json)
        return self._nav

    @property
    def nav_set(self) -> set[str]:
        return set(self.nav_entries)

    @property
    def page_files(self) -> dict[str, str]:
        """slug -> rel path for every content page (.mdx outside _snippets/)."""
        return {
            page_slug(f): f
            for f in self.files
            if f.endswith(".mdx") and not f.startswith(SNIPPET_DIR + "/")
        }

    @property
    def live_pages(self) -> set[str]:
        """Nav entries that exist on disk (slugs)."""
        return {e for e in self.nav_set if slug_file(e)}

    @property
    def orphan_pages(self) -> set[str]:
        """Pages on disk not reachable from navigation (slugs)."""
        return {s for s in self.page_files if s not in self.nav_set}

    @property
    def nav_missing_file(self) -> set[str]:
        """Nav entries with no file on disk."""
        return {e for e in self.nav_set if not slug_file(e)}

    @property
    def snippet_files(self) -> list[str]:
        """Every .mdx under _snippets/."""
        return [f for f in self.files
                if f.startswith(SNIPPET_DIR + "/") and f.endswith(".mdx")]

    @property
    def snippet_direct(self) -> dict[str, list[str]]:
        """rel path -> snippet rel paths it directly includes, for every .mdx.

        Includes dangling refs (snippet names with no file) so callers can
        report them; check membership in snippet_files to filter.
        """
        if self._snippet_direct is None:
            graph = {}
            for f in self.files:
                if f.endswith(".mdx"):
                    refs = SNIPPET_RE.findall(read_text(f))
                    graph[f] = [f"{SNIPPET_DIR}/{name}" for name in refs]
            self._snippet_direct = graph
        return self._snippet_direct

    def snippets_of(self, rel: str) -> frozenset[str]:
        """All snippet files transitively included by rel (page or snippet)."""
        if rel in self._snippet_closure:
            return self._snippet_closure[rel]
        seen: set[str] = set()
        stack = list(self.snippet_direct.get(rel, []))
        while stack:
            snip = stack.pop()
            if snip in seen or not (DOCS_ROOT / snip).is_file():
                continue
            seen.add(snip)
            stack.extend(self.snippet_direct.get(snip, []))
        result = frozenset(seen)
        self._snippet_closure[rel] = result
        return result


# ---------------------------------------------------------------------------
# Markdown processing
# ---------------------------------------------------------------------------

def blank_noncontent_lines(text: str) -> list[str]:
    """Lines of text with fenced code blocks and YAML frontmatter blanked out,
    preserving line numbers. Used before link/heading extraction."""
    lines = text.split("\n")
    out = []
    fence: str | None = None  # opening fence string while inside a block
    in_frontmatter = False
    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            out.append("")
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
            out.append("")
            continue
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append("")
            else:
                out.append(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
    return out


def slugify(heading: str) -> str:
    """GitHub/Mintlify-style anchor slug for a heading."""
    h = heading.strip()
    h = CUSTOM_ID_RE.sub("", h)
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)  # [text](url) -> text
    h = h.replace("`", "").replace("*", "")
    h = h.lower()
    h = re.sub(r"[^\w\s-]", "", h)
    h = re.sub(r"\s", "-", h)
    return h


def _loose(anchor: str) -> str:
    return re.sub(r"-{2,}", "-", anchor.lower()).strip("-")


def page_anchors(rel: str, ctx: Context) -> tuple[set[str], set[str]]:
    """(exact, loose) anchor sets for a page: slugified headings (own +
    transitively included snippets, with github-slugger -N dedupe suffixes),
    {#custom-id} ids, and literal id="..." attributes."""
    exact: set[str] = set()
    counts: dict[str, int] = {}
    sources = [rel] + sorted(ctx.snippets_of(rel))
    for src in sources:
        text = read_text(src)
        for line in blank_noncontent_lines(text):
            m = HEADING_RE.match(line)
            if not m:
                continue
            title = m.group(2)
            custom = CUSTOM_ID_RE.search(title)
            if custom:
                exact.add(custom.group(1))
            base = slugify(title)
            if not base:
                continue
            n = counts.get(base, 0)
            counts[base] = n + 1
            exact.add(base if n == 0 else f"{base}-{n}")
        for html_id in HTML_ID_RE.findall(text):
            exact.add(html_id)
    return exact, {_loose(a) for a in exact}


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------

def normalize_path(p: str) -> str:
    """Strip anchor, query, and surrounding slashes: /foo/bar#x -> foo/bar."""
    return p.split("#")[0].split("?")[0].strip("/")


def is_external(p: str) -> bool:
    return p.startswith(("http://", "https://", "mailto:"))


def is_wildcard(p: str) -> bool:
    return ":" in normalize_path(p)


def compile_source_pattern(source: str) -> re.Pattern:
    """Compile a Mintlify redirect source (:param, :param*) to a regex that
    matches normalized page slugs. A trailing :param* also matches the bare
    prefix (catch-alls match zero or more segments)."""
    parts = normalize_path(source).split("/")
    rx = []
    for i, part in enumerate(parts):
        if part.startswith(":") and part.endswith("*"):
            if i == len(parts) - 1:
                prefix = "/".join(rx)
                if prefix:
                    return re.compile(f"^{prefix}(?:/.+)?$")
                return re.compile("^.*$")
            rx.append(".+")
        elif part.startswith(":"):
            rx.append("[^/]+")
        else:
            rx.append(re.escape(part))
    return re.compile("^" + "/".join(rx) + "$")


def wildcard_base(path: str) -> str:
    """Literal prefix of a wildcard path: /foo/:slug* -> foo."""
    parts = []
    for part in normalize_path(path).split("/"):
        if part.startswith(":"):
            break
        parts.append(part)
    return "/".join(parts)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(name: str, data: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def make_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--json", action="store_true",
                   help="also write the full report to scripts/inventory/out/<name>.json")
    p.add_argument("--limit", type=int, default=25,
                   help="max items per list on stdout (0 = all; default 25)")
    return p


def print_counts(counts: dict) -> None:
    width = max(len(k) for k in counts)
    for key, val in counts.items():
        print(f"  {key:<{width}}  {val}")


def print_list(title: str, items: list, limit: int) -> None:
    print(f"\n{title} ({len(items)}):")
    shown = items if limit == 0 else items[:limit]
    for item in shown:
        print(f"  {item}")
    if limit and len(items) > limit:
        print(f"  ... {len(items) - limit} more (use --limit 0 or --json for all)")


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"
