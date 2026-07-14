#!/usr/bin/env python3
"""Post-sync integrity checks for an examples sync run.

Reads the plan from out/sync-plan.json (run plan.py first) and verifies:
  (a) frontmatter shape, fence balance, and source field on every generated page
  (b) every cookbook path referenced under examples/ exists in the cookbook
  (c) pages the plan flagged as fence-mangled now carry the full cookbook source
  (d) file inventory report (mdx count, stray non-mdx files, git status summary)
  (e) PRESERVE_CURATED pages untouched (per git status)

Writes out/integrity-log.json; exits 1 if any check fails.

Usage:
    python scripts/examples_sync/check_integrity.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS_ROOT = HERE.parents[1]
AGNO_ROOT = Path(os.environ.get("AGNO_REPO") or DOCS_ROOT / "agno")
COOKBOOK = AGNO_ROOT / "cookbook"
OUT_DIR = HERE / "out"
PLAN_PATH = OUT_DIR / "sync-plan.json"

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


def extract_first_code_block(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(`{3,})python\b", line.strip())
        if not m:
            continue
        run = len(m.group(1))
        for j in range(i + 1, len(lines)):
            s = lines[j].strip()
            if s == "`" * len(s) and len(s) >= run and s.startswith("`"):
                return "\n".join(lines[i + 1 : j])
        return None
    return None


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
    re.compile(r"cd agno/(cookbook/[^\s`\"']+)"),
    re.compile(r"github\.com/agno-agi/agno/(?:blob|tree)/[^/\s]+/(cookbook/[^)\s\"'`]+)"),
]
gen_slugs = {t[0] for t in gen_tasks}
b_bad_gen, b_bad_other = [], []
all_mdx = sorted((DOCS_ROOT / "examples").rglob("*.mdx"))
for p in all_mdx:
    slug = str(p.relative_to(DOCS_ROOT)).removesuffix(".mdx")
    text = p.read_text(encoding="utf-8")
    for rx in ref_res:
        for ref in rx.findall(text):
            ref = ref.rstrip(".,)")
            tail = ref.removeprefix("cookbook/")
            target = COOKBOOK / tail
            if not (target.is_file() or target.is_dir()):
                (b_bad_gen if slug in gen_slugs else b_bad_other).append((slug, ref))
print(f"(b) cookbook refs: {len(all_mdx)} files scanned; "
      f"{len(b_bad_gen)} dead refs in generated pages, {len(b_bad_other)} in preserved pages")
for s, r in (b_bad_gen + b_bad_other)[:25]:
    print("   DEAD:", s, "->", r)
problems += [f"(b) generated {s}: dead ref {r}" for s, r in b_bad_gen]

# ---------------------------------------------------------------------------
# (c) pages the plan flagged as fence-mangled carry the complete cookbook source
# ---------------------------------------------------------------------------
mangled = [e for e in plan["pages"] if e.get("mangled")]
c_bad = []
for e in mangled:
    p = DOCS_ROOT / f"{e['slug']}.mdx"
    rel = e.get("new_cookbook_path") or e["cookbook_path"]
    code = extract_first_code_block(p.read_text(encoding="utf-8"))
    want = (COOKBOOK / rel).read_text(encoding="utf-8").strip("\n")
    if code is None or code.strip("\n") != want:
        c_bad.append(e["slug"])
print(f"(c) mangled pages: {len(mangled)} checked, {len(c_bad)} still broken")
for s in c_bad:
    print("   STILL BROKEN:", s)
problems += [f"(c) {s} code block != cookbook source" for s in c_bad]

# ---------------------------------------------------------------------------
# (d) file inventory report (informational; only stray non-mdx files fail)
# ---------------------------------------------------------------------------
n_files = len(all_mdx)
non_mdx = [str(p) for p in (DOCS_ROOT / "examples").rglob("*") if p.is_file() and p.suffix != ".mdx"]
print(f"(d) files under examples/: {n_files} mdx; non-mdx files: {len(non_mdx)}")
for f in non_mdx[:10]:
    print("   NON-MDX:", f)
problems += [f"(d) non-mdx file under examples/: {f}" for f in non_mdx]

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
print(f"(d) git status under examples/: {dict(st)}; entries outside examples/: {len(outside)}")

# ---------------------------------------------------------------------------
# (e) PRESERVE_CURATED untouched (all of them, not just a sample)
# ---------------------------------------------------------------------------
changed = {line[3:] for line in status}
preserve = [e["slug"] for e in plan["pages"] if e["class"] == "PRESERVE_CURATED"]
e_bad = [s for s in preserve if f"{s}.mdx" in changed]
print(f"(e) PRESERVE_CURATED: {len(preserve)} slugs, {len(e_bad)} appear in git status")
for s in e_bad[:10]:
    print("   TOUCHED:", s)
problems += [f"(e) curated page touched: {s}" for s in e_bad]

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
