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
AGNO_SOURCE_ROOT = Path(os.environ.get("AGNO_REPO") or REPO_ROOT / "agno").resolve()
AGNO_IMPORT_ROOT = (AGNO_SOURCE_ROOT / "libs" / "agno").resolve()


def _source_git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(AGNO_SOURCE_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def verify_source_checkout_before_import() -> dict[str, str]:
    """Verify the reviewed checkout before any Agno module can be imported."""
    package = AGNO_IMPORT_ROOT / "agno" / "__init__.py"
    if not package.is_file():
        raise RuntimeError(f"Agno import package not found below {AGNO_IMPORT_ROOT}")

    pyproject = AGNO_SOURCE_ROOT / "libs" / "agno" / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError(f"Agno source pyproject not found at {pyproject}")
    project_match = re.search(
        r"(?ms)^\[project\]\s*$.*?^version\s*=\s*[\"']([^\"']+)[\"']\s*$",
        pyproject.read_text(encoding="utf-8"),
    )
    if project_match is None:
        raise RuntimeError(f"Agno source version not found in {pyproject}")
    source_version = project_match.group(1)

    expected_sha = os.environ.get("AGNO_EXPECTED_SHA")
    if not expected_sha:
        raise RuntimeError("AGNO_EXPECTED_SHA is required")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise RuntimeError("AGNO_EXPECTED_SHA must be a full lowercase commit SHA")

    git_root = Path(_source_git("rev-parse", "--show-toplevel")).resolve()
    if git_root != AGNO_SOURCE_ROOT:
        raise RuntimeError(
            f"Agno source root {AGNO_SOURCE_ROOT} is inside a different checkout {git_root}"
        )
    source_sha = _source_git("rev-parse", "--verify", "HEAD^{commit}")
    if source_sha != expected_sha:
        raise RuntimeError(
            f"Agno source SHA {source_sha} does not match AGNO_EXPECTED_SHA {expected_sha}"
        )
    source_tag = _source_git("describe", "--tags", "--exact-match", "HEAD")
    expected_tag = f"v{source_version}"
    if source_tag != expected_tag:
        raise RuntimeError(
            f"Agno source tag {source_tag!r} does not match source version {expected_tag!r}"
        )
    dirty = _source_git("status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        summary = dirty.splitlines()[:10]
        raise RuntimeError(
            "Agno source checkout is dirty; generation requires reviewed committed bytes: "
            + repr(summary)
        )

    return {
        "import_root": str(AGNO_IMPORT_ROOT),
        "source_root": str(AGNO_SOURCE_ROOT),
        "source_sha": source_sha,
        "source_tag": source_tag,
        "source_version": source_version,
    }


PREIMPORT_SOURCE_PROVENANCE = verify_source_checkout_before_import()
sys.path.insert(0, str(AGNO_IMPORT_ROOT))

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
from agno.os.scopes import get_default_scope_mappings, get_required_scopes_for_route  # noqa: E402
from agno.registry import Registry  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.workflow import Workflow  # noqa: E402
from agno.workflow.step import Step  # noqa: E402

NOTES = []  # inclusion/exclusion notes surfaced at the end of the run

CORE_PARENT_AUTH_OPERATIONS: set[tuple[str, str]] = set()
CORE_PUBLIC_OPERATIONS = {("/health", "get"), ("/info", "get")}
OPTIONAL_PARENT_AUTH_FAMILIES = {
    "AGUI": {("/agui", "post"), ("/status", "get")},
    "A2A": {
        ("/a2a/agents/{id}/.well-known/agent-card.json", "get"),
        ("/a2a/agents/{id}/v1/message:send", "post"),
        ("/a2a/agents/{id}/v1/tasks:get", "post"),
        ("/a2a/agents/{id}/v1/tasks:cancel", "post"),
        ("/a2a/agents/{id}/v1/message:stream", "post"),
        ("/a2a/teams/{id}/.well-known/agent-card.json", "get"),
        ("/a2a/teams/{id}/v1/message:send", "post"),
        ("/a2a/teams/{id}/v1/tasks:get", "post"),
        ("/a2a/teams/{id}/v1/tasks:cancel", "post"),
        ("/a2a/teams/{id}/v1/message:stream", "post"),
        ("/a2a/workflows/{id}/.well-known/agent-card.json", "get"),
        ("/a2a/workflows/{id}/v1/message:send", "post"),
        ("/a2a/workflows/{id}/v1/message:stream", "post"),
    },
}
OPTIONAL_PUBLIC_FAMILIES = {
    "Slack": {("/slack/events", "post"), ("/slack/interactions", "post")},
    "Whatsapp": {
        ("/whatsapp/status", "get"),
        ("/whatsapp/webhook", "get"),
        ("/whatsapp/webhook", "post"),
    },
    "Telegram": {
        ("/telegram/status", "get"),
        ("/telegram/webhook", "post"),
    },
}
OPTIONAL_INTERFACE_OPERATIONS = set().union(
    *OPTIONAL_PARENT_AUTH_FAMILIES.values(),
    *OPTIONAL_PUBLIC_FAMILIES.values(),
)


def present_optional_families(
    operation_keys: set[tuple[str, str]],
    families: dict[str, set[tuple[str, str]]],
) -> tuple[set[tuple[str, str]], set[str]]:
    """Return complete optional route families and reject partial mounts."""
    present_routes: set[tuple[str, str]] = set()
    present_names: set[str] = set()
    for name, family in families.items():
        present = operation_keys & family
        if present and present != family:
            raise RuntimeError(
                f"optional interface {name} is partially mounted: "
                f"missing={sorted(family - present)}"
            )
        if present:
            present_routes.update(family)
            present_names.add(name)
    return present_routes, present_names


def verify_source_provenance() -> dict[str, str]:
    provenance = verify_source_checkout_before_import()
    if provenance != PREIMPORT_SOURCE_PROVENANCE:
        raise RuntimeError("Agno source provenance changed after the pre-import check")
    source_version = provenance["source_version"]
    if source_version != agno_version:
        raise RuntimeError(
            f"Agno source version {source_version} does not match imported package version {agno_version}"
        )

    imported_modules = {}
    outside_modules = {}
    for name, module in sorted(sys.modules.items()):
        if name != "agno" and not name.startswith("agno."):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            continue
        resolved = Path(module_file).resolve()
        imported_modules[name] = str(resolved)
        if not resolved.is_relative_to(AGNO_IMPORT_ROOT):
            outside_modules[name] = str(resolved)
    if outside_modules:
        raise RuntimeError(
            "Agno modules resolved outside the reviewed source tree: "
            + json.dumps(outside_modules, sort_keys=True)
        )

    return {**provenance, "imported_module": imported_modules["agno"]}

# Interface imports are optional: each pulls in an extra (a2a-sdk, ag-ui-protocol,
# slack-sdk, ...) that may be absent from the venv. Missing ones are excluded
# from the generated spec and reported, instead of failing the whole run.
try:
    from a2a.types import AgentCard as A2AAgentCard  # noqa: E402
    from agno.os.interfaces.a2a import A2A  # noqa: E402
except ImportError as _e:
    A2A = None
    A2AAgentCard = None
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
        mcp=True,  # mounts /mcp sub-app; sub-app routes don't appear in app.openapi()
        telemetry=False,  # telemetry POSTs home at init; this is an offline dry run
    )
    return agent_os.get_app(), interfaces


def apply_runtime_description_enrichments(spec: dict, interfaces: list) -> dict:
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

    checkpoint_snapshot = spec["paths"][
        "/agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}"
    ]["get"]
    assert checkpoint_snapshot["operationId"] == "get_agent_run_checkpoint_snapshot"
    snapshot_success = checkpoint_snapshot["responses"]["200"]
    assert snapshot_success["content"]["application/json"]["schema"] == {}
    checkpoint_entry_schema = checkpoint_success["content"]["application/json"]["schema"][
        "properties"
    ]["checkpoints"]["items"]
    snapshot_checkpoint_schema = json.loads(json.dumps(checkpoint_entry_schema))
    snapshot_checkpoint_schema["properties"]["checkpoint_id"]["type"] = ["string", "null"]
    snapshot_checkpoint_schema["properties"]["reason"]["enum"] = ["snapshot"]
    snapshot_success["content"]["application/json"]["schema"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["checkpoint", "snapshot"],
        "properties": {
            "checkpoint": snapshot_checkpoint_schema,
            "snapshot": {
                "type": "object",
                "additionalProperties": True,
                "description": "Serialized AgentRunOutput truncated at the selected message boundary",
            },
        },
    }
    snapshot_bad_request = checkpoint_snapshot["responses"]["400"]
    assert snapshot_bad_request["description"] == "Invalid checkpoint message index"
    snapshot_bad_request["description"] = (
        "The message index is invalid or checkpoint snapshots are unavailable for remote agents"
    )
    assert "403" not in checkpoint_snapshot["responses"]
    checkpoint_snapshot["responses"]["403"] = {
        "description": "The caller cannot run this agent"
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

    list_workflow_runs = spec["paths"]["/workflows/{workflow_id}/runs"]["get"]
    assert list_workflow_runs["operationId"] == "list_workflow_runs"
    list_workflow_runs_success = list_workflow_runs["responses"]["200"]
    assert list_workflow_runs_success["description"] == "List of runs retrieved successfully"
    assert list_workflow_runs_success["content"]["application/json"]["schema"] == {}
    list_workflow_runs_success["content"]["application/json"]["schema"] = {
        "type": "array",
        "items": {"$ref": "#/components/schemas/WorkflowRunSchema"},
    }
    workflow_status_parameter = next(
        parameter for parameter in list_workflow_runs["parameters"] if parameter["name"] == "status"
    )
    old_workflow_status_description = (
        "Filter by run status (PENDING, RUNNING, COMPLETED, ERROR, PAUSED)"
    )
    assert workflow_status_parameter["description"] == old_workflow_status_description
    assert workflow_status_parameter["schema"]["description"] == old_workflow_status_description
    workflow_string_status_schema = next(
        branch
        for branch in workflow_status_parameter["schema"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert workflow_string_status_schema == {"type": "string"}
    workflow_string_status_schema["enum"] = status_values
    workflow_status_description = f"Filter by run status ({', '.join(status_values)})"
    workflow_status_parameter["description"] = workflow_status_description
    workflow_status_parameter["schema"]["description"] = workflow_status_description
    assert "403" not in list_workflow_runs["responses"]
    list_workflow_runs["responses"]["403"] = {"description": "Access denied to run this workflow"}
    NOTES.append(
        "runtime Workflow run-list schema: WorkflowRunSchema array, complete RunStatus filter, and authorization response"
    )

    list_workflows = spec["paths"]["/workflows"]["get"]
    assert list_workflows["operationId"] == "get_workflows"
    assert list_workflows["description"] == (
        "Retrieve a comprehensive list of all workflows configured in this OS instance.\n\n"
        "**Return Information:**\n"
        "- Workflow metadata (ID, name, description)\n"
        "- Input schema requirements\n"
        "- Step sequence and execution flow\n"
        "- Associated agents and teams"
    )
    list_workflows["description"] = (
        "Retrieve summary records for the workflows configured in this AgentOS instance. "
        "Each item includes identifiers, metadata, database association, factory or component "
        "flags, and published stage or version fields when applicable. Use "
        "`GET /workflows/{workflow_id}` for input schemas, steps, agents, and teams."
    )
    assert "403" not in list_workflows["responses"]
    list_workflows["responses"]["403"] = {
        "description": "The caller has no accessible workflow scopes"
    }

    get_workflow_run = spec["paths"]["/workflows/{workflow_id}/runs/{run_id}"]["get"]
    assert get_workflow_run["operationId"] == "get_workflow_run"
    get_workflow_run_success = get_workflow_run["responses"]["200"]
    assert get_workflow_run_success["description"] == "Run output retrieved successfully"
    assert get_workflow_run_success["content"]["application/json"]["schema"] == {}
    get_workflow_run_success["content"]["application/json"]["schema"] = {
        "anyOf": [
            {"$ref": "#/components/schemas/WorkflowRunSchema"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "session_id", "status"],
                "properties": {
                    "run_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": status_values,
                    },
                    "content": {"type": ["string", "null"]},
                },
            },
        ]
    }
    NOTES.append(
        "runtime Workflow run polling schema: persisted WorkflowRunSchema or durable queue ticket"
    )

    create_workflow_run = spec["paths"]["/workflows/{workflow_id}/runs"]["post"]
    assert create_workflow_run["operationId"] == "create_workflow_run"
    create_workflow_success = create_workflow_run["responses"]["200"]
    assert create_workflow_success["description"] == "Workflow executed successfully"
    assert create_workflow_success["content"]["application/json"]["schema"] == {}
    create_workflow_success["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/WorkflowRunSchema"
    }
    workflow_stream = create_workflow_success["content"]["text/event-stream"]
    assert workflow_stream["example"] == (
        'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n'
    )
    workflow_stream["example"] = (
        'event: WorkflowStarted\ndata: {"event": "WorkflowStarted", '
        '"workflow_id": "workflow-123", "session_id": "session-123", '
        '"run_id": "run-123", "nested_depth": 0, "created_at": 1770000000}\n\n'
    )
    assert "202" not in create_workflow_run["responses"]
    create_workflow_run["responses"]["202"] = {
        "description": "Workflow accepted for background execution",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["run_id", "session_id", "status"],
                    "properties": {
                        "run_id": {"type": "string"},
                        "session_id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": status_values,
                        },
                    },
                }
            }
        },
    }
    for status, description in {
        "409": "The idempotency key conflicts with an incompatible or unrecoverable run",
        "429": "The durable workflow queue is full",
    }.items():
        assert status not in create_workflow_run["responses"]
        create_workflow_run["responses"][status] = {"description": description}
    NOTES.append(
        "runtime Workflow execution responses: typed output, background ticket, and WorkflowStarted SSE event"
    )

    get_team_run = spec["paths"]["/teams/{team_id}/runs/{run_id}"]["get"]
    assert get_team_run["operationId"] == "get_team_run"
    get_team_run_success = get_team_run["responses"]["200"]
    assert get_team_run_success["description"] == "Run output retrieved successfully"
    assert get_team_run_success["content"]["application/json"]["schema"] == {}
    get_team_run_success["content"]["application/json"]["schema"] = {
        "anyOf": [
            {"$ref": "#/components/schemas/TeamRunSchema"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id", "session_id", "status"],
                "properties": {
                    "run_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": status_values,
                    },
                    "content": {"type": ["string", "null"]},
                },
            },
        ]
    }
    assert "403" not in get_team_run["responses"]
    get_team_run["responses"]["403"] = {
        "description": (
            "Insufficient permissions. Requires teams:read and run access to the requested team"
        )
    }
    NOTES.append(
        "runtime Team run polling: typed persisted output or queue ticket and resource-access requirement"
    )

    get_teams = spec["paths"]["/teams"]["get"]
    assert get_teams["operationId"] == "get_teams"
    assert get_teams["summary"] == "List All Teams"
    assert get_teams["description"].startswith(
        "Retrieve a comprehensive list of all teams configured in this OS instance."
    )
    get_teams["summary"] = "List Accessible Teams"
    get_teams["description"] = (
        "Retrieve the teams visible to the authenticated principal. Administrators can access "
        "the complete roster. Scoped callers receive only teams allowed by their permissions."
    )
    assert "403" not in get_teams["responses"]
    get_teams["responses"]["403"] = {"description": "Insufficient permission to list teams"}
    NOTES.append("runtime Team roster visibility: scoped results and authorization response")

    delete_all_content = spec["paths"]["/knowledge/content"]["delete"]
    assert delete_all_content["operationId"] == "delete_all_content"
    assert delete_all_content["description"] == (
        "Permanently remove all content from the knowledge base. This is a destructive "
        "operation that cannot be undone. Use with extreme caution."
    )
    delete_all_content["description"] = (
        "Permanently remove content from the knowledge base. With user isolation enabled, "
        "a non-admin caller removes only its own content; shared and other users' content "
        "remain. Admins and unscoped callers remove all content. This action cannot be undone."
    )
    delete_all_success = delete_all_content["responses"]["200"]
    assert delete_all_success["content"]["application/json"]["schema"] == {}
    delete_all_success["content"]["application/json"]["schema"] = {
        "type": ["string", "null"],
        "enum": ["success", None],
    }

    delete_content = spec["paths"]["/knowledge/content/{content_id}"]["delete"]
    assert delete_content["operationId"] == "delete_content_by_id"
    assert delete_content["description"] == (
        "Permanently remove a specific content item from the knowledge base. "
        "This action cannot be undone."
    )
    delete_content["description"] = (
        "Permanently remove a specific content item from the knowledge base. With user "
        "isolation enabled, a non-admin caller can delete its own content but cannot delete "
        "shared content. Content outside the caller's scope is reported as not found. "
        "This action cannot be undone."
    )
    assert "403" not in delete_content["responses"]
    delete_content["responses"]["403"] = {
        "description": "Shared content cannot be deleted by a scoped caller"
    }
    NOTES.append(
        "runtime knowledge deletion: owner scoping, shared-content denial, and string/null delete-all result"
    )

    delete_memories = spec["paths"]["/memories"]["delete"]
    assert delete_memories["operationId"] == "delete_memories"
    assert delete_memories["responses"]["400"]["description"] == (
        "Invalid request - empty memory_ids list"
    )
    del delete_memories["responses"]["400"]
    NOTES.append("runtime memory validation: empty memory_ids is a request-model 422 response")

    trigger_schedule = spec["paths"]["/schedules/{schedule_id}/trigger"]["post"]
    assert trigger_schedule["operationId"] == "trigger_schedule_schedules__schedule_id__trigger_post"
    assert set(trigger_schedule["responses"]) == {"200", "422"}
    trigger_schedule["responses"].update(
        {
            "404": {"description": "Schedule not found"},
            "409": {"description": "Schedule is disabled"},
            "503": {"description": "Scheduler is not running"},
        }
    )
    NOTES.append("runtime schedule trigger: explicit not-found, disabled, and unavailable responses")

    component_config = spec["paths"]["/components/{component_id}/configs/{version}"]["get"]
    assert component_config["operationId"] == "get_config"
    component_config["operationId"] = "get_component_config"
    NOTES.append(
        "operationId enrichment: GET /components/{component_id}/configs/{version} "
        "uses get_component_config to avoid the pinned v3.0.4 get_config collision"
    )

    slack_route_keys = OPTIONAL_PUBLIC_FAMILIES["Slack"]
    available_operation_keys = {
        (path, method)
        for path, path_item in spec["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete", "options", "head"}
    }
    a2a_route_keys = OPTIONAL_PARENT_AUTH_FAMILIES["A2A"]
    present_a2a_routes, _ = present_optional_families(
        available_operation_keys,
        {"A2A": a2a_route_keys},
    )
    if present_a2a_routes:
        assert A2AAgentCard is not None
        agent_card_schema = A2AAgentCard.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        assert agent_card_schema["title"] == "AgentCard"
        assert agent_card_schema["type"] == "object"
        agent_card_definitions = agent_card_schema.pop("$defs")
        new_agent_card_schemas = {
            **agent_card_definitions,
            "AgentCard": agent_card_schema,
        }
        component_schemas = spec["components"]["schemas"]
        collisions = set(new_agent_card_schemas) & set(component_schemas)
        assert not collisions, f"A2A schema name collisions: {sorted(collisions)}"
        component_schemas.update(new_agent_card_schemas)

        card_operations = {
            "Agent": (
                "/a2a/agents/{id}/.well-known/agent-card.json",
                "get_agent_card_a2a_agents__id___well_known_agent_card_json_get",
            ),
            "Team": (
                "/a2a/teams/{id}/.well-known/agent-card.json",
                "get_team_card_a2a_teams__id___well_known_agent_card_json_get",
            ),
            "Workflow": (
                "/a2a/workflows/{id}/.well-known/agent-card.json",
                "get_workflow_card_a2a_workflows__id___well_known_agent_card_json_get",
            ),
        }
        for kind, (path, operation_id) in card_operations.items():
            operation = spec["paths"][path]["get"]
            assert operation["operationId"] == operation_id
            success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            assert success_schema == {}
            assert "404" not in operation["responses"]
            operation["responses"]["200"]["content"]["application/json"]["schema"] = {
                "$ref": "#/components/schemas/AgentCard"
            }
            operation["responses"]["404"] = {"description": f"{kind} not found"}

        get_agent_task = spec["paths"]["/a2a/agents/{id}/v1/tasks:get"]["post"]
        assert get_agent_task["operationId"] == "get_agent_task"
        assert "requestBody" not in get_agent_task
        get_agent_task_success = get_agent_task["responses"]["200"]
        assert get_agent_task_success["content"]["application/json"]["schema"] == {}
        for status in ("400", "404", "501"):
            assert status not in get_agent_task["responses"]
        get_agent_task["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": True,
                        "required": ["params"],
                        "properties": {
                            "id": {"type": ["string", "integer", "null"]},
                            "params": {
                                "type": "object",
                                "additionalProperties": True,
                                "required": ["id", "contextId"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "contextId": {"type": "string"},
                                },
                            },
                        },
                    },
                    "example": {
                        "id": "request-1",
                        "params": {"id": "task-1", "contextId": "context-1"},
                    },
                }
            },
        }
        get_agent_task_success["content"]["application/json"]["schema"] = {
            "$ref": "#/components/schemas/SendMessageSuccessResponse"
        }
        get_agent_task["responses"]["400"] = {
            "description": "Missing task ID, unsupported RemoteAgent, or missing context ID"
        }
        get_agent_task["responses"]["404"] = {
            "description": "Agent or task not found"
        }
        get_agent_task["responses"]["501"] = {
            "description": "Task retrieval is not supported for this agent type"
        }
        NOTES.append(
            "A2A agent task retrieval: JSON-RPC request, typed success response, and runtime errors"
        )

        stream_operations = [
            spec["paths"]["/a2a/agents/{id}/v1/message:stream"]["post"],
            spec["paths"]["/a2a/teams/{id}/v1/message:stream"]["post"],
            spec["paths"]["/a2a/workflows/{id}/v1/message:stream"]["post"],
        ]
        for operation in stream_operations:
            description = operation["description"]
            assert description.endswith(
                "Returns real-time updates as newline-delimited JSON (NDJSON)."
            )
            operation["description"] = description.replace(
                "Returns real-time updates as newline-delimited JSON (NDJSON).",
                "Returns real-time updates as server-sent events (SSE).",
            )
            success_content = operation["responses"]["200"]["content"]
            assert success_content["application/json"] == {"schema": {}}
            assert "text/event-stream" in success_content
            success_content.pop("application/json")
        NOTES.append("A2A streaming responses: publish SSE descriptions and media types")

    present_slack_routes, _ = present_optional_families(
        available_operation_keys,
        {"Slack": slack_route_keys},
    )
    if present_slack_routes:
        slack_events = spec["paths"]["/slack/events"]["post"]
        slack_interactions = spec["paths"]["/slack/interactions"]["post"]
    else:
        # Run the deterministic assertions against local placeholders when the
        # optional Slack interface is unavailable. The spec remains unchanged.
        slack_events = {"description": "Process incoming Slack events"}
        slack_interactions = {
            "description": "Handle Slack interactive components (HITL buttons / form submit)"
        }
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
    assert "requestBody" not in slack_events
    slack_events["requestBody"] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["type"],
                    "properties": {"type": {"type": "string"}},
                },
                "examples": {
                    "url_verification": {
                        "summary": "URL verification challenge",
                        "value": {
                            "type": "url_verification",
                            "challenge": "challenge-token",
                            "token": "verification-token",
                        },
                    },
                    "event_callback": {
                        "summary": "App mention event",
                        "value": {
                            "type": "event_callback",
                            "team_id": "T01234567",
                            "event": {
                                "type": "app_mention",
                                "user": "U01234567",
                                "text": "<@U76543210> summarize this thread",
                                "ts": "1712345678.123456",
                                "channel": "C01234567",
                            },
                        },
                    },
                },
            }
        },
    }
    NOTES.append("Slack events: required JSON request body with verification and event examples")

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
    if present_slack_routes:
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

    update_component = spec["paths"]["/components/{component_id}"]["patch"]
    assert "403" not in update_component["responses"]
    assert "409" not in update_component["responses"]
    update_component["responses"]["403"] = {
        "description": "The shared component or another user's published component cannot be modified"
    }
    update_component["responses"]["409"] = {
        "description": "The version guard is stale or the component update conflicts with another write"
    }

    approval_count = spec["paths"]["/approvals/count"]["get"]
    for status in ("401", "403", "503"):
        assert status not in approval_count["responses"]
    approval_count["responses"]["401"] = {
        "description": "Authentication is required by the configured AgentOS security policy"
    }
    approval_count["responses"]["403"] = {
        "description": "The caller lacks the approvals:read scope or a required isolated user ID"
    }
    approval_count["responses"]["503"] = {
        "description": "The configured database does not support approval operations"
    }

    delete_approval = spec["paths"]["/approvals/{approval_id}"]["delete"]
    assert (
        delete_approval["operationId"]
        == "delete_approval_approvals__approval_id__delete"
    )
    assert delete_approval.get("description") is None
    delete_approval["description"] = (
        "Delete an approval audit record. Scoped non-admin callers receive 404 so approval "
        "existence is not disclosed."
    )
    for status in ("401", "403", "404", "500", "503"):
        assert status not in delete_approval["responses"]
    delete_approval["responses"]["401"] = {
        "description": "Authentication is required by the configured AgentOS security policy"
    }
    delete_approval["responses"]["403"] = {
        "description": "The caller lacks the approvals:delete scope or a required isolated user ID"
    }
    delete_approval["responses"]["404"] = {
        "description": (
            "Approval deletion is unavailable to a scoped non-admin caller"
        )
    }
    delete_approval["responses"]["500"] = {
        "description": "The configured database reported that the approval was not deleted"
    }
    delete_approval["responses"]["503"] = {
        "description": "The configured database does not support approval operations"
    }

    list_service_accounts = spec["paths"]["/service-accounts"]["get"]
    assert list_service_accounts["operationId"] == "list_service_accounts_service_accounts_get"
    assert "503" not in list_service_accounts["responses"]
    list_service_accounts["responses"]["503"] = {
        "description": "The configured database does not support service account operations"
    }

    list_learnings = spec["paths"]["/learnings"]["get"]
    assert list_learnings["operationId"] == "list_learnings"
    for status in ("403", "501"):
        assert status not in list_learnings["responses"]
    list_learnings["responses"]["403"] = {
        "description": "A scoped caller cannot list learnings for another user"
    }
    list_learnings["responses"]["501"] = {
        "description": "Learnings are not supported by the selected remote or configured database"
    }

    learning_users = spec["paths"]["/learnings/users"]["get"]
    assert learning_users["operationId"] == "list_learning_users"
    assert "501" not in learning_users["responses"]
    learning_users["responses"]["501"] = {
        "description": (
            "Learning-user statistics are not supported by the selected remote "
            "or configured database"
        )
    }

    delete_learning_user = spec["paths"]["/learnings/users/{user_id}"]["delete"]
    assert delete_learning_user["operationId"] == "delete_learning_user"
    assert "501" not in delete_learning_user["responses"]
    delete_learning_user["responses"]["501"] = {
        "description": "Learning deletion is not supported by the selected remote or configured database"
    }

    delete_learning = spec["paths"]["/learnings/{learning_id}"]["delete"]
    assert delete_learning["operationId"] == "delete_learning"
    assert "501" not in delete_learning["responses"]
    delete_learning["responses"]["501"] = {
        "description": "Learning deletion is not supported by the selected remote or configured database"
    }
    NOTES.append("learning deletion: document unsupported remote and database responses")

    user_memory_stats = spec["paths"]["/user_memory_stats"]["get"]
    assert user_memory_stats["operationId"] == "get_user_memory_stats"
    user_memory_stats_media = user_memory_stats["responses"]["200"]["content"]["application/json"]
    assert user_memory_stats_media["schema"] == {
        "$ref": "#/components/schemas/PaginatedResponse_UserStatsSchema_"
    }
    assert set(user_memory_stats_media["example"]) == {"data"}
    user_memory_stats_media["example"]["meta"] = {
        "page": 1,
        "limit": 20,
        "total_pages": 1,
        "total_count": 1,
        "search_time_ms": 0,
    }

    content_status = spec["paths"]["/knowledge/content/{content_id}/status"]["get"]
    assert content_status["operationId"] == "get_content_status"
    content_status_not_found = content_status["responses"]["404"]
    assert content_status_not_found["description"] == "Content not found"
    content_status_not_found["description"] = (
        "The selected knowledge base or database was not found"
    )

    agui_status = spec["paths"]["/status"]["get"]
    assert agui_status["operationId"] == "get_status_status_get"
    agui_status_success = agui_status["responses"]["200"]
    assert agui_status_success["content"]["application/json"]["schema"] == {}
    agui_status_success["content"]["application/json"]["schema"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {
            "status": {"type": "string", "enum": ["available"]},
        },
    }

    delete_memory = spec["paths"]["/memories/{memory_id}"]["delete"]
    assert delete_memory["operationId"] == "delete_memory"
    assert delete_memory["description"] == (
        "Permanently delete a specific user memory. This action cannot be undone."
    )
    delete_memory["description"] = (
        "Delete a specific user memory. A valid local database request returns 204 even when "
        "no memory matches the ID."
    )
    memory_not_found = delete_memory["responses"]["404"]
    assert memory_not_found["description"] == "Memory not found"
    memory_not_found["description"] = "The selected database or table was not found"

    NOTES.append(
        "runtime sampled contracts: service account and learning capability errors, AG-UI status "
        "schema, approval deletion outcomes, and idempotent local memory deletion"
    )

    enable_schedule = spec["paths"]["/schedules/{schedule_id}/enable"]["post"]
    assert enable_schedule.get("description") is None
    enable_schedule["description"] = (
        "Enable a schedule after verifying access to its target and confirming that the target "
        "is published, active, and still matches the schedule endpoint."
    )
    for status in ("401", "403", "404", "409", "503"):
        assert status not in enable_schedule["responses"]
    enable_schedule["responses"]["401"] = {
        "description": "Authentication is required by the configured AgentOS security policy"
    }
    enable_schedule["responses"]["403"] = {
        "description": "The caller cannot run the target or schedule the target endpoint"
    }
    enable_schedule["responses"]["404"] = {"description": "Schedule not found"}
    enable_schedule["responses"]["409"] = {
        "description": (
            "The target is archived or unpublished, or the schedule endpoint no longer matches "
            "its target"
        )
    }
    enable_schedule["responses"]["503"] = {
        "description": (
            "The configured database does not support scheduler operations or scheduler "
            "dependencies are not installed"
        )
    }

    update_session = spec["paths"]["/sessions/{session_id}"]["patch"]
    assert update_session["operationId"] == "update_session"
    update_request_media = update_session["requestBody"]["content"]["application/json"]
    assert "examples" not in update_request_media
    update_success_media = update_session["responses"]["200"]["content"]["application/json"]
    request_examples = update_success_media.pop("examples")
    assert set(request_examples) == {
        "update_summary",
        "update_metadata",
        "update_session_name",
        "update_session_state",
    }
    update_request_media["examples"] = request_examples
    update_success_media["examples"] = {
        "updated_agent_session": {
            "summary": "Updated agent session",
            "value": {
                "agent_session_id": "session-123",
                "session_id": "session-123",
                "session_name": "Updated Session Name",
                "session_summary": {
                    "summary": "The user discussed project planning with the agent.",
                    "updated_at": "2025-10-21T14:30:00Z",
                },
            },
        }
    }

    upload_content = spec["paths"]["/knowledge/content"]["post"]
    upload_bad_request = upload_content["responses"]["400"]
    assert upload_bad_request["description"] == (
        "Invalid request - malformed metadata or missing content"
    )
    upload_bad_request["description"] = (
        "Knowledge base selection is ambiguous; provide knowledge_id or a db_id that "
        "resolves to one knowledge base"
    )
    NOTES.append("knowledge upload: document the runtime knowledge-selector 400 response")

    refresh_content = spec["paths"]["/knowledge/content/{content_id}/refresh"]["post"]
    assert refresh_content["operationId"] == "refresh_content"
    assert refresh_content["description"] == (
        "Re-ingest a URL-sourced content row from its source. For a site row this refreshes "
        "changed pages, retries failed ones, and removes pages that left the site."
    )
    refresh_content["description"] = (
        "Re-ingest a URL- or path-sourced content row from its source. For a site row this "
        "refreshes changed pages, retries failed ones, and removes pages that left the site."
    )
    refresh_bad_request = refresh_content["responses"]["400"]
    assert refresh_bad_request["description"] == "Content has no source URL"
    assert refresh_bad_request["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BadRequestResponse"
    }
    refresh_bad_request["description"] = (
        "Content has no recorded URL or path, its row ID cannot be matched to that source, "
        "or no URL reader can be determined"
    )
    assert "403" not in refresh_content["responses"]
    assert "501" not in refresh_content["responses"]
    refresh_content["responses"]["403"] = {
        "description": "Shared content cannot be refreshed by this caller"
    }
    refresh_content["responses"]["501"] = {
        "description": "Refresh is not supported for remote knowledge"
    }

    list_content_sources = spec["paths"]["/knowledge/{knowledge_id}/sources"]["get"]
    assert list_content_sources["operationId"] == "list_content_sources"
    assert "501" not in list_content_sources["responses"]
    list_content_sources["responses"]["501"] = {
        "description": "Source listing is not supported for remote knowledge"
    }
    NOTES.append(
        "knowledge refresh and source listing: path-source validation and remote unsupported responses"
    )

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

    traces = spec["paths"]["/traces"]["get"]
    traces_pagination = "- Use `page` (1-indexed) and `limit` parameters"
    assert traces_pagination in traces["description"]
    traces["description"] = traces["description"].replace(
        traces_pagination,
        "- Use `page` and `limit` parameters",
    )
    trace_page = next(
        parameter for parameter in traces["parameters"] if parameter["name"] == "page"
    )
    assert trace_page["description"] == "Page number (1-indexed)"
    assert trace_page["schema"]["description"] == "Page number (1-indexed)"
    assert trace_page["schema"]["minimum"] == 0
    trace_page["description"] = "Page number"
    trace_page["schema"]["description"] = "Page number"
    NOTES.append("traces pagination: remove the one-indexed claim while page zero remains valid")

    runtime_scope_mappings = get_default_scope_mappings()
    for interface in interfaces:
        if getattr(interface, "authenticates_own_requests", False):
            continue
        runtime_scope_mappings.update(interface.get_scope_mappings())
    scoped_operation_keys: set[tuple[str, str]] = set()
    added_scope_responses = 0
    preserved_scope_responses = 0
    operation_methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in operation_methods:
                continue
            required_scopes = get_required_scopes_for_route(
                runtime_scope_mappings,
                method.upper(),
                path,
            )
            if not required_scopes:
                continue

            key = (path, method)
            scoped_operation_keys.add(key)
            responses = operation.get("responses")
            assert isinstance(responses, dict)
            if "403" in responses:
                forbidden = responses["403"]
                assert isinstance(forbidden.get("description"), str)
                assert forbidden["description"].strip()
                preserved_scope_responses += 1
                continue

            responses["403"] = {
                "description": (
                    "Insufficient permissions. Required scope(s): "
                    + ", ".join(required_scopes)
                )
            }
            added_scope_responses += 1

    documented_scope_keys = {
        key
        for key in scoped_operation_keys
        if "403" in spec["paths"][key[0]][key[1]]["responses"]
    }
    assert documented_scope_keys == scoped_operation_keys
    assert added_scope_responses + preserved_scope_responses == len(scoped_operation_keys)
    NOTES.append(
        f"scope responses: {len(scoped_operation_keys)} runtime-mapped operations document 403; "
        f"added {added_scope_responses} and preserved {preserved_scope_responses}"
    )

    # The generated reference covers both open AgentOS instances and protected
    # deployments. FastAPI emits an unconditional bearer requirement for its
    # optional HTTPBearer dependency, so add the empty alternative required by
    # OpenAPI for anonymous access. Service-account creation explicitly rejects
    # anonymous callers and remains bearer-only. Parent AuthMiddleware protects
    # AG-UI, status, and A2A routes without adding operation-level metadata, so
    # enrich those interface operations explicitly.
    bearer_shape = [{"HTTPBearer": []}]
    required_bearer = {("/service-accounts", "post")}
    operation_keys = {
        (path, method)
        for path, path_item in spec["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete", "options", "head"}
    }
    optional_parent_routes, present_parent_families = present_optional_families(
        operation_keys, OPTIONAL_PARENT_AUTH_FAMILIES
    )
    optional_public_routes, present_public_families = present_optional_families(
        operation_keys, OPTIONAL_PUBLIC_FAMILIES
    )
    expected_parent_optional_bearer = CORE_PARENT_AUTH_OPERATIONS | optional_parent_routes
    expected_public_no_security = CORE_PUBLIC_OPERATIONS | optional_public_routes
    if not expected_parent_optional_bearer <= operation_keys:
        raise RuntimeError("core parent-auth operations are missing")
    if not expected_public_no_security <= operation_keys:
        raise RuntimeError("core public operations are missing")
    raw_bearer: set[tuple[str, str]] = set()
    found_required_bearer: set[tuple[str, str]] = set()
    found_parent_optional_bearer: set[tuple[str, str]] = set()
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            key = (path, method)
            if key in expected_parent_optional_bearer:
                assert "security" not in operation
                operation["security"] = [{}, {"HTTPBearer": []}]
                found_parent_optional_bearer.add(key)
                continue
            if operation.get("security") != bearer_shape:
                continue
            raw_bearer.add(key)
            if key in required_bearer:
                found_required_bearer.add(key)
                continue
            operation["security"] = [{}, {"HTTPBearer": []}]
    assert found_required_bearer == required_bearer
    assert found_parent_optional_bearer == expected_parent_optional_bearer
    optional_shape = [{}, {"HTTPBearer": []}]
    final_optional = set()
    final_required = set()
    final_no_security = set()
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            key = (path, method)
            if operation.get("security") == optional_shape:
                final_optional.add(key)
            elif operation.get("security") == bearer_shape:
                final_required.add(key)
            elif "security" not in operation:
                final_no_security.add(key)
    assert final_optional == (raw_bearer - required_bearer) | expected_parent_optional_bearer
    assert final_required == required_bearer
    assert final_no_security == expected_public_no_security
    full_interface_profile = (
        present_parent_families == set(OPTIONAL_PARENT_AUTH_FAMILIES)
        and present_public_families == set(OPTIONAL_PUBLIC_FAMILIES)
    )
    if full_interface_profile:
        assert len(raw_bearer) == 122
        assert len(final_optional) == 136
        assert len(final_required) == 1
        assert len(final_no_security) == 9
    NOTES.append(
        "runtime response enrichments: component update and restore, schedule enable, approval "
        "count, session update, knowledge refresh, Queue, and media branches; "
        "PaginationInfo wording aligned with its emitted default and minimum"
    )
    NOTES.append(
        f"authentication profile: {len(final_optional)} HTTPBearer operations allow the documented "
        f"open-AgentOS alternative; {len(final_required)} operation remains bearer-only and "
        f"{len(final_no_security)} public or self-authenticating operations remain open"
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
        declared_key = None
        if len(declared) == 1:
            method, route = declared[0].split(" ", 1)
            declared_key = (route, method.lower())
        if len(declared) != 1 or (
            declared[0] not in expected
            and declared_key not in OPTIONAL_INTERFACE_OPERATIONS
        ):
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
    app, interfaces = build_app()
    spec = apply_runtime_description_enrichments(app.openapi(), interfaces)
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
