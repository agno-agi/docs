#!/usr/bin/env python3
"""One-off page fixes that regeneration cannot derive. Run after
drive_sync.py + dedupe_titles.py, in that order.

Each fix asserts its precondition so a silent no-op is impossible: the fix is
either applied (old pattern found), already applied (new pattern found), or an
error. Idempotent: re-running after a regeneration re-applies exactly the same
edits. --check reports each fix's state without writing.

Usage:
    python scripts/examples_sync/apply_oneoffs.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate as gen  # noqa: E402

DOCS = HERE.parents[1] / "examples"

CHECK = False
would_apply = 0


def sub(path: str, old: str, new: str, required: bool = True) -> None:
    global would_apply
    p = DOCS / path
    text = p.read_text(encoding="utf-8")
    # `new` may contain `old` as a substring (insertion-style fixes), so the
    # already-applied test must run first or re-runs would apply twice.
    if new in text:
        print(f"  already applied: {path}")
        return
    if old not in text:
        assert not required, f"{path}: pattern not found: {old[:60]!r}"
        print(f"  skipped (pattern absent, optional): {path}")
        return
    if CHECK:
        print(f"  would apply: {path}")
        would_apply += 1
        return
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  applied: {path}")


def main() -> None:
    global CHECK
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report fix state without writing")
    CHECK = ap.parse_args().check

    # 1. Docstring title is the generic mode name; page is the structured-debate example.
    sub(
        "teams/modes/broadcast/structured-debate.mdx",
        'title: "Broadcast Mode"',
        'title: "Structured Debate"',
    )

    # 2. Digit-heavy stem (9_11_or_9_9) defeats the numeric-prefix strip; upstream
    #    docstring is a machine stub.
    sub("reasoning/models/groq/or-9-9.mdx", 'title: "11 or 9 9"', 'title: "9.11 or 9.9"')
    sub(
        "reasoning/models/groq/or-9-9.mdx",
        'description: "Runnable cookbook example: 11 or 9 9."',
        'description: "Groq reasoning model works through the classic 9.11 vs 9.9 comparison."',
    )

    # 3. google.auth.default() needs application-default credentials. The
    #    generator now derives the model-less Agent's OpenAI requirement.
    sub(
        "storage/gcs/gcs-json-for-agent.mdx",
        """  <Step title="Run the example">""",
        """  <Step title="Set up Google Cloud credentials">
    `google.auth.default()` needs application-default credentials and a project:
    ```bash
    gcloud auth application-default login
    ```
  </Step>

  <Step title="Run the example">""",
    )

    # 4. Curated page shipped with an empty description.
    sub(
        "tools/mcp/include-exclude-tools.mdx",
        'description: ""',
        'description: "Filter which MCP server tools an agent can use with include_tools '
        'and exclude_tools."',
        required=False,  # already fixed in place; keep idempotent
    )

    # 5. Curated page prose with an em dash.
    sub(
        "tools/models-lab-tools.mdx",
        "voiceover—all working",
        "voiceover, all working",
        required=False,
    )

    # 6. Title-casing pass over every page (fixes curated overview stubs:
    #    Openai -> OpenAI, Vertexai -> Vertex AI, Mcp Demo -> MCP Demo, ...).
    count = 0
    for p in sorted(DOCS.rglob("*.mdx")):
        text = p.read_text(encoding="utf-8")
        m = re.search(r'^title: "(.*)"$', text, re.M)
        if not m:
            continue
        old_t = m.group(1)
        new_t = gen.fix_title_casing(old_t)
        if new_t != old_t:
            if not CHECK:
                p.write_text(text.replace(f'title: "{old_t}"', f'title: "{new_t}"', 1), encoding="utf-8")
            count += 1

    if CHECK:
        print(f"check: {would_apply} fixes would apply; title-casing would change {count} pages")
    else:
        print(f"one-offs applied; title-casing fixed on {count} additional pages")


if __name__ == "__main__":
    main()
