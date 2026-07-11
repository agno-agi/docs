#!/usr/bin/env python3
"""Extract agno import lines from python code blocks in .mdx files and test them
against the running venv (each statement is exec'd with sys.executable, so run
this with a venv python that has agno installed). Failures caused only by
missing third-party deps are statically verified against the agno source tree
(module + names must exist). Reports REAL failures (agno-side module/name
missing) grouped by statement; exits 1 if any.

Agno repo defaults to the ./agno symlink at the repo root; override with the
AGNO_REPO env var.

Usage:
    python scripts/check_imports.py
"""
import ast
import os
import re
import subprocess
import sys
import json

DOCS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = sys.executable
AGNO_SRC = os.path.join(
    os.environ.get("AGNO_REPO") or os.path.join(DOCS_ROOT, "agno"),
    "libs", "agno", "agno",
)

EXCLUDE_DIRS = {"deploy", "TBD", "examples", "agno", "node_modules", ".git", "scripts"}
EXCLUDE_FILES = {
    os.path.join(DOCS_ROOT, "other", "v2-migration.mdx"),
    os.path.join(DOCS_ROOT, "other", "v2-changelog.mdx"),
}

# This page intentionally shows a complete Workflows 1.0 example before the
# current Workflows 2.0 replacement. Skip only the legacy block so imports in
# the replacement example remain covered.
LEGACY_BLOCK_MARKERS = {
    os.path.join(DOCS_ROOT, "other", "workflows-migration.mdx"): (
        "from agno.storage.sqlite import SqliteStorage",
    ),
}

CODEBLOCK_RE = re.compile(r"```(\w+)?[^\n]*\n(.*?)```", re.DOTALL)
IMPORT_START_RE = re.compile(r"^\s*(from\s+agno[.\s]|import\s+agno)")


def iter_mdx_files():
    for dirpath, dirnames, filenames in os.walk(DOCS_ROOT):
        rel = os.path.relpath(dirpath, DOCS_ROOT)
        parts = rel.split(os.sep)
        if parts[0] in EXCLUDE_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not (rel == "." and d in EXCLUDE_DIRS) and d != ".git"]
        for fn in filenames:
            if fn.endswith(".mdx"):
                path = os.path.join(dirpath, fn)
                if path not in EXCLUDE_FILES:
                    yield path


def extract_imports(text, legacy_markers=()):
    for m in CODEBLOCK_RE.finditer(text):
        lang = (m.group(1) or "").lower()
        if lang not in ("python", "py"):
            continue
        body = m.group(2)
        if any(marker in body for marker in legacy_markers):
            continue
        lines = body.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if IMPORT_START_RE.match(line):
                stmt = line.strip()
                if "(" in stmt and ")" not in stmt:
                    j = i + 1
                    while j < len(lines):
                        stmt += " " + lines[j].strip()
                        if ")" in lines[j]:
                            break
                        j += 1
                    i = j
                stmt = re.sub(r"\s+#.*$", "", stmt)
                yield stmt
            i += 1


def module_file(dotted):
    """Resolve agno.x.y to a source file, or None."""
    assert dotted == "agno" or dotted.startswith("agno.")
    rel = dotted.split(".")[1:]
    base = os.path.join(AGNO_SRC, *rel)
    if os.path.isfile(base + ".py"):
        return base + ".py"
    if os.path.isfile(os.path.join(base, "__init__.py")):
        return os.path.join(base, "__init__.py")
    return None


_names_cache = {}


def module_names(path):
    """Top-level names defined in a module source file (incl. inside try/if)."""
    if path in _names_cache:
        return _names_cache[path]
    names = set()
    tree = ast.parse(open(path, encoding="utf-8").read())

    def collect(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    if a.name == "*":
                        continue
                    names.add(a.asname or a.name.split(".")[0] if isinstance(node, ast.Import) else (a.asname or a.name))
            elif isinstance(node, ast.If):
                collect(node.body)
                collect(node.orelse)
            elif isinstance(node, ast.Try):
                collect(node.body)
                for h in node.handlers:
                    collect(h.body)
                collect(node.orelse)
                collect(node.finalbody)
    collect(tree.body)
    _names_cache[path] = names
    return names


def static_check(stmt):
    """Return None if statement resolves against agno source, else error string."""
    try:
        tree = ast.parse(stmt)
    except SyntaxError as e:
        return f"static: syntax error: {e}"
    node = tree.body[0]
    if isinstance(node, ast.Import):
        for a in node.names:
            if a.name == "agno" or a.name.startswith("agno."):
                if module_file(a.name) is None:
                    return f"static: no module {a.name} in source"
        return None
    if isinstance(node, ast.ImportFrom):
        mod = node.module
        mf = module_file(mod)
        if mf is None:
            return f"static: no module {mod} in source"
        # `from agno.x import name` where name may itself be a submodule
        defined = module_names(mf)
        for a in node.names:
            if a.name == "*":
                continue
            if a.name in defined:
                continue
            if module_file(mod + "." + a.name) is not None:
                continue
            return f"static: name '{a.name}' not in {mod}"
        return None
    return "static: not an import statement"


REAL_FAIL_RE = re.compile(
    r"(ModuleNotFoundError: No module named 'agno[.']"
    r"|ImportError: cannot import name .* from 'agno)"
)


def main():
    if not os.path.isdir(AGNO_SRC):
        sys.exit(f"error: agno source not found at {AGNO_SRC}; "
                 "create the ./agno symlink at the repo root or set AGNO_REPO")
    stmt_files = {}
    for path in iter_mdx_files():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for stmt in extract_imports(text, LEGACY_BLOCK_MARKERS.get(path, ())):
            stmt_files.setdefault(stmt, set()).add(path)

    print(f"Found {len(stmt_files)} unique agno import statements", file=sys.stderr)

    real_failures = {}
    dep_only = 0
    ok_count = 0
    for stmt in sorted(stmt_files):
        r = subprocess.run([VENV_PY, "-c", stmt], capture_output=True, text=True)
        if r.returncode == 0:
            ok_count += 1
            continue
        err = r.stderr.strip().split("\n")[-1]
        if REAL_FAIL_RE.search(err):
            real_failures[stmt] = {"error": err, "files": sorted(stmt_files[stmt])}
            continue
        # dependency-blocked: verify statically against source
        serr = static_check(stmt)
        if serr is None:
            dep_only += 1
        else:
            real_failures[stmt] = {"error": f"{err} | {serr}", "files": sorted(stmt_files[stmt])}

    print(f"OK: {ok_count}  dep-only (verified in source): {dep_only}  REAL FAIL: {len(real_failures)}", file=sys.stderr)
    print(json.dumps(real_failures, indent=2))
    return 1 if real_failures else 0


if __name__ == "__main__":
    sys.exit(main())
