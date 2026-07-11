"""Dry-run generator for the AgentOS OpenAPI spec.

Builds a representative AgentOS app (no serving, no network) covering the
surface of the reference-api spec, dumps app.openapi() to
scripts/out/openapi.json / openapi.yaml, and writes a structured diff against
the checked-in reference-api/openapi.yaml to scripts/out/openapi-diff.md.

Never touches reference-api/ itself: review the diff, then copy
scripts/out/openapi.yaml over reference-api/openapi.yaml by hand.

Run with a venv where agno[os,mcp,telegram,agui,a2a,slack] is importable:
  python scripts/make_openapi.py

Interfaces whose optional dependency is missing (e.g. a2a-sdk for A2A) are
excluded from the app and reported in the generator notes.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent / "out"
OLD_YAML = REPO_ROOT / "reference-api/openapi.yaml"
NEW_JSON = OUT_DIR / "openapi.json"
NEW_YAML = OUT_DIR / "openapi.yaml"
DIFF_MD = OUT_DIR / "openapi-diff.md"

# Fake credentials: everything is constructed offline, nothing is called.
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-not-a-real-key")
os.environ.setdefault("SLACK_TOKEN", "xoxb-fake-token")
os.environ.setdefault("SLACK_SIGNING_SECRET", "fake-signing-secret")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "fake-whatsapp-access-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "0000000000")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "fake-verify-token")
os.environ.setdefault("TELEGRAM_TOKEN", "123456789:AAFakeTokenValueForOpenAPIGenerationOnly")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET_TOKEN", "fake-telegram-webhook-secret")
os.environ.setdefault("AGNO_TELEMETRY", "false")

import yaml  # noqa: E402
from agno import __version__ as agno_version  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.knowledge.knowledge import Knowledge  # noqa: E402
from agno.models.openai import OpenAIChat  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.registry import Registry  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.workflow import Workflow  # noqa: E402
from agno.workflow.step import Step  # noqa: E402

NOTES = []  # inclusion/exclusion notes surfaced at the end of the run

# Interface imports are optional: each pulls in an extra (a2a-sdk, ag-ui-protocol,
# slack-sdk, ...) that may be absent from the venv. Missing ones are excluded
# from the generated spec and reported, instead of failing the whole run.
try:
    from agno.os.interfaces.a2a import A2A  # noqa: E402
except ImportError as _e:
    A2A = None
    NOTES.append(f"interface A2A: EXCLUDED, import failed: {_e}")
try:
    from agno.os.interfaces.agui import AGUI  # noqa: E402
except ImportError as _e:
    AGUI = None
    NOTES.append(f"interface AGUI: EXCLUDED, import failed: {_e}")
try:
    from agno.os.interfaces.slack import Slack  # noqa: E402
except ImportError as _e:
    Slack = None
    NOTES.append(f"interface Slack: EXCLUDED, import failed: {_e}")
try:
    from agno.os.interfaces.whatsapp import Whatsapp  # noqa: E402
except ImportError as _e:
    Whatsapp = None
    NOTES.append(f"interface Whatsapp: EXCLUDED, import failed: {_e}")
try:
    from agno.os.interfaces.telegram import Telegram  # noqa: E402
except ImportError as _e:
    Telegram = None
    NOTES.append(f"interface Telegram: EXCLUDED, import failed: {_e}")


def build_app():
    db = SqliteDb(db_file=str(OUT_DIR / "agentos-dryrun.db"))

    knowledge = None
    try:
        knowledge = Knowledge(name="Agno Docs", contents_db=db)
        NOTES.append("knowledge: included (Knowledge with contents_db only; no vector db needed offline)")
    except Exception as e:  # pragma: no cover - defensive
        NOTES.append(f"knowledge: EXCLUDED, construction failed: {e}")

    registry = Registry(
        name="Agno Registry",
        models=[OpenAIChat(id="gpt-5.2")],
        dbs=[db],
    )

    simple_agent = Agent(
        name="Simple Agent",
        role="Simple agent",
        id="simple-agent",
        model=OpenAIChat(id="gpt-5.2"),
        instructions=["You are a simple agent"],
        db=db,
        knowledge=knowledge,
    )

    simple_team = Team(
        name="Simple Team",
        description="A team of agents",
        members=[simple_agent],
        model=OpenAIChat(id="gpt-5.2"),
        id="simple-team",
        instructions=["You are the team lead."],
        db=db,
        markdown=True,
    )

    simple_workflow = Workflow(
        name="Simple Workflow",
        id="simple-workflow",
        description="A simple workflow",
        db=db,
        steps=[Step(name="step-1", agent=simple_agent)],
    )

    interfaces = []
    if Slack is not None:
        try:
            interfaces.append(
                Slack(
                    agent=simple_agent,
                    token=os.environ["SLACK_TOKEN"],
                    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
                )
            )
            NOTES.append("interface Slack: included (token/signing_secret passed as fake strings)")
        except Exception as e:
            NOTES.append(f"interface Slack: EXCLUDED, construction failed: {e}")
    if Whatsapp is not None:
        try:
            interfaces.append(
                Whatsapp(
                    agent=simple_agent,
                    access_token=os.environ["WHATSAPP_ACCESS_TOKEN"],
                    phone_number_id=os.environ["WHATSAPP_PHONE_NUMBER_ID"],
                    verify_token=os.environ["WHATSAPP_VERIFY_TOKEN"],
                )
            )
            NOTES.append("interface Whatsapp: included (fake meta credentials, encryption disabled)")
        except Exception as e:
            NOTES.append(f"interface Whatsapp: EXCLUDED, construction failed: {e}")
    if Telegram is not None:
        try:
            interfaces.append(
                Telegram(
                    agent=simple_agent,
                    token=os.environ["TELEGRAM_TOKEN"],
                )
            )
            NOTES.append("interface Telegram: included (fake token; status and webhook routes)")
        except Exception as e:
            NOTES.append(f"interface Telegram: EXCLUDED, construction failed: {e}")
    if AGUI is not None:
        try:
            interfaces.append(AGUI(agent=simple_agent))
            NOTES.append("interface AGUI: included")
        except Exception as e:
            NOTES.append(f"interface AGUI: EXCLUDED, construction failed: {e}")
    if A2A is not None:
        try:
            interfaces.append(A2A(agents=[simple_agent], teams=[simple_team], workflows=[simple_workflow]))
            NOTES.append("interface A2A: included (agents + teams + workflows)")
        except Exception as e:
            NOTES.append(f"interface A2A: EXCLUDED, construction failed: {e}")
    agent_os = AgentOS(
        id="agentos-demo",
        name="Agno API Reference",
        version=agno_version,
        description="The all-in-one, private, secure agent platform that runs in your cloud.",
        agents=[simple_agent],
        teams=[simple_team],
        workflows=[simple_workflow],
        knowledge=[knowledge] if knowledge else None,
        interfaces=interfaces,
        registry=registry,
        db=db,
        mcp_server=True,  # mounts /mcp sub-app; sub-app routes don't appear in app.openapi()
        telemetry=False,  # telemetry POSTs home at init; this is an offline dry run
    )
    return agent_os.get_app()


# --- YAML dumping shaped like the existing reference-api/openapi.yaml ----------


class IndentedDumper(yaml.SafeDumper):
    """Indent block sequences under their key, matching the existing openapi.yaml."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str_representer(dumper, value):
    # The old file renders multiline strings as |- block scalars.
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


