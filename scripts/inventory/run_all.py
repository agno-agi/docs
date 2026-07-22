#!/usr/bin/env python3
"""Run all five inventory reports over one shared context and print a
combined counts summary.

Usage:
    python scripts/inventory/run_all.py [--json]

--json writes every report to scripts/inventory/out/<name>.json.
Always exits 0; this is an inventory, not a gate.
"""

from __future__ import annotations

import argparse
import sys

import _lib
import link_check
import orphans
import redirect_audit
import unused_media
import unused_snippets

MODULES = [
    ("orphans", orphans),
    ("unused_media", unused_media),
    ("unused_snippets", unused_snippets),
    ("redirect_audit", redirect_audit),
    ("link_check", link_check),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true",
                        help="write all five reports to scripts/inventory/out/")
    args = parser.parse_args(argv)

    ctx = _lib.Context()
    for name, module in MODULES:
        report = module.build_report(ctx)
        print(f"\n== {name} ==")
        _lib.print_counts(report["counts"])
        if name == "unused_media":
            print(f"  reclaimable        {report['reclaimable_human']}")
        if args.json:
            _lib.write_report(name, report)

    if args.json:
        print(f"\nReports written to {_lib.OUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
