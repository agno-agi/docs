"""Dry-run generator for the AgentOS OpenAPI spec.

Builds a representative AgentOS app (no serving, no network) covering the
surface of the reference-api spec, dumps app.openapi() to
scripts/out/openapi.json / openapi.yaml, and writes a structured diff against
the checked-in reference-api/openapi.yaml to scripts/out/openapi-diff.md.

Never touches reference-api/ itself. Review the diff before updating the
tracked JSON and YAML specifications together.

Run with a venv where agno[os,mcp,telegram,agui,a2a,slack,openai] and PyYAML
are importable. Set AGNO_REPO and AGNO_EXPECTED_SHA to the reviewed source:
  AGNO_REPO=/path/to/agno AGNO_EXPECTED_SHA=<full-sha> python scripts/make_openapi.py

Interfaces whose optional dependency is missing (e.g. a2a-sdk for A2A) are
excluded from the app and reported in the generator notes.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent / "out"
OLD_YAML = REPO_ROOT / "reference-api/openapi.yaml"
OLD_JSON = REPO_ROOT / "reference-api/openapi.json"
NEW_JSON = OUT_DIR / "openapi.json"
NEW_YAML = OUT_DIR / "openapi.yaml"
DIFF_MD = OUT_DIR / "openapi-diff.md"
DOCS_JSON = REPO_ROOT / "docs.json"
SCHEMA_DIR = REPO_ROOT / "reference-api" / "schema"

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
from agno.os import AgentOS, QueueConfig  # noqa: E402
from agno.registry import Registry  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.workflow import Workflow  # noqa: E402
from agno.workflow.step import Step  # noqa: E402

NOTES = []  # inclusion/exclusion notes surfaced at the end of the run


def verify_source_provenance() -> dict[str, str]:
    source_root = Path(os.environ.get("AGNO_REPO") or REPO_ROOT / "agno").resolve()
    pyproject = source_root / "libs" / "agno" / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError(f"Agno source pyproject not found at {pyproject}")

    project_match = re.search(
        r"(?ms)^\[project\]\s*$.*?^version\s*=\s*[\"']([^\"']+)[\"']\s*$",
        pyproject.read_text(),
    )
    if project_match is None:
        raise RuntimeError(f"Agno source version not found in {pyproject}")
    source_version = project_match.group(1)
    if source_version != agno_version:
        raise RuntimeError(
            f"Agno source version {source_version} does not match imported package version {agno_version}"
        )

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    source_sha = git("rev-parse", "HEAD")
    source_tag = git("describe", "--tags", "--exact-match", "HEAD")
    expected_tag = f"v{agno_version}"
    if source_tag != expected_tag:
        raise RuntimeError(f"Agno source tag {source_tag!r} does not match imported version {expected_tag!r}")

    expected_sha = os.environ.get("AGNO_EXPECTED_SHA")
    if not expected_sha:
        raise RuntimeError("AGNO_EXPECTED_SHA is required")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise RuntimeError("AGNO_EXPECTED_SHA must be a full lowercase commit SHA")
    if source_sha != expected_sha:
        raise RuntimeError(f"Agno source SHA {source_sha} does not match AGNO_EXPECTED_SHA {expected_sha}")

    return {
        "source_root": str(source_root),
        "source_sha": source_sha,
        "source_tag": source_tag,
        "source_version": source_version,
        "imported_module": str(Path(sys.modules["agno"].__file__).resolve()),
    }

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
        queue=QueueConfig(durable=True),
        mcp_server=True,  # mounts /mcp sub-app; sub-app routes don't appear in app.openapi()
        telemetry=False,  # telemetry POSTs home at init; this is an offline dry run
    )
    return agent_os.get_app()


def apply_runtime_description_enrichments(spec: dict) -> dict:
    """Document runtime branches that the pinned route metadata omits."""
    delete_component = spec["paths"]["/components/{component_id}"]["delete"]
    assert delete_component["description"] == "Delete a component by ID."
    delete_component["description"] = (
        "Soft-delete a component by ID. Component configs and links remain stored."
    )

    resume_workflow = spec["paths"]["/workflows/{workflow_id}/runs/{run_id}/resume"]["post"]
    bad_request = resume_workflow["responses"]["400"]
    assert bad_request["description"] == "Not supported for remote workflows"
    bad_request["description"] = (
        "Stream resumption is unavailable for remote and factory workflows. "
        "Non-admin callers must provide `session_id`."
    )

    list_agent_checkpoints = spec["paths"]["/agents/{agent_id}/runs/{run_id}/checkpoints"]["get"]
    assert list_agent_checkpoints["operationId"] == "list_agent_run_checkpoints"
    checkpoint_success = list_agent_checkpoints["responses"]["200"]
    assert checkpoint_success["description"] == "Run checkpoints retrieved successfully"
    assert checkpoint_success["content"]["application/json"]["schema"] == {}
    checkpoint_success["content"]["application/json"]["schema"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id", "session_id", "checkpoints"],
        "properties": {
            "run_id": {"type": "string"},
            "session_id": {"type": "string"},
            "checkpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "checkpoint_id",
                        "run_id",
                        "session_id",
                        "message_index",
                        "continue_from",
                        "status",
                        "reason",
                        "created_at",
                        "message_id",
                        "message_role",
                        "message_preview",
                        "is_latest",
                    ],
                    "properties": {
                        "checkpoint_id": {"type": "string"},
                        "run_id": {"type": ["string", "null"]},
                        "session_id": {"type": ["string", "null"]},
                        "message_index": {"type": "integer", "minimum": 0},
                        "continue_from": {"type": "integer", "minimum": 0},
                        "status": {"type": ["string", "null"]},
                        "reason": {"type": "string", "enum": ["checkpoint", "end"]},
                        "created_at": {"type": ["integer", "null"]},
                        "message_id": {"type": ["string", "null"]},
                        "message_role": {"type": ["string", "null"]},
                        "message_preview": {"type": ["string", "null"], "maxLength": 120},
                        "is_latest": {"type": "boolean"},
                    },
                },
            },
        },
    }

    continue_team_run = spec["paths"]["/teams/{team_id}/runs/{run_id}/continue"]["post"]
    assert continue_team_run["operationId"] == "continue_team_run"
    assert "202" not in continue_team_run["responses"]
    continue_team_run["responses"]["202"] = {
        "description": "Durable background continuation accepted",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["run_id", "session_id", "status"],
                    "properties": {
                        "run_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["PENDING"]},
                    },
                }
            }
        },
    }
    NOTES.append(
        "runtime response schemas: Agent checkpoint envelope and durable Team continuation acceptance"
    )

    list_team_runs = spec["paths"]["/teams/{team_id}/runs"]["get"]
    assert list_team_runs["operationId"] == "list_team_runs"
    list_team_runs_success = list_team_runs["responses"]["200"]
    assert list_team_runs_success["description"] == "List of runs retrieved successfully"
    assert list_team_runs_success["content"]["application/json"]["schema"] == {}
    list_team_runs_success["content"]["application/json"]["schema"] = {
        "type": "array",
        "items": {"$ref": "#/components/schemas/TeamRunSchema"},
    }
    status_parameter = next(
        parameter for parameter in list_team_runs["parameters"] if parameter["name"] == "status"
    )
    old_status_description = "Filter by run status (PENDING, RUNNING, COMPLETED, ERROR)"
    assert status_parameter["description"] == old_status_description
    assert status_parameter["schema"]["description"] == old_status_description
    status_values = [status.value for status in RunStatus]
    string_status_schema = next(
        branch
        for branch in status_parameter["schema"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert string_status_schema == {"type": "string"}
    string_status_schema["enum"] = status_values
    status_description = f"Filter by run status ({', '.join(status_values)})"
    status_parameter["description"] = status_description
    status_parameter["schema"]["description"] = status_description
    assert "403" not in list_team_runs["responses"]
    list_team_runs["responses"]["403"] = {"description": "Access denied to run this team"}
    NOTES.append(
        "runtime Team run-list schema: TeamRunSchema array, complete RunStatus filter, and authorization response"
    )

    component_config = spec["paths"]["/components/{component_id}/configs/{version}"]["get"]
    assert component_config["operationId"] == "get_config"
    component_config["operationId"] = "get_component_config"
    NOTES.append(
        "operationId enrichment: GET /components/{component_id}/configs/{version} "
        "uses get_component_config to avoid the pinned v3.0.4 get_config collision"
    )

    slack_events = spec["paths"]["/slack/events"]["post"]
    assert slack_events["description"] == "Process incoming Slack events"
    slack_events["description"] = (
        "Receives incoming Slack events (messages, mentions, thread starts).\n\n"
        "**URL Verification:** On first setup, Slack sends a `url_verification` challenge. "
        "The endpoint echoes back the challenge string.\n\n"
        "**Event Processing:** Normal events are acknowledged immediately with "
        "`{\"status\": \"ok\"}` and processed in the background. This prevents Slack's "
        "3-second retry timeout.\n\n"
        "**Retry Handling:** Events with `X-Slack-Retry-Num` header are duplicates and "
        "return 200 without reprocessing.\n\n"
        "**Setup:** Configure this URL in your [Slack App](https://api.slack.com/apps) "
        "under **Event Subscriptions > Request URL**.\n\n"
        "See the [setup guide](/agent-os/interfaces/slack/setup) for creating a Slack App "
        "or use the [manifest](/agent-os/interfaces/slack/setup#2-create-the-slack-app) "
        "for quick setup.\n"
    )
    slack_events["parameters"] = [
        {
            "name": "X-Slack-Request-Timestamp",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Unix timestamp when Slack sent the request",
        },
        {
            "name": "X-Slack-Signature",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "HMAC signature for request verification (v0=hash)",
        },
        {
            "name": "X-Slack-Retry-Num",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "Retry attempt number (present on retried events)",
        },
    ]

    slack_interactions = spec["paths"]["/slack/interactions"]["post"]
    assert slack_interactions["description"] == (
        "Handle Slack interactive components (HITL buttons / form submit)"
    )
    slack_interactions["description"] = (
        "Handles Slack interactive components for Human-in-the-Loop (HITL) workflows.\n\n"
        "**Supported Actions:**\n"
        "- `row_approve` - Approve a pending tool call\n"
        "- `row_reject` - Reject a pending tool call\n"
        "- `submit_pause` - Submit form data for a paused workflow\n\n"
        "**Setup:** Configure this URL in your [Slack App](https://api.slack.com/apps) "
        "under **Interactivity & Shortcuts > Request URL**.\n\n"
        "See the [setup guide](/agent-os/interfaces/slack/setup) for step-by-step "
        "instructions or the [HITL guide](/agent-os/interfaces/slack/hitl) for approval "
        "workflows.\n"
    )
    slack_interactions["parameters"] = [
        {
            "name": "X-Slack-Request-Timestamp",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Unix timestamp when Slack sent the request",
        },
        {
            "name": "X-Slack-Signature",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "HMAC signature for request verification (v0=hash)",
        },
    ]
    slack_interactions["requestBody"] = {
        "required": True,
        "content": {
            "application/x-www-form-urlencoded": {
                "schema": {
                    "type": "object",
                    "required": ["payload"],
                    "properties": {
                        "payload": {
                            "type": "string",
                            "description": (
                                "URL-encoded JSON interaction payload (Slack sends interactive "
                                "component data as a single form field)"
                            ),
                        }
                    },
                }
            }
        },
    }
    NOTES.append(
        "Slack enrichments: preserved header parameters, form request body, and HITL descriptions"
    )

    restore_component = spec["paths"]["/components/{component_id}/restore"]["post"]
    assert "403" not in restore_component["responses"]
    assert "409" not in restore_component["responses"]
    restore_component["responses"]["403"] = {
        "description": "The archived component is shared and cannot be modified by this caller"
    }
    restore_component["responses"]["409"] = {
        "description": "The component is not archived or the restore conflicts with another write"
    }

    refresh_content = spec["paths"]["/knowledge/content/{content_id}/refresh"]["post"]
    assert "403" not in refresh_content["responses"]
    assert "501" not in refresh_content["responses"]
    refresh_content["responses"]["403"] = {
        "description": "Shared content cannot be refreshed by this caller"
    }
    refresh_content["responses"]["501"] = {
        "description": "Refresh is not supported for remote knowledge"
    }

    queue_operations = [
        spec["paths"]["/queue/jobs"]["get"],
        spec["paths"]["/queue/jobs/{job_id}"]["get"],
        spec["paths"]["/queue/jobs/{job_id}/requeue"]["post"],
        spec["paths"]["/queue/stats"]["get"],
    ]
    for operation in queue_operations:
        assert "403" not in operation["responses"]
        operation["responses"]["403"] = {
            "description": "Job queue operations require an admin scope"
        }
    requeue_job = spec["paths"]["/queue/jobs/{job_id}/requeue"]["post"]
    assert "409" not in requeue_job["responses"]
    requeue_job["responses"]["409"] = {
        "description": (
            "The failed job may still be executing within the lock grace period; "
            "retry later or pass force=true"
        )
    }

    session_media = spec["paths"]["/sessions/{session_id}/media/{storage_key}"]["get"]
    assert "307" not in session_media["responses"]
    session_media["responses"]["307"] = {
        "description": "Redirect to a freshly signed HTTP or HTTPS media URL when redirect=true",
        "headers": {
            "Location": {
                "description": "Freshly signed media URL",
                "schema": {"type": "string", "format": "uri"},
            }
        },
    }

    pagination_page = spec["components"]["schemas"]["PaginationInfo"]["properties"]["page"]
    assert pagination_page["description"] == "Current page number (1-indexed)"
    assert pagination_page["default"] == 0
    assert pagination_page["minimum"] == 0
    pagination_page["description"] = "Current page number"
    NOTES.append(
        "runtime response enrichments: restore, knowledge refresh, Queue, and media branches; "
        "PaginationInfo wording aligned with its emitted default and minimum"
    )
    return spec


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


def validate_operation_ids(spec: dict) -> None:
    operation_ids = []
    missing = []
    for key, op in operations(spec).items():
        operation_id = op.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            missing.append(key)
        else:
            operation_ids.append(operation_id)
    duplicates = sorted(name for name, count in Counter(operation_ids).items() if count > 1)
    if missing or duplicates:
        raise RuntimeError(f"invalid operation IDs: missing={missing}, duplicates={duplicates}")


def _navigation_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _navigation_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _navigation_nodes(child)


def _page_routes(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _page_routes(child)
    elif isinstance(value, dict):
        yield from _page_routes(value.get("pages") or [])


def validate_endpoint_page_coverage(spec: dict) -> None:
    """Require one navigated endpoint stub for every generated operation."""
    declarations: dict[str, list[str]] = {}
    for page in sorted(SCHEMA_DIR.rglob("*.mdx")):
        matches = re.findall(
            r"(?m)^openapi:\s*([a-z]+)\s+([^\n]+?)\s*$",
            page.read_text(),
        )
        if len(matches) != 1:
            raise RuntimeError(f"expected one openapi frontmatter declaration in {page}")
        method, route = matches[0]
        key = f"{method.upper()} {route}"
        page_route = page.relative_to(REPO_ROOT).with_suffix("").as_posix()
        declarations.setdefault(key, []).append(page_route)

    expected = set(operations(spec))
    missing_pages = sorted(expected - set(declarations))
    duplicate_pages = {
        key: routes
        for key, routes in sorted(declarations.items())
        if key in expected and len(routes) != 1
    }

    navigation = json.loads(DOCS_JSON.read_text())
    api_groups = [
        node
        for node in _navigation_nodes(navigation)
        if node.get("openapi") == "reference-api/openapi.yaml"
    ]
    if len(api_groups) != 1:
        raise RuntimeError(f"expected one AgentOS OpenAPI navigation group, found {len(api_groups)}")
    nav_pages = list(_page_routes(api_groups[0].get("pages") or []))
    nav_counts = Counter(nav_pages)

    missing_nav = []
    duplicate_nav = []
    for key in sorted(expected & set(declarations)):
        for page_route in declarations[key]:
            if nav_counts[page_route] == 0:
                missing_nav.append((key, page_route))
            elif nav_counts[page_route] > 1:
                duplicate_nav.append((key, page_route, nav_counts[page_route]))

    stale_nav = []
    for page_route in sorted(
        route for route in nav_counts if route.startswith("reference-api/schema/")
    ):
        declared = [key for key, routes in declarations.items() if page_route in routes]
        if len(declared) != 1 or declared[0] not in expected:
            stale_nav.append((page_route, declared))

    if missing_pages or duplicate_pages or missing_nav or duplicate_nav or stale_nav:
        raise RuntimeError(
            "invalid endpoint-page coverage: "
            f"missing_pages={missing_pages}, duplicate_pages={duplicate_pages}, "
            f"missing_nav={missing_nav}, duplicate_nav={duplicate_nav}, stale_nav={stale_nav}"
        )

    stale_files = sorted(set(declarations) - expected)
    NOTES.append(
        f"endpoint-page coverage: {len(expected)} operations each have one navigated stub; "
        f"{len(stale_files)} non-navigated legacy stubs retained"
    )


def changed_fields(old: dict, new: dict) -> list[str]:
    return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))


def diff_specs(old: dict, new: dict) -> str:
    old_ops, new_ops = operations(old), operations(new)
    added = sorted(set(new_ops) - set(old_ops))
    removed = sorted(set(old_ops) - set(new_ops))
    common = sorted(set(old_ops) & set(new_ops))
    changed = []
    for key in common:
        old_op, new_op = old_ops[key], new_ops[key]
        if old_op != new_op:
            reasons = []
            fields = changed_fields(old_op, new_op)
            if fields:
                reasons.append("fields: " + ", ".join(fields))
            changed.append((key, "; ".join(reasons)))

    old_schema_map = (old.get("components") or {}).get("schemas") or {}
    new_schema_map = (new.get("components") or {}).get("schemas") or {}
    old_schemas = set(old_schema_map)
    new_schemas = set(new_schema_map)
    changed_schemas = sorted(
        name for name in old_schemas & new_schemas if old_schema_map[name] != new_schema_map[name]
    )

    lines = []
    lines.append("# OpenAPI diff: reference-api/openapi.yaml (old) vs generated spec (new)")
    lines.append("")
    lines.append(f"- Old: `{OLD_YAML}` (info.version `{old.get('info', {}).get('version')}`)")
    lines.append(f"- New: `{NEW_YAML}` (info.version `{new.get('info', {}).get('version')}`)")
    lines.append(f"- Operations: {len(old_ops)} old -> {len(new_ops)} new "
                 f"({len(added)} added, {len(removed)} removed, {len(changed)} changed)")
    lines.append(f"- Component schemas: {len(old_schemas)} old -> {len(new_schemas)} new "
                 f"({len(new_schemas - old_schemas)} added, {len(old_schemas - new_schemas)} removed, "
                 f"{len(changed_schemas)} changed)")
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

    lines.append(f"## Changed component schemas ({len(changed_schemas)})")
    lines.append("")
    for name in changed_schemas:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero when the tracked JSON or YAML differs from generated output",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    provenance = verify_source_provenance()
    NOTES.append(
        f"source: {provenance['source_tag']} at {provenance['source_sha']}; "
        f"imported module: {provenance['imported_module']}"
    )
    app = build_app()
    spec = apply_runtime_description_enrichments(app.openapi())
    validate_operation_ids(spec)
    validate_endpoint_page_coverage(spec)

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
    if args.check:
        checked_json = json.loads(OLD_JSON.read_text())
        checked_yaml = yaml.safe_load(OLD_YAML.read_text())
        if checked_json != checked_yaml:
            print("error: tracked OpenAPI JSON and YAML differ semantically", file=sys.stderr)
            return 1
        if checked_json != spec:
            print(f"error: tracked OpenAPI is stale; review {DIFF_MD}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
