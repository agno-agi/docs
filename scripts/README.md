# Docs maintenance scripts

Tooling for keeping the docs in sync with the agno repo across releases. Every
script resolves the docs repo root from its own location and runs from
anywhere; all generated artifacts land in gitignored `out/` directories.

## Tools

| Script | What it does |
|--------|--------------|
| `examples_sync/plan.py` | Classifies every Examples-tab page against the cookbook (KEEP_VERBATIM, REGEN, REMAP_REGEN, PRESERVE_CURATED, DELETE, NEW). Writes `examples_sync/out/sync-plan.json`, `nav-examples-tab.json`, `redirects.json`. Read-only outside `out/`. |
| `examples_sync/merge_nav.py` | Adds proposed NEW routes to the current Examples tab without removing, moving, or reordering any live route. `--check` verifies convergence without writing. |
| `examples_sync/generate.py` | Renders one cookbook file to a docs page (`--stdout` to preview). Also the library the pipeline scripts import. |
| `examples_sync/drive_sync.py` | Executes the plan: regenerates every planned page under `examples/`, writes `out/gen-log.json` and the DELETE list to `out/rm-list.txt`. Never deletes pages. `--check` diffs renders against disk without writing. |
| `examples_sync/dedupe_titles.py` | Retitles pages whose titles collide within a nav group (stem-derived, parent-prefixed on repeat collision). `--check` previews. |
| `examples_sync/apply_oneoffs.py` | Hand-curated fixes regeneration cannot derive, plus a title-casing pass. Idempotent; every fix is applied, already applied, or an error. `--check` previews. |
| `examples_sync/check_integrity.py` | Post-sync verification: frontmatter shape, fence balance, `source:` fields, dead cookbook refs, mangled pages, curated pages untouched. Exits 1 on problems. |
| `examples_sync/description-overrides.json` | Hand-written frontmatter descriptions keyed by slug; consumed by `generate.py`. Curated data, checked in. |
| `reference_drift.py` | Compares every `reference/**` parameter table against agno source signatures (runtime introspection, AST fallback). Writes `out/drift-report.json`: missing, phantom, wrong-default params per page. Read-only. |
| `make_openapi.py` | Builds a representative AgentOS app offline and dumps its OpenAPI spec to `out/openapi.{json,yaml}` plus a structured diff against `reference-api/openapi.yaml` in `out/openapi-diff.md`. Validates operation IDs, runtime enrichments, endpoint stubs, and navigation. Never touches `reference-api/` itself. |
| `check_imports.py` | Extracts every agno import from python code blocks in non-example docs pages and executes each against the running venv; third-party-dep failures are verified statically against agno source. Exits 1 on real (agno-side) failures. |

## Requirements

Python 3.10+. The `examples_sync/` pipeline and `plan.py` use the stdlib only.
The rest need a venv with agno installed; run them with that venv's python:

| Script | Venv needs |
|--------|-----------|
| `reference_drift.py` | `agno` importable. `agno[os,mcp]` plus provider SDKs widen runtime-introspection coverage; unimportable modules fall back to pure-AST extraction. |
| `make_openapi.py` | `agno[os,mcp,telegram,agui,a2a,slack,openai]` and `pyyaml`. Missing interface extras exclude their routes and are reported in the diff output. |
| `check_imports.py` | `agno` installed. Statements failing only on missing third-party deps still pass via the static source check. |

## Environment variables

| Variable | Effect |
|----------|--------|
| `AGNO_REPO` | Path to the agno repo. Default: the `./agno` symlink at the docs repo root. |
| `AGNO_EXPECTED_SHA` | Full commit SHA required by `make_openapi.py`. The SHA must match `AGNO_REPO`. |
| `DESC_OVERRIDES_JSON` | Alternate path for `description-overrides.json`. Default: next to `generate.py`. |

## Release-time flow

After an Agno release, check out the exact release tag in `AGNO_REPO` and record
its full commit SHA.

1. `python scripts/examples_sync/plan.py`, then review
   `examples_sync/out/sync-plan.json`. Slug conflicts and `unplaced_new`
   entries need a human decision before executing.
2. `python scripts/examples_sync/drive_sync.py --check` to preview, then
   without `--check` to write. Run `python scripts/examples_sync/merge_nav.py`
   to add NEW routes without removing current routes. Review
   `examples_sync/out/rm-list.txt` and `redirects.json`; remove routes or files
   and add redirects only after each deletion is approved.
3. `python scripts/examples_sync/dedupe_titles.py`, then
   `python scripts/examples_sync/apply_oneoffs.py`.
4. `python scripts/examples_sync/check_integrity.py` and fix anything it
   reports.
5. `python scripts/reference_drift.py`, then work through
   `out/drift-report.json` against the `reference/**` tables.
6. At GA only, generate the AgentOS API reference from the reviewed source:

   ```bash
   AGNO_REPO=/path/to/agno \
   AGNO_EXPECTED_SHA=$(git -C /path/to/agno rev-parse HEAD) \
   python scripts/make_openapi.py
   ```

   Review every endpoint and schema in `out/openapi-diff.md`. The generator
   applies the Slack header, form body, and HITL description enrichments and
   fails if their source operations change. After review, update both tracked
   specifications together:

   ```bash
   cp scripts/out/openapi.json reference-api/openapi.json
   cp scripts/out/openapi.yaml reference-api/openapi.yaml
   ```

   Add source-backed schema pages and `docs.json` entries for new endpoints.
   Preserve pages for removed endpoints until their removal is approved.
   Finish with `python scripts/make_openapi.py --check`.
7. Run `python scripts/check_imports.py`, `mint broken-links -t false`, and
   `mint validate -t false`.
