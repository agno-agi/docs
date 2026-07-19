"""Dry-run generator for the AgentOS OpenAPI spec.

Builds a representative AgentOS app (no serving, no network) covering the
surface of the reference-api spec, dumps app.openapi() to
scripts/out/openapi.json / openapi.yaml, and writes a structured diff against
the checked-in reference-api/openapi.yaml to scripts/out/openapi-diff.md.

Never touches reference-api/ itself. It carries forward the reviewed Slack
request metadata that FastAPI cannot derive from the router implementation.

Run with a venv where agno[os,mcp,telegram,agui,a2a,slack] is importable:
  python scripts/make_openapi.py

Interfaces whose optional dependency is missing (e.g. a2a-sdk for A2A) are
excluded from the app and reported in the generator notes.
"""

import json
import os
import sys
from copy import deepcopy
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


def apply_runtime_description_enrichments(spec: dict) -> dict:
    """Document runtime branches that the pinned route metadata omits."""
    schemas = spec["components"]["schemas"]

    def response_ref(description: str, schema_name: str) -> dict:
        assert schema_name in schemas, schema_name
        return {
            "description": description,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{schema_name}"},
                }
            },
        }

    def add_response(operation: dict, status: str, description: str, schema_name: str) -> None:
        assert status not in operation["responses"], (operation.get("operationId"), status)
        operation["responses"][status] = response_ref(description, schema_name)

    def sort_responses(operation: dict) -> None:
        operation["responses"] = dict(
            sorted(operation["responses"].items(), key=lambda item: int(item[0]))
        )

    def get_parameter(operation: dict, name: str) -> dict:
        matches = [parameter for parameter in operation["parameters"] if parameter["name"] == name]
        assert len(matches) == 1, (operation.get("operationId"), name, len(matches))
        return matches[0]

    for schema_name, title, example in (
        ("ForbiddenResponse", "ForbiddenResponse", {"detail": "Insufficient permissions"}),
        ("ConflictResponse", "ConflictResponse", {"detail": "Resource conflict"}),
        (
            "NotImplementedResponse",
            "NotImplementedResponse",
            {"detail": "Operation not supported for this resource type"},
        ),
        (
            "ServiceUnavailableResponse",
            "ServiceUnavailableResponse",
            {"detail": "Feature not supported by the configured service"},
        ),
    ):
        assert schema_name not in schemas
        schemas[schema_name] = {
            "properties": {
                "detail": {
                    "type": "string",
                    "title": "Detail",
                    "description": "Error detail message",
                },
            },
            "type": "object",
            "required": ["detail"],
            "title": title,
            "example": example,
        }

    config_example = spec["paths"]["/config"]["get"]["responses"]["200"]["content"]["application/json"][
        "example"
    ]
    assert config_example.get("id") == "demo" and "os_id" not in config_example
    config_example["os_id"] = config_example.pop("id")

    home = spec["paths"]["/"]["get"]
    assert home["description"] == (
        "Get basic information about this AgentOS API instance, including:\n\n"
        "- API metadata and version\n"
        "- Available capabilities overview\n"
        "- Links to key endpoints and documentation"
    )
    home["description"] = "Return the AgentOS instance name, ID, and version."
    home_schema = home["responses"]["200"]["content"]["application/json"]["schema"]
    assert home_schema == {}
    home_schema.update(
        {
            "properties": {
                "name": {"type": "string", "title": "Name"},
                "id": {"type": "string", "title": "Id"},
                "version": {"type": "string", "title": "Version"},
            },
            "type": "object",
            "required": ["name", "id", "version"],
            "title": "ApiInfoResponse",
        }
    )

    component_config = spec["paths"]["/components/{component_id}/configs/{version}"]["get"]
    assert component_config["operationId"] == "get_config"
    component_config["operationId"] = "get_config_version"

    delete_component = spec["paths"]["/components/{component_id}"]["delete"]
    assert delete_component["description"] == "Delete a component by ID."
    delete_component["description"] = (
        "Soft-delete a component by ID. Component configs and links remain stored."
    )

    assert "BackgroundRunResponse" not in schemas
    schemas["BackgroundRunResponse"] = {
        "properties": {
            "run_id": {
                "type": "string",
                "title": "Run Id",
                "description": "Unique identifier for the background run.",
            },
            "session_id": {
                "type": "string",
                "title": "Session Id",
                "description": "Session that contains the background run.",
            },
            "status": {
                "type": "string",
                "title": "Status",
                "description": "Initial run status.",
            },
        },
        "type": "object",
        "required": ["run_id", "session_id", "status"],
        "title": "BackgroundRunResponse",
    }

    run_endpoints = (
        ("agents", "agent_id", "RunSchema"),
        ("teams", "team_id", "TeamRunSchema"),
        ("workflows", "workflow_id", "WorkflowRunSchema"),
    )
    for component, id_parameter, run_schema in run_endpoints:
        assert run_schema in schemas

        create_run = spec["paths"][f"/{component}/{{{id_parameter}}}/runs"]["post"]
        create_responses = create_run["responses"]
        create_json_schema = create_responses["200"]["content"]["application/json"]["schema"]
        assert create_json_schema == {}
        create_json_schema["$ref"] = f"#/components/schemas/{run_schema}"
        assert "202" not in create_responses
        create_responses["202"] = {
            "description": "Background run accepted when `background=true` and `stream=false`.",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/BackgroundRunResponse"},
                }
            },
        }
        create_run["responses"] = dict(sorted(create_responses.items(), key=lambda item: int(item[0])))

        get_run = spec["paths"][f"/{component}/{{{id_parameter}}}/runs/{{run_id}}"]["get"]
        get_json_schema = get_run["responses"]["200"]["content"]["application/json"]["schema"]
        assert get_json_schema == {}
        get_json_schema["$ref"] = f"#/components/schemas/{run_schema}"

        continue_run = spec["paths"][f"/{component}/{{{id_parameter}}}/runs/{{run_id}}/continue"]["post"]
        continue_json_schema = continue_run["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert continue_json_schema == {}
        continue_json_schema["$ref"] = f"#/components/schemas/{run_schema}"
        continue_sse = continue_run["responses"]["200"]["content"]["text/event-stream"]
        assert "schema" not in continue_sse
        continue_sse["schema"] = {"type": "string"}

    continue_agent_run = spec["paths"]["/agents/{agent_id}/runs/{run_id}/continue"]["post"]
    continue_agent_responses = continue_agent_run["responses"]
    assert continue_agent_responses["200"]["description"] == "Agent run continued successfully"
    continue_agent_responses["200"]["description"] = (
        "A non-streaming run response or a server-sent event stream. Streaming execution failures "
        "are delivered as events after the stream starts."
    )
    assert continue_agent_responses["400"]["description"] == (
        "Invalid JSON in tools field or invalid tool structure"
    )
    continue_agent_responses["400"]["description"] = (
        "Invalid tools or continuation boundary, missing local session ID, rejected input, "
        "or background streaming requested for a remote agent"
    )
    assert continue_agent_responses["403"] == {
        "description": "Run has a pending admin approval and cannot be continued by the user yet."
    }
    continue_agent_responses["403"] = response_ref(
        "Agent run access denied, or a required admin approval is unresolved",
        "ForbiddenResponse",
    )
    assert continue_agent_responses["404"]["description"] == "Agent not found"
    continue_agent_responses["404"]["description"] = "Agent, session, or run not found"
    add_response(
        continue_agent_run,
        "409",
        "Run is in a state that cannot be continued",
        "ConflictResponse",
    )
    continue_agent_validation = continue_agent_responses["422"]["content"]["application/json"][
        "schema"
    ]
    assert continue_agent_validation == {"$ref": "#/components/schemas/ValidationErrorResponse"}
    continue_agent_validation["$ref"] = "#/components/schemas/HTTPValidationError"
    add_response(
        continue_agent_run,
        "503",
        "Remote agent is unavailable",
        "ServiceUnavailableResponse",
    )
    add_response(
        continue_agent_run,
        "501",
        "The selected agent does not support run continuation",
        "NotImplementedResponse",
    )
    sort_responses(continue_agent_run)

    cancel_agent_run = spec["paths"]["/agents/{agent_id}/runs/{run_id}/cancel"]["post"]
    add_response(
        cancel_agent_run,
        "501",
        "The selected agent does not support run cancellation",
        "NotImplementedResponse",
    )
    sort_responses(cancel_agent_run)

    continue_team_run = spec["paths"]["/teams/{team_id}/runs/{run_id}/continue"]["post"]
    continue_team_responses = continue_team_run["responses"]
    assert continue_team_responses["200"]["description"] == "Team run continued successfully"
    continue_team_responses["200"]["description"] = (
        "A non-streaming run response or a server-sent event stream. Streaming execution failures "
        "are delivered as events after the stream starts."
    )
    assert continue_team_responses["400"]["description"] == (
        "Invalid JSON in requirements field or invalid requirement structure"
    )
    continue_team_responses["400"]["description"] = (
        "Invalid requirements or continuation boundary, missing local session ID, rejected input, "
        "or background streaming requested for a remote team"
    )
    assert continue_team_responses["403"] == {
        "description": "Run has a pending admin approval and cannot be continued by the user yet."
    }
    continue_team_responses["403"] = response_ref(
        "Team run access denied, or a required admin approval is unresolved",
        "ForbiddenResponse",
    )
    assert continue_team_responses["404"]["description"] == "Team not found"
    continue_team_responses["404"]["description"] = "Team, session, or run not found"
    assert continue_team_responses["409"] == {
        "description": (
            "Run is not paused (e.g. run is already running, continued, or errored). "
            "Only PAUSED runs can be continued."
        )
    }
    continue_team_responses["409"] = response_ref(
        "Run is in a state that cannot be continued",
        "ConflictResponse",
    )
    continue_team_validation = continue_team_responses["422"]["content"]["application/json"][
        "schema"
    ]
    assert continue_team_validation == {"$ref": "#/components/schemas/ValidationErrorResponse"}
    continue_team_validation["$ref"] = "#/components/schemas/HTTPValidationError"
    add_response(
        continue_team_run,
        "503",
        "Remote team is unavailable",
        "ServiceUnavailableResponse",
    )
    sort_responses(continue_team_run)

    continue_workflow_run = spec["paths"]["/workflows/{workflow_id}/runs/{run_id}/continue"]["post"]
    continue_workflow_responses = continue_workflow_run["responses"]
    assert continue_workflow_responses["200"]["description"] == "Workflow run continued successfully"
    continue_workflow_responses["200"]["description"] = (
        "A non-streaming run response or a server-sent event stream. Streaming execution failures "
        "are delivered as events after the stream starts."
    )
    assert continue_workflow_responses["400"]["description"] == "Invalid JSON in requirements field"
    continue_workflow_responses["400"]["description"] = (
        "Invalid step requirements or factory input, missing required session ID, rejected input, "
        "or remote workflow continuation requested"
    )
    assert continue_workflow_responses["404"]["description"] == "Workflow not found"
    continue_workflow_responses["404"]["description"] = "Workflow, session, or run not found"
    assert continue_workflow_responses["409"] == {
        "description": "Run is not paused. Only PAUSED runs can be continued."
    }
    continue_workflow_responses["409"] = response_ref(
        "Run is not paused and cannot be continued",
        "ConflictResponse",
    )
    continue_workflow_validation = continue_workflow_responses["422"]["content"]["application/json"][
        "schema"
    ]
    assert continue_workflow_validation == {"$ref": "#/components/schemas/ValidationErrorResponse"}
    continue_workflow_validation["$ref"] = "#/components/schemas/HTTPValidationError"
    sort_responses(continue_workflow_run)

    list_teams = spec["paths"]["/teams"]["get"]
    assert list_teams["summary"] == "List All Teams"
    list_teams["summary"] = "List Accessible Teams"
    assert list_teams["description"] == (
        "Retrieve a comprehensive list of all teams configured in this OS instance.\n\n"
        "**Returns team information including:**\n"
        "- Team metadata (ID, name, description, execution mode)\n"
        "- Model configuration for team coordination\n"
        "- Team member roster with roles and capabilities\n"
        "- Knowledge sharing and memory configurations"
    )
    list_teams["description"] = (
        "Retrieve configured team metadata, models, members, knowledge, and memory settings. "
        "When authorization is enabled, in-memory team registrations are filtered by caller scopes. "
        "Database-loaded team components are also included."
    )

    list_workflows = spec["paths"]["/workflows"]["get"]
    assert list_workflows["summary"] == "List All Workflows"
    list_workflows["summary"] = "List Workflows"
    assert list_workflows["description"] == (
        "Retrieve a comprehensive list of all workflows configured in this OS instance.\n\n"
        "**Return Information:**\n"
        "- Workflow metadata (ID, name, description)\n"
        "- Input schema requirements\n"
        "- Step sequence and execution flow\n"
        "- Associated agents and teams"
    )
    list_workflows["description"] = (
        "Return workflow ID, name, description, database ID, factory metadata, and Builder "
        "version metadata. When authorization is enabled, caller scopes filter in-memory "
        "workflow registrations. Database-loaded Builder workflows are appended separately."
    )

    content_status = spec["paths"]["/knowledge/content/{content_id}/status"]["get"]
    assert content_status["description"] == (
        "Retrieve the current processing status of a content item. Useful for monitoring "
        "asynchronous content processing progress and identifying any processing errors."
    )
    content_status["description"] = (
        "Return the processing status for a content ID. For local knowledge in Agno 2.7.4, "
        "an unknown content ID returns HTTP 200 with `status=\"failed\"` and "
        "`status_message=\"Content not found\"`."
    )
    content_status_responses = content_status["responses"]
    assert content_status_responses["200"]["description"] == "Content status retrieved successfully"
    content_status_responses["200"]["description"] = (
        'Content status returned. An unknown local content ID is represented by status "failed".'
    )
    status_examples = content_status_responses["200"]["content"]["application/json"]["examples"]
    assert set(status_examples) == {"completed"}
    status_examples.clear()
    status_examples.update(
        {
            "completed": {
                "summary": "Completed content",
                "value": {
                    "id": "content-123",
                    "status": "completed",
                    "status_message": "",
                },
            },
            "content_not_found": {
                "summary": "Unknown local content ID",
                "value": {
                    "id": "missing-content",
                    "status": "failed",
                    "status_message": "Content not found",
                },
            },
        }
    )
    assert content_status_responses["404"]["description"] == "Content not found"
    content_status_responses["404"]["description"] = "Selected knowledge base or database ID not found"

    list_content = spec["paths"]["/knowledge/content"]["get"]
    assert list_content["description"] == (
        "Retrieve paginated list of all content in the knowledge base with filtering and sorting options. "
        "Filter by status, content type, or metadata properties."
    )
    list_content["description"] = (
        "Return a paginated, sorted list of content for the selected knowledge base. Use `limit`, "
        "`page`, `sort_by`, and `sort_order` to control the result. Agno 2.7.4 exposes no status, "
        "content type, or metadata filter parameters on this endpoint. Named local knowledge "
        "instances scope rows by the stored `linked_to` value."
    )

    one_based_page_description = (
        "1-based page number. Agno 2.7.4 also accepts 0 at request validation, but the "
        "pagination implementation is 1-based. Use 1 or greater."
    )
    zero_accepting_page_parameters = (
        ("/sessions", "Page number for pagination"),
        ("/memories", "Page number for pagination"),
        ("/user_memory_stats", "Page number for pagination"),
        ("/eval-runs", "Page number"),
        ("/knowledge/content", "Page number"),
        ("/traces", "Page number (1-indexed)"),
    )
    for path, source_description in zero_accepting_page_parameters:
        operation = spec["paths"][path]["get"]
        page_parameter = get_parameter(operation, "page")
        assert page_parameter["description"] == source_description
        assert page_parameter["schema"]["description"] == source_description
        assert page_parameter["schema"]["default"] == 1
        page_minimum = page_parameter["schema"].get("minimum")
        if page_minimum is None:
            page_minimum = page_parameter["schema"]["anyOf"][0]["minimum"]
        assert page_minimum == 0
        page_parameter["description"] = one_based_page_description
        page_parameter["schema"]["description"] = one_based_page_description

    pagination_page = schemas["PaginationInfo"]["properties"]["page"]
    assert pagination_page["description"] == "Current page number (0-indexed)"
    assert pagination_page["minimum"] == 0 and pagination_page["default"] == 0
    pagination_page["description"] = (
        "Page value returned by the endpoint. AgentOS paginated routes use 1-based page numbers. "
        "Some Agno 2.7.4 routes accept and echo 0 even though their pagination implementation "
        "is 1-based."
    )

    content_properties = schemas["ContentResponseSchema"]["properties"]
    assert content_properties["linked_to"]["description"] == "ID of related content if linked"
    content_properties["linked_to"]["description"] = (
        "Knowledge instance name used for content isolation. Local Agno 2.7.4 responses return "
        "null because response conversion does not propagate the stored value."
    )
    assert content_properties["access_count"]["description"] == (
        "Number of times content has been accessed"
    )
    content_properties["access_count"]["description"] = (
        "Stored access count. Local Agno 2.7.4 responses return null because response conversion "
        "does not propagate the stored value."
    )

    content_examples = (
        list_content["responses"]["200"]["content"]["application/json"]["example"]["data"][0],
        spec["paths"]["/knowledge/content/{content_id}"]["patch"]["responses"]["200"]["content"]
        ["application/json"]["example"],
        spec["paths"]["/knowledge/content/{content_id}"]["get"]["responses"]["200"]["content"]
        ["application/json"]["example"],
    )
    for example in content_examples:
        assert example["access_count"] == 1 and "linked_to" not in example
        example["access_count"] = None
        example["linked_to"] = None

    for path, description in (
        ("/knowledge/remote-content", "Remote content upload is unavailable for remote knowledge bases"),
        (
            "/knowledge/{knowledge_id}/sources",
            "Content source listing is unavailable for remote knowledge bases",
        ),
        (
            "/knowledge/{knowledge_id}/sources/{source_id}/files",
            "Source file listing is unavailable for remote knowledge bases",
        ),
    ):
        operation = spec["paths"][path]["post" if path == "/knowledge/remote-content" else "get"]
        add_response(operation, "501", description, "NotImplementedResponse")
        sort_responses(operation)

    learning_operations = (
        ("/learnings", "get"),
        ("/learnings", "post"),
        ("/learnings/users", "get"),
        ("/learnings/users/{user_id}", "delete"),
        ("/learnings/{learning_id}", "get"),
        ("/learnings/{learning_id}", "patch"),
        ("/learnings/{learning_id}", "delete"),
    )
    for path, method in learning_operations:
        operation = spec["paths"][path][method]
        add_response(
            operation,
            "501",
            "Learnings are unavailable for remote or unsupported databases",
            "NotImplementedResponse",
        )
        sort_responses(operation)

    create_learning = spec["paths"]["/learnings"]["post"]
    add_response(
        create_learning,
        "409",
        "An identity-keyed learning already exists",
        "ConflictResponse",
    )
    sort_responses(create_learning)

    update_content = spec["paths"]["/knowledge/content/{content_id}"]["patch"]
    assert update_content["description"] == (
        "Update content properties such as name, description, metadata, or processing configuration. "
        "Allows modification of existing content without re-uploading."
    )
    update_content["description"] = (
        "Update content name, description, or metadata without re-uploading it. "
        "In Agno 2.7.4, this endpoint accepts `reader_id`. Local knowledge validates the value, "
        "but the content patch does not apply or persist the reader change."
    )
    reader_id = schemas["Body_update_content"]["properties"]["reader_id"]
    assert reader_id["description"] == "ID of the reader to use for processing"
    reader_id["description"] = (
        "Reader ID. In Agno 2.7.4, local knowledge validates the value, but the content patch "
        "does not apply or persist the reader change."
    )

    delete_eval_runs = spec["paths"]["/eval-runs"]["delete"]
    eval_responses = delete_eval_runs["responses"]
    assert eval_responses["400"]["description"] == "Bad Request"
    assert eval_responses["404"]["description"] == "Not Found"
    del eval_responses["400"]
    del eval_responses["404"]
    assert eval_responses["500"]["description"] == "Failed to delete evaluation runs"
    eval_responses["500"]["description"] = (
        "Deletion failed. In Agno 2.7.4, failures including invalid database or table selections "
        "surface as 500 responses."
    )

    get_metrics = spec["paths"]["/metrics"]["get"]
    metrics_get_responses = get_metrics["responses"]
    assert metrics_get_responses["400"]["description"] == "Invalid date range parameters"
    assert metrics_get_responses["404"]["description"] == "Not Found"
    del metrics_get_responses["400"]
    del metrics_get_responses["404"]
    assert metrics_get_responses["500"]["description"] == "Failed to retrieve metrics"
    metrics_get_responses["500"]["description"] = (
        "Metrics retrieval failed. In Agno 2.7.4, invalid or ambiguous database selections "
        "surface as 500 responses."
    )

    refresh_metrics = spec["paths"]["/metrics/refresh"]["post"]
    metrics_responses = refresh_metrics["responses"]
    assert metrics_responses["400"]["description"] == "Bad Request"
    assert metrics_responses["404"]["description"] == "Not Found"
    del metrics_responses["400"]
    del metrics_responses["404"]
    assert metrics_responses["500"]["description"] == "Failed to refresh metrics"
    metrics_responses["500"]["description"] = (
        "Refresh failed. In Agno 2.7.4, failures including invalid database or table selections "
        "surface as 500 responses."
    )

    list_agent_runs = spec["paths"]["/agents/{agent_id}/runs"]["get"]
    list_runs_schema = list_agent_runs["responses"]["200"]["content"]["application/json"]["schema"]
    assert list_runs_schema == {}
    list_runs_schema.update(
        {
            "items": {"$ref": "#/components/schemas/RunSchema"},
            "type": "array",
            "title": "Response List Agent Runs",
        }
    )
    status_parameters = [
        parameter for parameter in list_agent_runs["parameters"] if parameter["name"] == "status"
    ]
    assert len(status_parameters) == 1
    status_parameter = status_parameters[0]
    old_status_description = "Filter by run status (PENDING, RUNNING, COMPLETED, ERROR)"
    new_status_description = (
        "Filter by run status: PENDING, RUNNING, COMPLETED, PAUSED, CANCELLED, ERROR, or REGENERATED"
    )
    assert status_parameter["description"] == old_status_description
    assert status_parameter["schema"]["description"] == old_status_description
    status_parameter["description"] = new_status_description
    status_parameter["schema"]["description"] = new_status_description
    list_run_responses = list_agent_runs["responses"]
    assert list_run_responses["400"]["description"] == "Bad Request"
    list_run_responses["400"]["description"] = "Run listing is unavailable for remote agents"
    assert list_run_responses["404"]["description"] == "Agent not found"
    list_run_responses["404"]["description"] = "Agent or session not found"
    assert list_run_responses["500"]["description"] == "Internal Server Error"
    list_run_responses["500"]["description"] = "Agent resolution failed"
    add_response(
        list_agent_runs,
        "501",
        "The selected agent does not support run listing",
        "NotImplementedResponse",
    )
    sort_responses(list_agent_runs)

    revoke_service_account = spec["paths"]["/service-accounts/{service_account_id}"]["delete"]
    assert revoke_service_account["description"] == (
        "Revoke a service account. Idempotent.\n\n"
        "Takes effect immediately on this worker (the local verification cache entry is\n"
        "evicted) and within the cache TTL on other workers."
    )
    revoke_service_account["description"] = (
        "Revoke an existing service account.\n\n"
        "Takes effect immediately on this worker (the local verification cache entry is "
        "evicted) and within the cache TTL on other workers."
    )
    revoke_responses = revoke_service_account["responses"]
    assert set(revoke_responses) == {"204", "422"}
    revoke_responses.update(
        {
            "401": {
                "description": "Unauthorized",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/UnauthenticatedResponse"},
                    }
                },
            },
            "404": {
                "description": "Service account not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/NotFoundResponse"},
                    }
                },
            },
            "500": {
                "description": "Service account could not be revoked",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/InternalServerErrorResponse"},
                    }
                },
            },
            "503": {
                "description": "Service accounts are not supported by the configured database",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ServiceUnavailableResponse"},
                    }
                },
            },
        }
    )
    revoke_service_account["responses"] = dict(sorted(revoke_responses.items(), key=lambda item: int(item[0])))

    create_service_account = spec["paths"]["/service-accounts"]["post"]
    assert set(create_service_account["responses"]) == {"201", "422"}
    add_response(
        create_service_account,
        "400",
        "Requested scopes are invalid, or privileged scopes were not explicitly allowed",
        "BadRequestResponse",
    )
    add_response(
        create_service_account,
        "409",
        "An active service account with this name already exists",
        "ConflictResponse",
    )
    add_response(
        create_service_account,
        "500",
        "Service account could not be created",
        "InternalServerErrorResponse",
    )
    add_response(
        create_service_account,
        "503",
        "Service accounts are not supported by the configured database",
        "ServiceUnavailableResponse",
    )
    sort_responses(create_service_account)

    list_service_accounts = spec["paths"]["/service-accounts"]["get"]
    assert set(list_service_accounts["responses"]) == {"200", "422"}
    add_response(
        list_service_accounts,
        "503",
        "Service accounts are not supported by the configured database",
        "ServiceUnavailableResponse",
    )
    sort_responses(list_service_accounts)

    approval_operations = (
        (
            "/approvals",
            "get",
            "200",
            (
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
                ("500", "Approvals could not be listed", "InternalServerErrorResponse"),
            ),
        ),
        (
            "/approvals/count",
            "get",
            "200",
            (
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
                ("500", "Approval count could not be retrieved", "InternalServerErrorResponse"),
            ),
        ),
        (
            "/approvals/{approval_id}/status",
            "get",
            "200",
            (
                ("404", "Approval not found or not visible to the caller", "NotFoundResponse"),
                ("500", "Approval status could not be retrieved", "InternalServerErrorResponse"),
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
            ),
        ),
        (
            "/approvals/{approval_id}",
            "get",
            "200",
            (
                ("404", "Approval not found or not visible to the caller", "NotFoundResponse"),
                ("500", "Approval could not be retrieved", "InternalServerErrorResponse"),
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
            ),
        ),
        (
            "/approvals/{approval_id}/resolve",
            "post",
            "200",
            (
                ("404", "Approval not found or not available to the caller", "NotFoundResponse"),
                ("409", "Approval has already been resolved", "ConflictResponse"),
                ("500", "Approval could not be resolved", "InternalServerErrorResponse"),
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
            ),
        ),
        (
            "/approvals/{approval_id}",
            "delete",
            "204",
            (
                ("404", "Approval is not available to the caller", "NotFoundResponse"),
                ("500", "Approval could not be deleted", "InternalServerErrorResponse"),
                (
                    "503",
                    "Approvals are not supported by the configured database",
                    "ServiceUnavailableResponse",
                ),
            ),
        ),
    )
    for path, method, success_status, additions in approval_operations:
        operation = spec["paths"][path][method]
        assert set(operation["responses"]) == {success_status, "422"}, operation["operationId"]
        for status, description, schema_name in additions:
            add_response(operation, status, description, schema_name)
        sort_responses(operation)

    schedule_operations = (
        ("/schedules", "get", "200", (("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),)),
        (
            "/schedules",
            "post",
            "201",
            (
                ("409", "A schedule with this name already exists", "ConflictResponse"),
                ("500", "Schedule could not be created", "InternalServerErrorResponse"),
                ("503", "Scheduler dependencies or storage are unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}",
            "get",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}",
            "patch",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("409", "A schedule with this name already exists", "ConflictResponse"),
                ("500", "Schedule could not be updated", "InternalServerErrorResponse"),
                ("503", "Scheduler dependencies or storage are unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}",
            "delete",
            "204",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("500", "Schedule could not be deleted", "InternalServerErrorResponse"),
                ("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}/enable",
            "post",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("500", "Schedule could not be enabled", "InternalServerErrorResponse"),
                ("503", "Scheduler dependencies or storage are unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}/disable",
            "post",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("500", "Schedule could not be disabled", "InternalServerErrorResponse"),
                ("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}/trigger",
            "post",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("409", "Schedule is disabled", "ConflictResponse"),
                ("503", "Scheduler is not running or storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}/runs",
            "get",
            "200",
            (
                ("404", "Schedule not found", "NotFoundResponse"),
                ("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
        (
            "/schedules/{schedule_id}/runs/{run_id}",
            "get",
            "200",
            (
                ("404", "Schedule run not found", "NotFoundResponse"),
                ("503", "Scheduler storage is unavailable", "ServiceUnavailableResponse"),
            ),
        ),
    )
    for path, method, success_status, additions in schedule_operations:
        operation = spec["paths"][path][method]
        assert set(operation["responses"]) == {success_status, "422"}, operation["operationId"]
        for status, description, schema_name in additions:
            add_response(operation, status, description, schema_name)
        sort_responses(operation)

    for migration_path, schema_title in (
        ("/databases/all/migrate", "MigrationResponse"),
        ("/databases/{db_id}/migrate", "MigrationResponse"),
    ):
        migration = spec["paths"][migration_path]["post"]
        success_schema = migration["responses"]["200"]["content"]["application/json"]["schema"]
        assert success_schema == {}
        success_schema.update(
            {
                "properties": {"message": {"type": "string", "title": "Message"}},
                "type": "object",
                "required": ["message"],
                "title": schema_title,
            }
        )

    migrate_all_databases = spec["paths"]["/databases/all/migrate"]["post"]
    assert "207" not in migrate_all_databases["responses"]
    migrate_all_databases["responses"]["207"] = {
        "description": "Some database migrations failed",
        "content": {
            "application/json": {
                "schema": {
                    "properties": {
                        "message": {"type": "string", "title": "Message"},
                        "failed": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "title": "Failed",
                        },
                    },
                    "type": "object",
                    "required": ["message", "failed"],
                    "title": "PartialMigrationResponse",
                },
                "example": {
                    "message": "Migrated 2/3 databases to latest version",
                    "failed": {"archive-db": "Migration failed"},
                },
            }
        },
    }
    sort_responses(migrate_all_databases)

    optimize_memories = spec["paths"]["/optimize-memories"]["post"]
    assert optimize_memories["description"] == (
        "Optimize all memories for a given user using the default summarize strategy. This operation "
        "combines all memories into a single comprehensive summary, achieving maximum token reduction "
        "while preserving all key information. To use a custom model, specify the model parameter in "
        "'provider:model_id' format (e.g., 'openai:gpt-4o-mini', "
        "'anthropic:claude-3-5-sonnet-20241022'). If not specified, uses MemoryManager's default model "
        "(gpt-4o). Set apply=false to preview optimization results without saving to database."
    )
    optimize_memories["description"] = (
        "Optimize all memories for a user with the summarize strategy. The operation combines the "
        "user's memories into one summary. Set `apply=false` to preview the result without saving it. "
        "Specify a custom model as `provider:model_id`, for example `openai:gpt-5.4-mini`, "
        "`anthropic:claude-sonnet-4-6`, or `google:gemini-3.5-flash`. If omitted, Agno v2.7.4 uses "
        "MemoryManager's default model, `gpt-4o`."
    )
    optimize_model = schemas["OptimizeMemoriesRequest"]["properties"]["model"]
    assert optimize_model["description"] == (
        "Model to use for optimization in format 'provider:model_id' (e.g., 'openai:gpt-4o-mini', "
        "'anthropic:claude-3-5-sonnet-20241022', 'google:gemini-2.0-flash-exp'). If not specified, uses "
        "MemoryManager's default model (gpt-4o)."
    )
    optimize_model["description"] = (
        "Model in `provider:model_id` format. Current examples include `openai:gpt-5.4-mini`, "
        "`anthropic:claude-sonnet-4-6`, and `google:gemini-3.5-flash`. If omitted, Agno v2.7.4 uses "
        "MemoryManager's default model, `gpt-4o`."
    )

    delete_config = spec["paths"]["/components/{component_id}/configs/{version}"]["delete"]
    assert delete_config["description"] == (
        "Delete a specific draft config version. Cannot delete published or current configs."
    )
    delete_config["description"] = (
        "Delete a specific config version. Agno v2.7.4 rejects the current version. Synchronous "
        "SQLite and PostgreSQL storage allow deletion of a published non-current version."
    )

    whatsapp_path = spec["paths"].get("/whatsapp/webhook")
    if whatsapp_path is not None:
        whatsapp_status = spec["paths"]["/whatsapp/status"]["get"]
        status_schema = whatsapp_status["responses"]["200"]["content"]["application/json"]["schema"]
        assert status_schema == {}
        status_schema.update(
            {
                "properties": {"status": {"type": "string", "title": "Status"}},
                "type": "object",
                "required": ["status"],
                "title": "WhatsAppStatusResponse",
                "example": {"status": "available"},
            }
        )

        whatsapp_verify = whatsapp_path["get"]
        assert whatsapp_verify.get("parameters") in (None, [])
        whatsapp_verify["parameters"] = [
            {
                "name": "hub.mode",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Webhook verification mode. Meta sends `subscribe`.",
            },
            {
                "name": "hub.verify_token",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Verification token configured for the WhatsApp interface.",
            },
            {
                "name": "hub.challenge",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Challenge returned as plain text after successful verification.",
            },
        ]
        verify_success = whatsapp_verify["responses"]["200"]
        assert verify_success["content"] == {"application/json": {"schema": {}}}
        verify_success["description"] = "Webhook challenge accepted"
        verify_success["content"] = {
            "text/plain": {
                "schema": {"type": "string"},
                "example": "challenge-token",
            }
        }
        add_response(whatsapp_verify, "400", "No challenge was provided", "BadRequestResponse")
        add_response(whatsapp_verify, "403", "Invalid verify token or mode", "ForbiddenResponse")
        add_response(
            whatsapp_verify,
            "500",
            "Webhook verification is not configured",
            "InternalServerErrorResponse",
        )
        sort_responses(whatsapp_verify)

        whatsapp_webhook = whatsapp_path["post"]
        assert whatsapp_webhook["description"] == "Process incoming WhatsApp messages"
        assert "requestBody" not in whatsapp_webhook
        assert whatsapp_webhook.get("parameters") in (None, [])
        whatsapp_webhook["parameters"] = [
            {
                "name": "X-Hub-Signature-256",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "description": "SHA-256 HMAC signature for the raw request body, prefixed with `sha256=`",
            }
        ]
        whatsapp_webhook["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True},
                }
            },
        }
        assert set(whatsapp_webhook["responses"]) == {"200", "403"}
        assert whatsapp_webhook["responses"]["403"] == {"description": "Invalid webhook signature"}
        whatsapp_webhook["responses"]["403"] = response_ref(
            "Invalid webhook signature", "ForbiddenResponse"
        )
        add_response(
            whatsapp_webhook,
            "500",
            "Signature validation is not configured, or the JSON body is malformed or is not an object",
            "InternalServerErrorResponse",
        )
        sort_responses(whatsapp_webhook)

    slack_events_path = spec["paths"].get("/slack/events")
    if slack_events_path is not None:
        slack_events = slack_events_path["post"]
        assert set(slack_events["responses"]) == {"200", "400", "403"}
        assert "requestBody" not in slack_events
        slack_events["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True},
                }
            },
        }
        assert slack_events["responses"]["400"] == {"description": "Missing Slack headers"}
        slack_events["responses"]["400"] = response_ref("Missing Slack headers", "BadRequestResponse")
        assert slack_events["responses"]["403"] == {"description": "Invalid Slack signature"}
        slack_events["responses"]["403"] = response_ref("Invalid Slack signature", "ForbiddenResponse")
        add_response(
            slack_events,
            "500",
            "Slack signing is not configured, or the event body is not valid JSON",
            "InternalServerErrorResponse",
        )
        sort_responses(slack_events)

        slack_interactions = spec["paths"]["/slack/interactions"]["post"]
        assert set(slack_interactions["responses"]) == {"200", "400", "403"}
        assert slack_interactions["responses"]["400"] == {"description": "Malformed interaction payload"}
        slack_interactions["responses"]["400"] = response_ref(
            "Missing Slack headers or malformed interaction payload", "BadRequestResponse"
        )
        assert slack_interactions["responses"]["403"] == {"description": "Invalid Slack signature"}
        slack_interactions["responses"]["403"] = response_ref(
            "Invalid Slack signature", "ForbiddenResponse"
        )
        add_response(
            slack_interactions,
            "500",
            "Slack signing is not configured",
            "InternalServerErrorResponse",
        )
        sort_responses(slack_interactions)

    agui_path = spec["paths"].get("/agui")
    if agui_path is not None:
        agui_run = agui_path["post"]
        assert agui_run.get("security") is None
        agui_run["security"] = [{"HTTPBearer": []}]
        agui_success = agui_run["responses"]["200"]
        assert agui_success["description"] == "Successful Response"
        assert agui_success["content"] == {"application/json": {"schema": {}}}
        agui_success["description"] = "Server-sent event stream"
        agui_success["content"] = {"text/event-stream": {"schema": {"type": "string"}}}

    a2a_families = (
        ("agents", "Agent"),
        ("teams", "Team"),
        ("workflows", "Workflow"),
    )
    a2a_paths = [
        f"/a2a/{family}/{{id}}/v1/message:{action}"
        for family, _ in a2a_families
        for action in ("send", "stream")
    ]
    present_a2a_paths = [path for path in a2a_paths if path in spec["paths"]]
    if present_a2a_paths:
        assert present_a2a_paths == a2a_paths
        from a2a.types import (
            AgentCard,
            CancelTaskSuccessResponse,
            CancelTaskRequest,
            GetTaskSuccessResponse,
            GetTaskRequest,
            SendMessageRequest,
            SendMessageSuccessResponse,
            SendStreamingMessageRequest,
        )

        for request_model in (SendMessageRequest, SendStreamingMessageRequest):
            request_schema = request_model.model_json_schema(
                ref_template="#/components/schemas/A2ARequest_{model}"
            )
            request_definitions = request_schema.pop("$defs")
            for definition_name, definition_schema in request_definitions.items():
                component_name = f"A2ARequest_{definition_name}"
                if component_name in schemas:
                    assert schemas[component_name] == definition_schema, component_name
                else:
                    schemas[component_name] = definition_schema
            assert request_model.__name__ not in schemas
            schemas[request_model.__name__] = request_schema

        deprecated_entity_id = schemas["A2ARequest_Message"]["properties"]
        assert "agentId" not in deprecated_entity_id
        deprecated_entity_id["agentId"] = {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Agent ID",
            "description": "Target agent, team, or workflow ID for deprecated dynamic-dispatch endpoints.",
        }

        card_schema = AgentCard.model_json_schema(ref_template="#/components/schemas/A2ACard_{model}")
        card_definitions = card_schema.pop("$defs")
        for definition_name, definition_schema in card_definitions.items():
            component_name = f"A2ACard_{definition_name}"
            assert component_name not in schemas
            schemas[component_name] = definition_schema
        assert "AgentCard" not in schemas
        schemas["AgentCard"] = card_schema

        for request_model, params_definition, context_required in (
            (GetTaskRequest, "TaskQueryParams", True),
            (CancelTaskRequest, "TaskIdParams", False),
        ):
            request_schema = request_model.model_json_schema(
                ref_template="#/components/schemas/A2ARequest_{model}"
            )
            request_definitions = request_schema.pop("$defs")
            params_schema = request_definitions[params_definition]
            assert "contextId" not in params_schema["properties"]
            params_schema["properties"]["contextId"] = {
                "type": "string",
                "title": "Context ID",
                "description": "Agno session ID containing the task.",
            }
            if context_required:
                assert params_schema["required"] == ["id"]
                params_schema["required"].append("contextId")
            for definition_name, definition_schema in request_definitions.items():
                component_name = f"A2ARequest_{definition_name}"
                assert component_name not in schemas
                schemas[component_name] = definition_schema
            assert request_model.__name__ not in schemas
            schemas[request_model.__name__] = request_schema

        for response_model in (GetTaskSuccessResponse, CancelTaskSuccessResponse):
            response_schema = response_model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            response_schema.pop("$defs")
            assert "Task" in schemas
            assert response_schema["properties"]["result"] == {
                "$ref": "#/components/schemas/Task"
            }
            assert response_model.__name__ not in schemas
            schemas[response_model.__name__] = response_schema

        success_example = SendMessageSuccessResponse.model_validate(
            {
                "jsonrpc": "2.0",
                "id": "request-123",
                "result": {
                    "id": "task-456",
                    "contextId": "context-789",
                    "status": {"state": "completed"},
                },
            }
        ).model_dump(mode="json", by_alias=True, exclude_none=True)
        get_task_example = {
            "id": "request-123",
            "jsonrpc": "2.0",
            "result": {
                "contextId": "context-789",
                "id": "task-456",
                "kind": "task",
                "status": {"state": "completed"},
            },
        }
        cancel_task_example = deepcopy(get_task_example)
        cancel_task_example["result"]["status"]["state"] = "canceled"

        for family, label in a2a_families:
            card_operation = spec["paths"][f"/a2a/{family}/{{id}}/.well-known/agent-card.json"]["get"]
            assert card_operation.get("security") is None
            card_operation["security"] = [{"HTTPBearer": []}]
            card_success = card_operation["responses"]["200"]
            assert card_success == {
                "description": "Successful Response",
                "content": {"application/json": {"schema": {}}},
            }
            card_operation["responses"]["200"] = response_ref(
                f"{label} card retrieved successfully",
                "AgentCard",
            )
            add_response(card_operation, "404", f"{label} not found", "NotFoundResponse")
            sort_responses(card_operation)

        for family, label in a2a_families[:2]:
            for action, request_schema_name in (
                ("get", "GetTaskRequest"),
                ("cancel", "CancelTaskRequest"),
            ):
                operation = spec["paths"][f"/a2a/{family}/{{id}}/v1/tasks:{action}"]["post"]
                expected_description = (
                    f"Get the status and result of {'an' if family == 'agents' else 'a'} {family[:-1]} task by ID."
                    if action == "get"
                    else f"Cancel a running {family[:-1]} task."
                )
                assert operation["description"] == expected_description
                if action == "get":
                    operation["description"] += " `params.contextId` identifies the session containing the task."
                else:
                    operation["description"] += (
                        " Scoped non-admin callers must identify the task's session with `params.contextId`."
                    )
                assert operation.get("security") is None
                operation["security"] = [{"HTTPBearer": []}]
                assert "requestBody" not in operation
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{request_schema_name}"},
                            "example": {
                                "jsonrpc": "2.0",
                                "id": "request-123",
                                "method": f"tasks/{action}",
                                "params": {"id": "task-456", "contextId": "context-789"},
                            },
                        }
                    },
                }
                task_success = operation["responses"]["200"]
                assert task_success == {
                    "description": "Successful Response",
                    "content": {"application/json": {"schema": {}}},
                }
                response_schema_name = (
                    "GetTaskSuccessResponse" if action == "get" else "CancelTaskSuccessResponse"
                )
                operation["responses"]["200"] = response_ref(
                    f"{label} task {'retrieved' if action == 'get' else 'canceled'} successfully",
                    response_schema_name,
                )
                operation["responses"]["200"]["content"]["application/json"]["example"] = deepcopy(
                    get_task_example if action == "get" else cancel_task_example
                )
                if action == "get":
                    bad_request_description = (
                        f"Missing task or context ID, or task polling requested for a remote {family[:-1]}"
                    )
                else:
                    bad_request_description = (
                        f"Missing task or required context ID, or task cancellation requested for a remote {family[:-1]}"
                    )
                add_response(
                    operation,
                    "400",
                    bad_request_description,
                    "BadRequestResponse",
                )
                add_response(
                    operation,
                    "404",
                    f"{label}, session, or task not found",
                    "NotFoundResponse",
                )
                if family == "agents":
                    add_response(
                        operation,
                        "501",
                        (
                            "Task polling is not supported for this agent type"
                            if action == "get"
                            else "Task cancellation is not supported for this agent type"
                        ),
                        "NotImplementedResponse",
                    )
                sort_responses(operation)

        for family, label in a2a_families:
            for action, request_schema_name in (
                ("send", "SendMessageRequest"),
                ("stream", "SendStreamingMessageRequest"),
            ):
                path = f"/a2a/{family}/{{id}}/v1/message:{action}"
                operation = spec["paths"][path]["post"]
                assert operation.get("security") is None
                operation["security"] = [{"HTTPBearer": []}]
                assert [parameter["name"] for parameter in operation["parameters"]] == ["id"]
                operation["parameters"].append(
                    {
                        "name": "X-User-ID",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": (
                            "Optional user ID for anonymous attribution. Authenticated requests use the "
                            "identity from the credential."
                        ),
                    }
                )
                assert "requestBody" not in operation
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{request_schema_name}"},
                        }
                    },
                }

                mode = "non-streaming" if action == "send" else "streaming"
                expected_description = (
                    f"{'Send' if action == 'send' else 'Stream'} a message to an Agno {label} "
                    f"({mode}). The {label} is identified via the path parameter '{{id}}'. Optional: "
                    "Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata."
                )
                if action == "stream":
                    expected_description += " Returns real-time updates as newline-delimited JSON (NDJSON)."
                assert operation["description"] == expected_description
                operation["description"] = (
                    f"{'Send' if action == 'send' else 'Stream'} a message to an Agno {label}. "
                    "Anonymous requests can set `X-User-ID` or `params.message.metadata.userId` for "
                    "attribution. Authenticated requests use the identity from the credential."
                )

                if action == "send":
                    success_json = operation["responses"]["200"]["content"]["application/json"]
                    assert "task" in success_json["example"]["result"]
                    success_json["example"] = deepcopy(success_example)
                    if family in ("agents", "teams"):
                        add_response(
                            operation,
                            "202",
                            "Message accepted for background execution when `blocking=false`",
                            "SendMessageSuccessResponse",
                        )
                    if family == "agents":
                        add_response(
                            operation,
                            "501",
                            "A2A is not supported for this agent type",
                            "NotImplementedResponse",
                        )
                else:
                    operation["description"] += " The response is a server-sent event stream."
                    success_content = operation["responses"]["200"]["content"]
                    assert success_content["application/json"]["schema"] == {}
                    assert "text/event-stream" in success_content
                    del success_content["application/json"]
                    success_content["text/event-stream"]["schema"] = {"type": "string"}
                    add_response(
                        operation,
                        "500",
                        "Run could not be started",
                        "InternalServerErrorResponse",
                    )
                sort_responses(operation)

        for action, request_schema_name in (
            ("send", "SendMessageRequest"),
            ("stream", "SendStreamingMessageRequest"),
        ):
            operation = spec["paths"][f"/a2a/message/{action}"]["post"]
            assert operation.get("deprecated") is None
            operation["deprecated"] = True
            assert operation.get("security") is None
            operation["security"] = [{"HTTPBearer": []}]
            assert "parameters" not in operation
            operation["parameters"] = [
                {
                    "name": "X-Agent-ID",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Target agent, team, or workflow ID when `params.message.agentId` is omitted.",
                },
                {
                    "name": "X-User-ID",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Optional user ID for anonymous attribution. Authenticated requests use the "
                        "identity from the credential."
                    ),
                },
            ]
            assert "requestBody" not in operation
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{request_schema_name}"},
                    }
                },
            }
            assert operation["responses"]["400"] == {
                "description": "Invalid request or unsupported method"
            }
            operation["responses"]["400"] = response_ref(
                "Invalid request or unsupported method",
                "BadRequestResponse",
            )
            assert operation["responses"]["404"] == {
                "description": "Agent, Team, or Workflow not found"
            }
            operation["responses"]["404"] = response_ref(
                "Agent, team, or workflow not found",
                "NotFoundResponse",
            )
            if action == "send":
                success_json = operation["responses"]["200"]["content"]["application/json"]
                assert "task" in success_json["example"]["result"]
                success_json["example"] = deepcopy(success_example)

        deprecated_stream = spec["paths"]["/a2a/message/stream"]["post"]
        deprecated_stream_content = deprecated_stream["responses"]["200"]["content"]
        assert deprecated_stream_content["application/json"]["schema"] == {}
        assert "text/event-stream" in deprecated_stream_content
        del deprecated_stream_content["application/json"]
        deprecated_stream_content["text/event-stream"]["schema"] = {"type": "string"}
        deprecated_stream_description = deprecated_stream["description"]
        assert "Returns real-time updates as newline-delimited JSON (NDJSON)." in deprecated_stream_description
        deprecated_stream["description"] = deprecated_stream_description.replace(
            "Returns real-time updates as newline-delimited JSON (NDJSON).",
            "Returns real-time updates as Server-Sent Events (SSE).",
        )
        add_response(
            deprecated_stream,
            "500",
            "Run could not be started",
            "InternalServerErrorResponse",
        )
        sort_responses(spec["paths"]["/a2a/message/send"]["post"])
        sort_responses(deprecated_stream)

    resume_paths = (
        "/agents/{agent_id}/runs/{run_id}/resume",
        "/teams/{team_id}/runs/{run_id}/resume",
        "/workflows/{workflow_id}/runs/{run_id}/resume",
    )
    for path in resume_paths:
        resume_content = spec["paths"][path]["post"]["responses"]["200"]["content"]
        assert resume_content["application/json"]["schema"] == {}
        assert "text/event-stream" in resume_content
        del resume_content["application/json"]
        resume_content["text/event-stream"]["schema"] = {"type": "string"}

    resume_team = spec["paths"]["/teams/{team_id}/runs/{run_id}/resume"]["post"]
    assert resume_team["responses"]["400"]["description"] == "Not supported for remote teams"
    resume_team["responses"]["400"]["description"] = (
        "Stream resumption is unavailable for remote and factory teams. "
        "Non-admin callers must provide `session_id`."
    )
    assert resume_team["responses"]["404"]["description"] == "Team not found"
    resume_team["responses"]["404"]["description"] = "Team or run not found"

    cancellation_session_description = (
        "Session ID used to verify run ownership. Required when the caller is user-scoped: "
        "service accounts, and non-admin JWT users when user isolation is enabled. Admin and "
        "otherwise unscoped callers can omit it."
    )
    cancellation_contracts = (
        (
            "/agents/{agent_id}/runs/{run_id}/cancel",
            "Agent",
            "Cancel a currently executing agent run. This will attempt to stop the agent's execution "
            "gracefully.\n\n**Note:** Cancellation may not be immediate for all operations.",
            "Agent not found",
            "Request cancellation for `run_id`. After any required ownership check, local and "
            "factory agents store cancellation intent keyed by run ID. For admins and otherwise "
            "unscoped callers, this also supports cancel-before-start for an unregistered ID. "
            "Cancellation is cooperative and may not be immediate. HTTP 200 does not confirm that "
            "an active run existed or that cancellation was delivered to a remote agent.",
        ),
        (
            "/teams/{team_id}/runs/{run_id}/cancel",
            "Team",
            "Cancel a currently executing team run. This will attempt to stop the team's execution "
            "gracefully.\n\n**Note:** Cancellation may not be immediate for all operations.",
            "Team not found",
            "Request cancellation for `run_id`. After any required ownership check, local and "
            "factory teams store cancellation intent keyed by run ID and mark known member runs for "
            "cancellation. For admins and otherwise unscoped callers, this also supports "
            "cancel-before-start for an unregistered ID. Cancellation is cooperative and may not "
            "be immediate. HTTP 200 does not confirm that an active run existed or that "
            "cancellation was delivered to a remote team.",
        ),
        (
            "/workflows/{workflow_id}/runs/{run_id}/cancel",
            "Workflow",
            "Cancel a currently executing workflow run, stopping all active steps and cleanup.\n"
            "**Note:** Complex workflows with multiple parallel steps may take time to fully cancel.",
            "Workflow or run not found",
            "Request cancellation for `run_id`. After any required ownership check, local and "
            "factory workflows store cancellation intent keyed by run ID and mark known agent or "
            "team executor runs for cancellation. For admins and otherwise unscoped callers, this "
            "also supports cancel-before-start for an unregistered ID. Cancellation is cooperative "
            "and may not be immediate. HTTP 200 does not confirm that an active run existed or that "
            "cancellation was delivered to a remote workflow.",
        ),
    )
    for path, component, source_description, source_not_found, description in cancellation_contracts:
        operation = spec["paths"][path]["post"]
        assert operation["description"] == source_description
        operation["description"] = description
        session_parameter = get_parameter(operation, "session_id")
        assert session_parameter["description"] == (
            "Session ID the run belongs to. Required for non-admin JWT users."
        )
        assert session_parameter["schema"]["description"] == session_parameter["description"]
        session_parameter["description"] = cancellation_session_description
        session_parameter["schema"]["description"] = cancellation_session_description
        responses = operation["responses"]
        assert responses["200"]["description"] == "Successful Response"
        responses["200"]["description"] = (
            "Cancellation request accepted. The empty response does not confirm run existence or "
            "remote delivery."
        )
        assert responses["400"]["description"] == "Bad Request"
        responses["400"]["description"] = "A user-scoped caller omitted session_id"
        assert responses["404"]["description"] == source_not_found
        responses["404"]["description"] = (
            f"{component} not found, or the run could not be verified in the caller's session."
        )

    delete_memory = spec["paths"]["/memories/{memory_id}"]["delete"]
    assert delete_memory["responses"]["404"]["description"] == "Memory not found"
    del delete_memory["responses"]["404"]

    resume_workflow = spec["paths"]["/workflows/{workflow_id}/runs/{run_id}/resume"]["post"]
    bad_request = resume_workflow["responses"]["400"]
    assert bad_request["description"] == "Not supported for remote workflows"
    bad_request["description"] = (
        "Stream resumption is unavailable for remote and factory workflows. "
        "Non-admin callers must provide `session_id`."
    )

    fork_response_schema = {
        "properties": {
            "session_id": {
                "type": "string",
                "title": "Session Id",
                "description": "ID of the new independent session.",
            },
            "forked_from_session_id": {
                "type": "string",
                "title": "Forked From Session Id",
                "description": "ID of the source session.",
            },
        },
        "type": "object",
        "required": ["session_id", "forked_from_session_id"],
        "title": "ForkSessionResponse",
    }
    for component in ("agents", "teams"):
        response_schema = spec["paths"][f"/{component}/{{{component[:-1]}_id}}/sessions/{{session_id}}/fork"]["post"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]
        assert response_schema == {}
        response_schema.update(deepcopy(fork_response_schema))

    for path_item in spec["paths"].values():
        for method in ("get", "post", "put", "patch", "delete", "head", "options", "trace"):
            operation = path_item.get(method)
            if not isinstance(operation, dict) or not operation.get("security"):
                continue
            if "401" not in operation["responses"]:
                add_response(operation, "401", "Unauthorized", "UnauthenticatedResponse")
            if "403" not in operation["responses"]:
                add_response(operation, "403", "Forbidden", "ForbiddenResponse")
            sort_responses(operation)

    spec["components"]["schemas"] = dict(sorted(schemas.items()))
    return spec