IndentedDumper.add_representer(str, _str_representer)


def dump_yaml(spec: dict, path: Path) -> None:
    # Mirror the old file's top-level key order: openapi, info, paths, components.
    ordered = {}
    for key in ("openapi", "info", "paths", "components"):
        if key in spec:
            ordered[key] = spec[key]
    for key in spec:
        if key not in ordered:
            ordered[key] = spec[key]
    with open(path, "w") as f:
        yaml.dump(
            ordered,
            f,
            Dumper=IndentedDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100000,  # old file never wraps scalar lines
        )


# --- Differ ---------------------------------------------------------------------

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def operations(spec: dict) -> dict:
    """Map 'METHOD /path' -> operation object."""
    ops = {}
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if method in HTTP_METHODS:
                ops[f"{method.upper()} {path}"] = op
    return ops


def op_fingerprint(op: dict) -> dict:
    """The parts of an operation that matter for 'changed' detection."""
    params = sorted(
        f"{p.get('in')}:{p.get('name')}:{'req' if p.get('required') else 'opt'}"
        for p in op.get("parameters", [])
        if isinstance(p, dict)
    )
    body = op.get("requestBody", {})
    responses = op.get("responses", {})
    return {
        "parameters": params,
        "requestBody": body.get("content", {}),
        "responses": {code: r.get("content", {}) for code, r in responses.items() if isinstance(r, dict)},
    }