def preserve_curated_slack_metadata(spec: dict) -> dict:
    """Carry forward Slack request details read imperatively by the router."""
    old = yaml.safe_load(OLD_YAML.read_text())
    fields = {
        "/slack/events": ("description", "parameters"),
        "/slack/interactions": ("description", "parameters", "requestBody"),
    }
    for path, names in fields.items():
        if path not in spec["paths"]:
            NOTES.append(f"curated Slack metadata: skipped {path} (Slack interface excluded)")
            continue
        current_post = spec["paths"][path]["post"]
        curated_post = old["paths"][path]["post"]
        for name in names:
            assert name in curated_post, f"missing curated Slack {path} {name}"
            current_post[name] = curated_post[name]

    if "/slack/interactions" in spec["paths"]:
        from agno.os.interfaces.slack.ids import ACTION_CHECK_STATUS

        assert ACTION_CHECK_STATUS == "check_status"
        interactions = spec["paths"]["/slack/interactions"]["post"]
        interaction_parameter_names = [parameter["name"] for parameter in interactions["parameters"]]
        retry_parameter = {
            "name": "X-Slack-Retry-Num",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "Retry attempt number. Retried interactions return 200 without reprocessing.",
        }
        if "X-Slack-Retry-Num" not in interaction_parameter_names:
            assert interaction_parameter_names == ["X-Slack-Request-Timestamp", "X-Slack-Signature"]
            interactions["parameters"].append(retry_parameter)
        else:
            assert interaction_parameter_names == [
                "X-Slack-Request-Timestamp",
                "X-Slack-Signature",
                "X-Slack-Retry-Num",
            ]
            assert interactions["parameters"][-1] == retry_parameter
        old_actions = (
            "- `row_approve` - Approve a pending tool call\n"
            "- `row_reject` - Reject a pending tool call\n"
            "- `submit_pause` - Submit form data for a paused workflow"
        )
        new_actions = old_actions + (
            "\n- `check_status` - Check an admin approval and resume an approved run"
        )
        if "`check_status`" not in interactions["description"]:
            assert interactions["description"].count(old_actions) == 1
            interactions["description"] = interactions["description"].replace(old_actions, new_actions)
        else:
            assert interactions["description"].count("`check_status`") == 1
            assert new_actions in interactions["description"]
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
    spec = apply_runtime_description_enrichments(app.openapi())
    spec = preserve_curated_slack_metadata(spec)

    NEW_JSON.write_text(json.dumps(spec, separators=(",", ":")) + "\n")
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