def diff_specs(old: dict, new: dict) -> str:
    old_ops, new_ops = operations(old), operations(new)
    added = sorted(set(new_ops) - set(old_ops))
    removed = sorted(set(old_ops) - set(new_ops))
    common = sorted(set(old_ops) & set(new_ops))
    changed = []
    for key in common:
        old_fp, new_fp = op_fingerprint(old_ops[key]), op_fingerprint(new_ops[key])
        if old_fp != new_fp:
            reasons = []
            if old_fp["parameters"] != new_fp["parameters"]:
                added_p = set(new_fp["parameters"]) - set(old_fp["parameters"])
                removed_p = set(old_fp["parameters"]) - set(new_fp["parameters"])
                bits = []
                if added_p:
                    bits.append("+" + ", +".join(sorted(added_p)))
                if removed_p:
                    bits.append("-" + ", -".join(sorted(removed_p)))
                reasons.append("params: " + "; ".join(bits) if bits else "params reordered")
            if old_fp["requestBody"] != new_fp["requestBody"]:
                reasons.append("requestBody schema changed")
            if old_fp["responses"] != new_fp["responses"]:
                old_r, new_r = set(old_fp["responses"]), set(new_fp["responses"])
                bits = []
                if new_r - old_r:
                    bits.append("+codes " + ",".join(sorted(new_r - old_r)))
                if old_r - new_r:
                    bits.append("-codes " + ",".join(sorted(old_r - new_r)))
                same_codes_changed = [c for c in old_r & new_r if old_fp["responses"][c] != new_fp["responses"][c]]
                if same_codes_changed:
                    bits.append("response schema changed for " + ",".join(sorted(same_codes_changed)))
                reasons.append("responses: " + "; ".join(bits))
            changed.append((key, "; ".join(reasons)))

    old_schemas = set((old.get("components") or {}).get("schemas") or {})
    new_schemas = set((new.get("components") or {}).get("schemas") or {})

    lines = []
    lines.append("# OpenAPI diff: reference-api/openapi.yaml (old) vs generated spec (new)")
    lines.append("")
    lines.append(f"- Old: `{OLD_YAML}` (info.version `{old.get('info', {}).get('version')}`)")
    lines.append(f"- New: `{NEW_YAML}` (info.version `{new.get('info', {}).get('version')}`)")
    lines.append(f"- Operations: {len(old_ops)} old -> {len(new_ops)} new "
                 f"({len(added)} added, {len(removed)} removed, {len(changed)} changed)")
    lines.append(f"- Component schemas: {len(old_schemas)} old -> {len(new_schemas)} new "
                 f"({len(new_schemas - old_schemas)} added, {len(old_schemas - new_schemas)} removed)")
    lines.append("")

    lines.append(f"## Added endpoints ({len(added)})")
    lines.append("")
    for key in added:
        tag = (new_ops[key].get("tags") or ["-"])[0]
        summary = new_ops[key].get("summary", "")
        lines.append(f"- `{key}` [{tag}] {summary}")
    lines.append("")

    lines.append(f"## Removed endpoints ({len(removed)})")
    lines.append("")
    for key in removed:
        tag = (old_ops[key].get("tags") or ["-"])[0]
        summary = old_ops[key].get("summary", "")
        lines.append(f"- `{key}` [{tag}] {summary}")
    lines.append("")

    lines.append(f"## Changed operations ({len(changed)})")
    lines.append("")
    for key, reason in changed:
        lines.append(f"- `{key}`: {reason}")
    lines.append("")

    lines.append(f"## Added component schemas ({len(new_schemas - old_schemas)})")
    lines.append("")
    for name in sorted(new_schemas - old_schemas):
        lines.append(f"- `{name}`")
    lines.append("")

    lines.append(f"## Removed component schemas ({len(old_schemas - new_schemas)})")
    lines.append("")
    for name in sorted(old_schemas - new_schemas):
        lines.append(f"- `{name}`")
    lines.append("")

    lines.append("## info.version")
    lines.append("")
    lines.append(f"- `{old.get('info', {}).get('version')}` -> `{new.get('info', {}).get('version')}`")
    lines.append("")

    lines.append("## Generator notes (what the dry-run app includes/excludes)")
    lines.append("")
    for note in NOTES:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = build_app()
    spec = app.openapi()

    NEW_JSON.write_text(json.dumps(spec, indent=2) + "\n")
    dump_yaml(spec, NEW_YAML)

    old = yaml.safe_load(OLD_YAML.read_text())
    DIFF_MD.write_text(diff_specs(old, spec))

    print(f"agno {agno_version}")
    print(f"wrote {NEW_JSON} ({len(operations(spec))} operations, "
          f"{len((spec.get('components') or {}).get('schemas') or {})} schemas)")
    print(f"wrote {NEW_YAML}")
    print(f"wrote {DIFF_MD}")
    for note in NOTES:
        print("note:", note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
