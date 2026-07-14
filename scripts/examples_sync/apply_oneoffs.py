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
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate as gen  # noqa: E402

ROOT = HERE.parents[1]
DOCS = ROOT / "examples"
GENERATED_DESCRIPTION_OVERRIDES = json.loads(
    (HERE / "description-overrides.json").read_text(encoding="utf-8")
)

CHECK = False
would_apply = 0


# Curated overview frontmatter that cannot be derived from a cookbook docstring.
# Keys are docs slugs so the same values can be used while --check simulates
# the changes without writing the pages first.
DESCRIPTION_OVERRIDES = {
    "examples/agent-os/client-a2a/overview": "A2AClient examples for messaging, streaming, errors, multi-turn runs, and Agno or Google ADK servers.",
    "examples/agent-os/interfaces/a2a/overview": "A2A interface examples for AgentOS: basic agents, teams, research, structured output, and multi-agent servers.",
    "examples/agent-os/dbs/overview": "Database backends for AgentOS agents, teams, workflows, and session storage.",
    "examples/agent-os/knowledge/overview": "Serve AgentOS agents over Excel, markdown, Agno docs, and PgVector knowledge bases.",
    "examples/agent-os/mcp-demo/overview": "Expose AgentOS agents and custom tools through MCP with OAuth, dynamic headers, and managed MCPTools lifespans.",
    "examples/agent-os/mcp-demo/dynamic-headers/overview": "Pass request-specific headers from AgentOS through MCPTools to an MCP server.",
    "examples/agent-os/middleware/overview": "AgentOS middleware examples for authentication, request context, rate limiting, and custom request handling.",
    "examples/agent-os/os-config/overview": "Configure AgentOS in Python or YAML, including manifests, memory, and interfaces.",
    "examples/agent-os/rbac/overview": "JWT-based AgentOS RBAC examples for symmetric and asymmetric keys, scope mapping, and user isolation.",
    "examples/agent-os/rbac/asymmetric/overview": "RS256 AgentOS RBAC examples for generated keys, custom scope mappings, and WorkOS-issued tokens.",
    "examples/agent-os/remote/overview": "Connect AgentOS to remote agents, teams, workflows, A2A endpoints, and gateway instances.",
    "examples/agent-os/skills/overview": "Load local skills into AgentOS agents and teams, including sample system-information scripts.",
    "examples/agent-os/tracing/dbs/overview": "Persist AgentOS traces to ClickHouse, MongoDB, PostgreSQL, and SQLite.",
    "examples/evals/overview": "Evaluate agents and teams for accuracy, model-judged quality, performance, reliability, and reusable suites.",
    "examples/models/aws/bedrock/overview": "Amazon Bedrock examples for basic runs, image and PDF input, structured output, and tool use.",
    "examples/models/aws/claude/overview": "Claude on AWS Bedrock examples for runs, storage, images, knowledge, structured output, tools, and adaptive thinking.",
    "examples/models/azure/ai-foundry/overview": "Azure AI Foundry examples for Claude, Cohere, Mistral, images, knowledge, structured output, storage, and tools.",
    "examples/models/azure/openai/overview": "Azure OpenAI examples for runs, storage, knowledge, structured output, and tools.",
    "examples/models/google/overview": "Google Gemini and Gemini Interactions examples for multimodal input, search, thinking, tools, and deep research.",
    "examples/models/google/gemini/overview": "Gemini examples for multimodal input, file search, grounding, knowledge, thinking, structured output, tools, and Vertex AI.",
    "examples/models/meta/llama/overview": "Meta Llama API examples for runs, images, knowledge, memory, metrics, storage, structured output, and tools.",
    "examples/models/meta/llama-openai/overview": "OpenAI-compatible Llama examples for runs, images, knowledge, memory, metrics, storage, structured output, and tools.",
    "examples/models/vertexai/claude/overview": "Claude on Vertex AI examples for runs, storage, multimodal input, knowledge, memory, caching, thinking, structured output, and tools.",
    "examples/models/aimlapi/overview": "AIML API examples for basic runs, multimodal input, memory, retries, structured output, and tool use.",
    "examples/models/anthropic/overview": "Claude examples for multimodal input, context management, caching, knowledge, memory, thinking, structured output, server tools, and skills.",
    "examples/models/groq/overview": "Groq examples for agents and teams, multimodal input, knowledge, reasoning, research, transcription, translation, structured output, and tools.",
    "examples/models/ibm/overview": "IBM watsonx examples for model retries, storage, knowledge, structured output, and tools.",
    "examples/models/ollama/overview": "Ollama Chat and Responses API examples for local and cloud models, knowledge, memory, reasoning, structured output, and tools.",
    "examples/models/openai/overview": "OpenAI Chat and Responses API examples for multimodal input, tools, reasoning, structured output, storage, and streaming.",
    "examples/models/openrouter/overview": "OpenRouter Chat and Responses API examples for model routing, retries, structured output, and tools.",
    "examples/models/vertexai/overview": "Vertex AI examples for Claude models, retries, multimodal input, knowledge, memory, caching, structured output, and tools.",
    "examples/teams/context-compression/overview": "Compress team tool results to keep long-running collaboration within model context limits.",
    "examples/teams/context-management/overview": "Control team context with instructions, messages, history filters, dates, and locations.",
    "examples/teams/dependencies/overview": "Pass runtime dependencies into teams, members, instructions, and tools.",
    "examples/teams/distributed-rag/overview": "Distribute RAG searches across team members with LanceDB, PgVector, and reranking.",
    "examples/teams/guardrails/overview": "Apply moderation, PII, and prompt-injection guardrails to team runs.",
    "examples/teams/hooks/overview": "Validate, transform, and observe team inputs, outputs, streams, and tool calls with hooks.",
    "examples/teams/human-in-the-loop/overview": "Pause and resume team runs for confirmation, user input, and external tool execution.",
    "examples/teams/knowledge/overview": "Give teams shared knowledge, filters, custom retrievers, and coordinated RAG search.",
    "examples/teams/learning/overview": "Capture user profiles, memories, entities, session context, knowledge, and decisions from team runs.",
    "examples/teams/memory/overview": "Persist and inject team memories with LearningMachine, MemoryManager, and agentic memory.",
    "examples/teams/multimodal/overview": "Process audio, images, video, and media-aware tools with teams.",
    "examples/teams/reasoning/overview": "Coordinate reasoning-enabled team members across research and decision tasks.",
    "examples/teams/run-control/overview": "Control team background execution, cancellation, retries, remote access, and model inheritance.",
    "examples/teams/search-coordination/overview": "Coordinate distributed and reasoning-guided RAG searches across team members.",
    "examples/teams/session/overview": "Persist team sessions, history, summaries, and shared agent interactions.",
    "examples/teams/state/overview": "Share state across team members and persist sessions, chat history, searches, and summaries.",
    "examples/teams/streaming/overview": "Stream team and member content, tool calls, and lifecycle events.",
    "examples/teams/structured-input-output/overview": "Validate team inputs and return typed, schema-constrained outputs in sync and streaming runs.",
    "examples/teams/task-mode/overview": "Advanced team examples for task mode, run control, context management, multimodal input, metrics, reasoning, and dependencies.",
    "examples/teams/tools/overview": "Configure team and member tools, tool hooks, tool choice, and call limits.",
    "examples/workflows/basic-workflows/overview": "Workflow examples for function executors, step sequences, nested steps, files, and session metrics.",
    "examples/workflows/conditional-execution/overview": "Condition workflow examples for branching on input, state, and previous-step output.",
    "examples/workflows/loop-execution/overview": "Loop workflows for iterative processing, parallel branches, and accumulated outputs.",
    "examples/workflows/parallel-execution/overview": "Parallel workflows for concurrent agents, teams, conditions, and synthesis steps.",
    "examples/workflows/conditional-branching/overview": "Router and conditional workflow examples for dynamic branch selection.",
    "examples/workflows/advanced-concepts/overview": "Advanced workflow examples for run control, state, history, nesting, guardrails, structured I/O, and background execution.",
    "examples/workflows/cel-expressions/overview": "Use CEL expressions in workflow conditions, loops, and routers.",
    "examples/workflows/overview": "Workflow examples covering steps, loops, parallel execution, routing, advanced controls, and CEL.",
    # Reviewed candidate exceptions.
    "examples/models/huggingface/overview": "Hugging Face examples for basic and streaming runs, essay generation, retries, and web-search tool use.",
    "examples/storage/in-memory/overview": "Store agent, team, and workflow sessions in memory with InMemoryDb.",
    "examples/models/deepseek/overview": "Run DeepSeek models with reasoning, thinking mode, structured output, retries, and tool use.",
    "examples/models/mistral/overview": "Run Mistral models with image input, memory, structured output, retries, and tool use.",
    "examples/models/ibm/watsonx/overview": "Run IBM watsonx models with basic responses, tools, knowledge, storage, retries, and structured output.",
    "examples/models/internlm/overview": "Run InternLM models with basic responses, tools, knowledge, storage, retries, and structured output.",
    "examples/models/langdb/overview": "Run LangDB models with basic responses, tools, retries, and structured output.",
    "examples/models/lmstudio/overview": "LM Studio examples for local models, images, knowledge, memory, storage, retries, structured output, and tools.",
    "examples/storage/dynamodb/overview": "Store agent and team sessions in DynamoDB.",
}

TITLE_OVERRIDES = {
    "examples/agent-os/rbac/asymmetric/workos-byot": "WorkOS BYOT",
    "examples/agents/tools/tools-with-literal-type-param": "Tools with Literal Type Parameters",
    "examples/models/vercel/tool-use": "Vercel v0 Tool Use",
    "examples/models/vllm/tool-use": "vLLM Tool Use",
    "examples/models/xai/finance-agent": "Finance Agent",
    "examples/teams/state/overview": "State & Session",
    "examples/teams/task-mode/overview": "Advanced",
}

SIDEBAR_TITLE_OVERRIDES = {
    "examples/workflows/advanced-concepts/nested-workflows/overview": "Nested Workflows",
}

# Missing rows accepted by the audit. Values are in docs.json order. These are
# deliberately exhaustive rather than inferred from directories.
EXPLICIT_MISSING_ROWS = {
    "examples/agent-os/advanced-demo/overview": ["examples/agent-os/advanced-demo/checkpointing"],
    "examples/agent-os/client/overview": [
        "examples/agent-os/client/sse-reconnect",
        "examples/agent-os/client/team-sse-reconnect",
        "examples/agent-os/client/continue-run-sse-reconnect",
        "examples/agent-os/client/workflow-sse-reconnect",
    ],
    "examples/agent-os/interfaces/agui/overview": [
        "examples/agent-os/interfaces/agui/agent-with-media",
        "examples/agent-os/interfaces/agui/agentic-chat",
        "examples/agent-os/interfaces/agui/backend-tool-rendering",
        "examples/agent-os/interfaces/agui/human-in-the-loop",
        "examples/agent-os/interfaces/agui/shared-state",
        "examples/agent-os/interfaces/agui/showcase",
        "examples/agent-os/interfaces/agui/state-events",
        "examples/agent-os/interfaces/agui/team-state-events",
        "examples/agent-os/interfaces/agui/tool-based-generative-ui",
    ],
    "examples/agent-os/interfaces/slack/overview": [
        "examples/agent-os/interfaces/slack/hitl-audit-flow",
        "examples/agent-os/interfaces/slack/hitl-confirmation",
        "examples/agent-os/interfaces/slack/hitl-external-execution",
        "examples/agent-os/interfaces/slack/hitl-incident-commander",
        "examples/agent-os/interfaces/slack/hitl-required-approval",
        "examples/agent-os/interfaces/slack/hitl-simple",
        "examples/agent-os/interfaces/slack/hitl-user-feedback",
        "examples/agent-os/interfaces/slack/hitl-user-input",
        "examples/agent-os/interfaces/slack/multi-bot",
        "examples/agent-os/interfaces/slack/multimodal-team",
        "examples/agent-os/interfaces/slack/multimodal-workflow",
        "examples/agent-os/interfaces/slack/streaming-deep-research",
        "examples/agent-os/interfaces/slack/team-hitl-confirmation",
        "examples/agent-os/interfaces/slack/team-hitl-external-execution-simple",
        "examples/agent-os/interfaces/slack/team-hitl-team-tool-simple",
        "examples/agent-os/interfaces/slack/team-hitl-user-input-simple",
    ],
    "examples/agent-os/interfaces/whatsapp/overview": [
        "examples/agent-os/interfaces/whatsapp/deep-research",
        "examples/agent-os/interfaces/whatsapp/interactive-concierge",
        "examples/agent-os/interfaces/whatsapp/multimodal-team",
        "examples/agent-os/interfaces/whatsapp/multimodal-workflow",
        "examples/agent-os/interfaces/whatsapp/support-team",
        "examples/agent-os/interfaces/whatsapp/tourist-guide",
        "examples/agent-os/interfaces/whatsapp/video-generation",
    ],
    "examples/agent-os/knowledge/overview": ["examples/agent-os/knowledge/agentos-docling-markdown-analyst"],
    "examples/agent-os/mcp-demo/overview": [
        "examples/agent-os/mcp-demo/custom-mcp-tool-example",
        "examples/agent-os/mcp-demo/oauth-authkit-example",
        "examples/agent-os/mcp-demo/oauth-builtin-example",
    ],
    "examples/agent-os/overview": [
        "examples/agent-os/factories/overview",
        "examples/agent-os/agno-assist",
        "examples/agent-os/antigravity/basic",
        "examples/agent-os/approvals/agent/approval-basic",
        "examples/agent-os/factories/agent/basic-factory",
        "examples/agent-os/file-generation/file-generation-os",
        "examples/agent-os/followup/followups-agentos",
        "examples/agent-os/google/gemini-3/data-labeling",
        "examples/agent-os/human-in-the-loop/agent/agent-tool-requires-confirmation",
        "examples/agent-os/learnings/learnings-with-agentos",
        "examples/agent-os/studio-tool/standalone-studio-agent",
        "examples/agent-os/team-tasks/team-tasks-streaming",
    ],
    "examples/agent-os/interfaces/overview": ["examples/agent-os/interfaces/telegram/basic"],
    "examples/agent-os/rbac/overview": ["examples/agent-os/rbac/test-scopes"],
    "examples/agent-os/rbac/asymmetric/overview": ["examples/agent-os/rbac/asymmetric/workos-byot"],
    "examples/agent-os/rbac/symmetric/overview": ["examples/agent-os/rbac/symmetric/user-isolation"],
    "examples/agent-os/remote/overview": [
        "examples/agent-os/remote/remote-agent-as-team-member",
        "examples/agent-os/remote/a2a-agent-as-team-member",
    ],
    "examples/agent-os/scheduler/overview": ["examples/agent-os/scheduler/scheduler-tools-agent"],
    "examples/agent-os/tracing/overview": ["examples/agent-os/tracing/advanced-trace-filtering"],
    "examples/agent-os/tracing/dbs/overview": [
        "examples/agent-os/tracing/dbs/basic-agent-with-clickhousedb"
    ],
    "examples/agent-os/workflow/overview": ["examples/agent-os/workflow/workflow-with-workflow-as-step"],
    "examples/agents/advanced/overview": [
        "examples/agents/advanced/sse-reconnect",
        "examples/agents/advanced/agent-run-cancel-persistence",
        "examples/agents/advanced/combined-metrics",
        "examples/agents/advanced/interchange-model/all-providers",
        "examples/agents/advanced/interchange-model/claude-gemini",
        "examples/agents/advanced/interchange-model/openai-chat-responses",
        "examples/agents/advanced/interchange-model/openai-claude",
        "examples/agents/advanced/interchange-model/openai-gemini",
        "examples/agents/advanced/metrics",
    ],
    "examples/agents/guardrails/overview": ["examples/agents/guardrails/mixed-hooks"],
    "examples/agents/hooks/overview": [
        "examples/agents/context-management/datetime-format",
        "examples/agents/hooks/message-history-hooks",
    ],
    "examples/agents/human-in-the-loop/overview": [
        "examples/agents/human-in-the-loop/confirmation-with-session-state",
        "examples/agents/human-in-the-loop/mixed-external-and-regular-tools",
        "examples/agents/human-in-the-loop/user-feedback",
        "examples/agents/approvals/approval-post-hook",
        "examples/agent-os/approvals/team/member-agent-level-approval",
        "examples/agent-os/approvals/team/team-and-member-agent-both-level-approval",
    ],
    "examples/agents/input-output/overview": [
        "examples/agents/input-output/followup-suggestions",
        "examples/agents/input-output/followup-suggestions-streaming",
    ],
    "examples/agents/state-and-session/overview": ["examples/agents/state-and-session/search-session-history"],
    "examples/agents/tools/overview": ["examples/agents/tools/tools-with-literal-type-param"],
    "examples/components/overview": [
        "examples/components/auto-populate-registry",
        "examples/components/auto-populate-registry-os",
    ],
    "examples/components/workflows/overview": [
        "examples/components/workflows/registry-agents-in-workflow",
        "examples/components/workflows/save-hitl-condition-loop-router",
        "examples/components/workflows/save-hitl-confirmation-steps",
        "examples/components/workflows/save-hitl-user-input-steps",
    ],
    "examples/evals/overview": ["examples/evals/suite/suite-basic"],
    "examples/integrations/memory/overview": ["examples/memory/integrations/dakera-integration"],
    "examples/learning/patterns/overview": ["examples/learning/patterns/research-assistant"],
    "examples/models/azure/overview": ["examples/models/azure/claude/basic"],
    "examples/models/google/overview": ["examples/models/google/gemini-interactions/basic"],
    "examples/models/ibm/watsonx/overview": ["examples/models/ibm/retry"],
    "examples/models/litellm/overview": ["examples/models/litellm/append-trailing-user-message"],
    "examples/models/openai/responses/overview": [
        "examples/models/openai/responses/background",
        "examples/models/openai/responses/file-input-direct",
        "examples/models/openai/responses/image-agent-file",
    ],
    "examples/models/overview": [
        "examples/models/cloudflare/overview",
        "examples/models/inception/overview",
        "examples/models/minimax/overview",
        "examples/models/xiaomi/overview",
    ],
    "examples/storage/overview": ["examples/storage/session-summary-limits"],
    "examples/teams/human-in-the-loop/overview": ["examples/teams/human-in-the-loop/confirmation-required-with-dependencies"],
    "examples/teams/knowledge/overview": ["examples/teams/knowledge/team-update-knowledge"],
    "examples/teams/learning/overview": [
        "examples/teams/memory/memories-in-context",
        "examples/teams/learning/team-user-profile",
        "examples/teams/learning/team-user-memory",
        "examples/teams/learning/team-async-learning",
        "examples/teams/learning/team-agentic-learning",
    ],
    "examples/teams/modes/tasks/overview": [
        "examples/teams/modes/tasks-stream",
        "examples/teams/modes/tasks/streaming-events",
    ],
    "examples/teams/state/overview": ["examples/teams/session/custom-session-summary"],
    "examples/teams/structured-input-output/overview": ["examples/teams/structured-input-output/expected-output"],
    "examples/teams/tools/overview": [
        "examples/teams/tools/async-toolkit-context",
        "examples/teams/tools/member-information",
        "examples/teams/tools/message-history-in-tool-hooks",
        "examples/teams/tools/tool-call-limit",
        "examples/teams/tools/tool-choice",
    ],
    "examples/tools/mcp/overview": ["examples/tools/mcp/bgpt"],
    "examples/tools/tool-decorator/overview": ["examples/tools/tool-decorator/toolkit-per-tool-instructions"],
    "examples/tools/tool-hooks/overview": ["examples/tools/tool-hooks/message-history-in-hooks"],
}

# Reviewed row copy that cannot be derived from the linked page alone. This
# covers subgroup links without an overview page and factual corrections to
# existing rows.
EXPLICIT_ROW_OVERRIDES = {
    "examples/models/google/overview": {
        "examples/models/google/gemini-interactions/basic": (
            "Gemini Interactions",
            "Gemini Interactions API examples for server-side history, multimodal input, tools, Deep Research, and Antigravity.",
        ),
    },
    "examples/models/azure/overview": {
        "examples/models/azure/claude/basic": (
            "Claude",
            "Claude on Azure AI Foundry examples for basic runs, extended thinking, and web search tool use.",
        ),
    },
    "examples/agent-os/overview": {
        "examples/agent-os/factories/overview": (
            "Dynamic Agents",
            "Build request-scoped agents with AgentFactory, input schemas, JWT claims, and HITL tools.",
        ),
        "examples/agent-os/antigravity/basic": (
            "Antigravity",
            "Serve an Antigravity-backed agent through AgentOS with SQLite-backed sessions.",
        ),
        "examples/agent-os/approvals/agent/approval-basic": (
            "Approvals",
            "Persist approval-backed HITL decisions for AgentOS tool calls.",
        ),
        "examples/agent-os/factories/agent/basic-factory": (
            "Factories",
            "Construct request-scoped agents, teams, and workflows from tenant context and factory input.",
        ),
        "examples/agent-os/file-generation/file-generation-os": (
            "File Generation",
            "Generate downloadable JSON, CSV, PDF, DOCX, TXT, and HTML artifacts through AgentOS.",
        ),
        "examples/agent-os/followup/followups-agentos": (
            "Followup",
            "Enable built-in followup suggestions on agents and teams served through AgentOS.",
        ),
        "examples/agent-os/google/gemini-3/data-labeling": (
            "Google",
            "Run Gemini 3 video data labeling through AgentOS with structured output.",
        ),
        "examples/agent-os/human-in-the-loop/agent/agent-tool-requires-confirmation": (
            "Human in the Loop",
            "Pause and resume AgentOS runs for confirmations, user input, and external execution.",
        ),
        "examples/agent-os/learnings/learnings-with-agentos": (
            "Learnings",
            "Serve a learning-enabled agent and manage learned data through AgentOS REST endpoints.",
        ),
        "examples/agent-os/studio-tool/standalone-studio-agent": (
            "Studio Tool",
            "Build, edit, version, and run agents with StudioTools backed by SQLite.",
        ),
        "examples/agent-os/team-tasks/team-tasks-streaming": (
            "Team Tasks",
            "Stream task-mode team runs through AgentOS.",
        ),
    },
    "examples/agent-os/interfaces/overview": {
        "examples/agent-os/interfaces/telegram/basic": (
            "Telegram",
            "Serve chat, media, memory, reasoning, streaming, team, and workflow agents through Telegram.",
        ),
    },
    "examples/agent-os/rbac/overview": {
        "examples/agent-os/rbac/test-scopes": (
            "Test Scopes",
            "Test JWT scope enforcement against AgentOS agent, workflow, and component endpoints.",
        ),
    },
    "examples/agent-os/rbac/asymmetric/overview": {
        "examples/agent-os/rbac/asymmetric/workos-byot": (
            "WorkOS BYOT",
            "Validate WorkOS-issued RS256 tokens and provision three AgentOS RBAC roles through the API.",
        ),
    },
    "examples/evals/overview": {
        "examples/evals/suite/suite-basic": (
            "Suite",
            "Declare reusable eval cases and run them together with the built-in suite CLI.",
        ),
    },
    "examples/agent-os/mcp-demo/overview": {
        "examples/agent-os/mcp-demo/oauth-authkit-example": (
            "OAuth with WorkOS AuthKit",
            "Bring a FastMCP AuthProvider backed by WorkOS AuthKit to the AgentOS MCP endpoint.",
        ),
        "examples/agent-os/mcp-demo/oauth-builtin-example": (
            "Built-in OAuth",
            "Use the AgentOS built-in authorization server to protect the MCP endpoint.",
        ),
    },
    "examples/agent-os/rbac/symmetric/overview": {
        "examples/agent-os/rbac/symmetric/advanced-scopes": (
            "Advanced Scopes",
            "Issue HS256 tokens across five privilege tiers to test global, per-agent, and wildcard scopes.",
        ),
    },
    "examples/agent-os/remote/overview": {
        "examples/agent-os/remote/remote-agent": (
            "Remote Agent",
            "Call an agent hosted on another AgentOS with RemoteAgent in single-shot or streaming mode.",
        ),
        "examples/agent-os/remote/remote-team": (
            "Remote Team",
            "Run a team hosted on another AgentOS with RemoteTeam in single-shot or streaming mode.",
        ),
    },
}

# These pages have a reviewed, factual mismatch that is grammatical enough not
# to be caught by the fail-closed malformed-row detector.
EXPLICIT_ROW_REFRESH = {
    "examples/agent-os/advanced-demo/overview": {
        "examples/agent-os/advanced-demo/demo",
        "examples/agent-os/advanced-demo/reasoning-demo",
        "examples/agent-os/advanced-demo/reasoning-model",
    },
    "examples/agent-os/client-a2a/servers/overview": {
        "examples/agent-os/client-a2a/servers/agno-server",
        "examples/agent-os/client-a2a/servers/google-adk-server",
    },
    "examples/agent-os/customize/overview": {"examples/agent-os/customize/custom-fastapi-app"},
    "examples/agent-os/mcp-demo/overview": {
        "examples/agent-os/mcp-demo/mcp-tools-advanced-example",
        "examples/agent-os/mcp-demo/mcp-tools-existing-lifespan",
        "examples/agent-os/mcp-demo/oauth-authkit-example",
        "examples/agent-os/mcp-demo/oauth-builtin-example",
    },
    "examples/agent-os/mcp-demo/dynamic-headers/overview": {
        "examples/agent-os/mcp-demo/dynamic-headers/client",
        "examples/agent-os/mcp-demo/dynamic-headers/server",
    },
    "examples/agent-os/overview": {
        "examples/agent-os/basic",
        "examples/agent-os/demo",
        "examples/agent-os/rbac/overview",
    },
    "examples/agent-os/background-tasks/overview": {
        "examples/agent-os/background-tasks/background-hooks-decorator",
        "examples/agent-os/background-tasks/background-hooks-example",
        "examples/agent-os/background-tasks/background-hooks-team",
        "examples/agent-os/background-tasks/background-hooks-workflow",
        "examples/agent-os/background-tasks/evals-demo",
    },
    "examples/agent-os/interfaces/slack/overview": {
        "examples/agent-os/interfaces/slack/basic",
        "examples/agent-os/interfaces/slack/multiple-instances",
    },
    "examples/agent-os/interfaces/whatsapp/overview": {
        "examples/agent-os/interfaces/whatsapp/multiple-instances",
    },
    "examples/agent-os/knowledge/overview": {"examples/agent-os/knowledge/agentos-knowledge"},
    "examples/agent-os/rbac/overview": {
        "examples/agent-os/rbac/asymmetric/overview",
        "examples/agent-os/rbac/symmetric/overview",
    },
    "examples/agent-os/rbac/asymmetric/overview": {
        "examples/agent-os/rbac/asymmetric/basic",
        "examples/agent-os/rbac/asymmetric/custom-scope-mappings",
    },
    "examples/agent-os/rbac/symmetric/overview": {
        "examples/agent-os/rbac/symmetric/advanced-scopes",
    },
    "examples/agent-os/remote/overview": {
        "examples/agent-os/remote/remote-agent",
        "examples/agent-os/remote/remote-team",
    },
    "examples/agent-os/scheduler/overview": {
        "examples/agent-os/scheduler/rest-api-schedules",
        "examples/agent-os/scheduler/scheduler-with-agentos",
        "examples/agent-os/scheduler/scheduler-tools-agent",
    },
    "examples/agent-os/schemas/overview": {
        "examples/agent-os/schemas/agent-schemas",
        "examples/agent-os/schemas/team-schemas",
    },
    "examples/agent-os/tracing/overview": {
        "examples/agent-os/tracing/basic-team-tracing",
        "examples/agent-os/tracing/agent-with-knowledge-tracing",
        "examples/agent-os/tracing/agent-with-reasoning-tools-tracing",
        "examples/agent-os/tracing/tracing-with-multi-db-and-tracing-flag",
    },
    "examples/agent-os/tracing/dbs/overview": {
        "examples/agent-os/tracing/dbs/basic-agent-with-mongodb",
        "examples/agent-os/tracing/dbs/basic-agent-with-postgresdb",
        "examples/agent-os/tracing/dbs/basic-agent-with-sqlite",
    },
    "examples/integrations/rag/overview": {
        "examples/knowledge/integrations/rag/agentic-rag-infinity-reranker",
        "examples/knowledge/integrations/rag/agentic-rag-with-lightrag",
        "examples/knowledge/integrations/rag/local-rag-langchain-qdrant",
    },
    "examples/agents/guardrails/overview": {
        "examples/agents/guardrails/custom-guardrail",
        "examples/agents/guardrails/openai-moderation",
        "examples/agents/guardrails/output-guardrail",
        "examples/agents/guardrails/pii-detection",
        "examples/agents/guardrails/prompt-injection",
    },
    "examples/agents/human-in-the-loop/overview": {
        "examples/agents/human-in-the-loop/agentic-user-input",
        "examples/agents/human-in-the-loop/confirmation-advanced",
        "examples/agents/human-in-the-loop/confirmation-required-mcp-toolkit",
        "examples/agents/human-in-the-loop/confirmation-toolkit",
        "examples/agents/human-in-the-loop/external-tool-execution",
        "examples/agents/human-in-the-loop/user-input-required",
        "examples/agents/approvals/approval-team",
        "examples/agents/approvals/audit-approval-overview",
    },
    "examples/agents/input-output/overview": {"examples/agents/input-output/parser-model"},
    "examples/agents/hooks/overview": {
        "examples/agents/context-management/filter-tool-calls-from-history",
        "examples/agents/context-management/instructions",
    },
    "examples/agents/multimodal/overview": {"examples/agents/multimodal/audio-streaming"},
    "examples/agents/state-and-session/overview": {
        "examples/agents/state-and-session/agentic-session-state",
        "examples/agents/state-and-session/chat-history",
        "examples/agents/state-and-session/dynamic-session-state",
        "examples/agents/state-and-session/last-n-session-messages",
        "examples/agents/state-and-session/session-state-advanced",
        "examples/agents/state-and-session/session-state-basic",
        "examples/agents/state-and-session/session-state-events",
        "examples/agents/state-and-session/session-state-manual-update",
    },
    "examples/agents/tools/overview": {
        "examples/agents/tools/callable-tools",
        "examples/agents/tools/session-state-tools",
        "examples/agents/tools/team-callable-members",
        "examples/agents/tools/tool-call-limit",
        "examples/agents/tools/tool-choice",
        "examples/agents/dependencies/dependencies-in-context",
        "examples/agents/dependencies/dynamic-tools",
    },
    "examples/integrations/surrealdb/overview": {
        "examples/integrations/surrealdb/standalone-memory-surreal",
        "examples/integrations/surrealdb/memory-creation",
        "examples/integrations/surrealdb/custom-memory-instructions",
        "examples/integrations/surrealdb/memory-search-surreal",
        "examples/integrations/surrealdb/db-tools-control",
    },
    "examples/learning/basics/overview": {
        "examples/learning/basics/a-user-profile-always",
        "examples/learning/basics/b-user-profile-agentic",
        "examples/learning/basics/a-entity-memory-always",
        "examples/learning/basics/b-entity-memory-agentic",
    },
    "examples/memory/overview": {
        "examples/memory/multi-user-multi-session-chat-concurrent",
    },
    "examples/models/overview": {
        "examples/models/cometapi/overview",
        "examples/models/llama-cpp/overview",
        "examples/models/lmstudio/overview",
    },
    "examples/models/cerebras/overview": {"examples/models/cerebras/db"},
    "examples/models/cohere/overview": {
        "examples/models/cohere/db",
        "examples/models/cohere/tool-use",
    },
    "examples/models/deepseek/overview": {"examples/models/deepseek/tool-use"},
    "examples/models/groq/reasoning/overview": {
        "examples/models/groq/reasoning/demo-deepseek-qwen",
    },
    "examples/models/ibm/watsonx/overview": {
        "examples/models/ibm/watsonx/db",
        "examples/models/ibm/watsonx/tool-use",
    },
    "examples/models/lmstudio/overview": {
        "examples/models/lmstudio/db",
        "examples/models/lmstudio/tool-use",
    },
    "examples/models/mistral/overview": {
        "examples/models/mistral/mistral-small",
        "examples/models/mistral/tool-use",
    },
    "examples/models/nvidia/overview": {"examples/models/nvidia/tool-use"},
    "examples/models/ollama/responses/overview": {
        "examples/models/ollama/responses/basic",
        "examples/models/ollama/responses/structured-output",
    },
    "examples/models/openai/responses/overview": {
        "examples/models/openai/responses/db",
        "examples/models/openai/responses/image-generation-agent",
        "examples/models/openai/responses/tool-use",
        "examples/models/openai/responses/zdr-reasoning-agent",
    },
    "examples/models/together/overview": {"examples/models/together/tool-use"},
    "examples/models/vllm/overview": {
        "examples/models/vllm/code-generation",
        "examples/models/vllm/db",
    },
    "examples/storage/dynamodb/overview": {
        "examples/storage/dynamodb/dynamo-for-agent",
        "examples/storage/dynamodb/dynamo-for-team",
    },
    "examples/storage/overview": {
        "examples/storage/mongo/overview",
        "examples/storage/dynamodb/overview",
    },
    "examples/tools/overview": {"examples/tools/searchapi-tools"},
    "examples/teams/basics/overview": {"examples/teams/basics/basic-coordination"},
    "examples/teams/learning/overview": {"examples/teams/learning/team-learned-knowledge"},
    "examples/teams/modes/tasks/overview": {
        "examples/teams/modes/tasks/basic",
        "examples/teams/modes/tasks/dependencies",
        "examples/teams/modes/tasks/parallel",
    },
    "examples/teams/overview": {
        "examples/teams/basics/overview",
        "examples/teams/learning/overview",
    },
    "examples/teams/task-mode/overview": {
        "examples/teams/task-mode/basic-task-mode",
        "examples/teams/task-mode/parallel-tasks",
        "examples/teams/task-mode/task-mode-with-tools",
        "examples/teams/task-mode/multi-run-session",
        "examples/teams/task-mode/dependency-chain",
    },
}

EXPLICIT_LABEL_REFRESH = {
    "examples/agent-os/advanced-demo/reasoning-model",
    "examples/agent-os/client-a2a/servers/agno-server",
    "examples/agent-os/client-a2a/servers/google-adk-server",
    "examples/agent-os/interfaces/slack/basic",
    "examples/agent-os/interfaces/slack/multiple-instances",
    "examples/agent-os/interfaces/whatsapp/multiple-instances",
    "examples/agent-os/scheduler/async-schedule",
    "examples/agent-os/scheduler/demo",
    "examples/agent-os/scheduler/rest-api-schedules",
    "examples/agent-os/scheduler/scheduler-with-agentos",
    "examples/agent-os/scheduler/scheduler-tools-agent",
    "examples/agent-os/schemas/agent-schemas",
    "examples/agent-os/schemas/team-schemas",
    "examples/agent-os/tracing/basic-team-tracing",
    "examples/agent-os/tracing/dbs/basic-agent-with-clickhousedb",
    "examples/agent-os/tracing/dbs/basic-agent-with-mongodb",
    "examples/agent-os/tracing/dbs/basic-agent-with-postgresdb",
    "examples/agent-os/tracing/dbs/basic-agent-with-sqlite",
    "examples/agent-os/tracing/agent-with-knowledge-tracing",
    "examples/agent-os/tracing/agent-with-reasoning-tools-tracing",
    "examples/agent-os/tracing/tracing-with-multi-db-and-tracing-flag",
    "examples/agent-os/advanced-demo/reasoning-model",
    "examples/agent-os/mcp-demo/mcp-server-example",
    "examples/agent-os/rbac/symmetric/basic",
    "examples/agent-os/tracing/basic-agent-tracing",
    "examples/agent-os/tracing/basic-workflow-tracing",
    "examples/agent-os/tracing/tracing-with-multi-db-scenario",
    "examples/models/litellm-openai/audio-input",
    "examples/storage/dynamodb/dynamo-for-agent",
    "examples/storage/dynamodb/dynamo-for-team",
    "examples/models/vercel/tool-use",
    "examples/models/vllm/tool-use",
    "examples/tools/bitbucket-tools",
    "examples/tools/desi-vocal-tools",
    "examples/tools/elevenlabs-tools",
    "examples/tools/reddit-tools",
    "examples/tools/slack-tools",
}

# These two tables were explicitly reviewed as ordered subsets rather than
# append-only indexes. Rebuild only their row order, using current target
# frontmatter for the rows that the audit marked stale or missing.
EXPLICIT_TABLE_ORDER = {
    "examples/teams/modes/tasks/overview": [
        "examples/teams/modes/tasks/basic",
        "examples/teams/modes/tasks/dependencies",
        "examples/teams/modes/tasks/parallel",
        "examples/teams/modes/tasks-stream",
        "examples/teams/modes/tasks/streaming-events",
    ],
    "examples/teams/tools/overview": [
        "examples/teams/hooks/post-hook-output",
        "examples/teams/hooks/pre-hook-input",
        "examples/teams/hooks/stream-hook",
        "examples/teams/tools/async-tools",
        "examples/teams/tools/custom-tools",
        "examples/teams/tools/member-tool-hooks",
        "examples/teams/tools/tool-hooks",
        "examples/teams/tools/async-toolkit-context",
        "examples/teams/tools/member-information",
        "examples/teams/tools/message-history-in-tool-hooks",
        "examples/teams/tools/tool-call-limit",
        "examples/teams/tools/tool-choice",
    ],
}

# Shipped legacy routes whose examples now have one canonical docs location.
# Rewrite table targets before row refresh so --check validates the same state
# that the write pass would produce.
ROW_TARGET_REWRITES = {
    "examples/integrations/rag/overview": {
        "examples/integrations/rag/agentic-rag-infinity-reranker": "examples/knowledge/integrations/rag/agentic-rag-infinity-reranker",
        "examples/integrations/rag/agentic-rag-with-lightrag": "examples/knowledge/integrations/rag/agentic-rag-with-lightrag",
        "examples/integrations/rag/local-rag-langchain-qdrant": "examples/knowledge/integrations/rag/local-rag-langchain-qdrant",
    },
}

# Overview tables whose reported defects were confirmed. Restricting the pass
# to this allowlist prevents generic-looking but intentionally contextual rows
# elsewhere from being synchronized by accident.
ROW_REPAIR_OVERVIEWS = {
    "examples/agent-os/advanced-demo/overview",
    "examples/agent-os/background-tasks/overview",
    "examples/agent-os/client-a2a/servers/overview",
    "examples/agent-os/client/overview",
    "examples/agent-os/customize/overview",
    "examples/agent-os/dbs/surreal-db/overview",
    "examples/agent-os/integrations/overview",
    "examples/agent-os/interfaces/a2a/multi-agent-a2a/overview",
    "examples/agent-os/interfaces/a2a/overview",
    "examples/agent-os/interfaces/agui/overview",
    "examples/agent-os/interfaces/overview",
    "examples/agent-os/interfaces/slack/overview",
    "examples/agent-os/interfaces/whatsapp/overview",
    "examples/agent-os/knowledge/overview",
    "examples/agent-os/mcp-demo/overview",
    "examples/agent-os/mcp-demo/dynamic-headers/overview",
    "examples/agent-os/os-config/overview",
    "examples/agent-os/overview",
    "examples/agent-os/rbac/symmetric/overview",
    "examples/agent-os/rbac/asymmetric/overview",
    "examples/agent-os/rbac/overview",
    "examples/agent-os/remote/overview",
    "examples/agent-os/scheduler/overview",
    "examples/agent-os/tracing/overview",
    "examples/agent-os/tracing/dbs/overview",
    "examples/agent-os/schemas/overview",
    "examples/agent-os/workflow/overview",
    "examples/agents/advanced/overview",
    "examples/agents/guardrails/overview",
    "examples/agents/hooks/overview",
    "examples/agents/human-in-the-loop/overview",
    "examples/agents/input-output/overview",
    "examples/agents/knowledge/overview",
    "examples/agents/multimodal/overview",
    "examples/agents/overview",
    "examples/agents/state-and-session/overview",
    "examples/agents/tools/overview",
    "examples/components/overview",
    "examples/components/workflows/overview",
    "examples/evals/accuracy/overview",
    "examples/evals/overview",
    "examples/integrations/memory/overview",
    "examples/integrations/rag/overview",
    "examples/integrations/surrealdb/overview",
    "examples/learning/basics/overview",
    "examples/learning/patterns/overview",
    "examples/models/aws/overview",
    "examples/models/azure/overview",
    "examples/models/cerebras-openai/overview",
    "examples/models/cerebras/overview",
    "examples/models/cohere/overview",
    "examples/models/cometapi/overview",
    "examples/models/dashscope/overview",
    "examples/models/deepinfra/overview",
    "examples/models/deepseek/overview",
    "examples/models/google/overview",
    "examples/models/groq/reasoning/overview",
    "examples/models/huggingface/overview",
    "examples/models/ibm/watsonx/overview",
    "examples/models/litellm-openai/overview",
    "examples/models/litellm/overview",
    "examples/models/llama-cpp/overview",
    "examples/models/lmstudio/overview",
    "examples/models/meta/overview",
    "examples/models/minimax/overview",
    "examples/models/mistral/overview",
    "examples/models/moonshot/overview",
    "examples/models/n1n/overview",
    "examples/models/nebius/overview",
    "examples/models/neosantara/overview",
    "examples/models/nexus/overview",
    "examples/models/nvidia/overview",
    "examples/models/ollama/responses/overview",
    "examples/models/openai/responses/overview",
    "examples/models/openrouter/chat/overview",
    "examples/models/overview",
    "examples/models/perplexity/overview",
    "examples/models/portkey/overview",
    "examples/models/requesty/overview",
    "examples/models/sambanova/overview",
    "examples/models/siliconflow/overview",
    "examples/models/together/overview",
    "examples/models/vercel/overview",
    "examples/models/vertexai/overview",
    "examples/models/vllm/overview",
    "examples/models/xai/overview",
    "examples/models/xiaomi/overview",
    "examples/reasoning/agents/overview",
    "examples/reasoning/models/xai/overview",
    "examples/reasoning/teams/overview",
    "examples/reasoning/tools/overview",
    "examples/storage/examples/overview",
    "examples/storage/firestore/overview",
    "examples/storage/in-memory/overview",
    "examples/storage/mongo/overview",
    "examples/storage/postgres/overview",
    "examples/storage/redis/overview",
    "examples/storage/singlestore/overview",
    "examples/storage/sqlite/overview",
    "examples/storage/surrealdb/overview",
    "examples/teams/basics/overview",
    "examples/teams/human-in-the-loop/overview",
    "examples/teams/learning/overview",
    "examples/teams/modes/tasks/overview",
    "examples/teams/overview",
    "examples/teams/state/overview",
    "examples/teams/structured-input-output/overview",
    "examples/teams/task-mode/overview",
    "examples/teams/tools/overview",
    "examples/tools/mcp/local-server/overview",
    "examples/tools/mcp/overview",
    "examples/tools/mcp/sse-transport/overview",
    "examples/tools/mcp/streamable-http-transport/overview",
    "examples/tools/overview",
    "examples/tools/tool-decorator/overview",
    "examples/tools/tool-hooks/overview",
    "examples/workflows/overview",
}


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


def docs_path(slug: str) -> Path:
    assert slug.startswith("examples/"), f"not an example slug: {slug}"
    return ROOT / f"{slug}.mdx"


def frontmatter_value(text: str, field: str, slug: str) -> str:
    matches = re.findall(rf"^{re.escape(field)}:\s*(.+)$", text, re.M)
    assert len(matches) == 1, f"{slug}: expected one single-line {field}, found {len(matches)}"
    value = matches[0].strip()
    if value.startswith('"'):
        assert value.endswith('"') and len(value) >= 2, f"{slug}: malformed quoted {field}"
        return value[1:-1]
    return value


def desired_frontmatter(slug: str) -> tuple[str, str]:
    p = docs_path(slug)
    assert p.is_file(), f"missing target page: {slug}"
    text = p.read_text(encoding="utf-8")
    title = TITLE_OVERRIDES.get(slug, gen.fix_title_casing(frontmatter_value(text, "title", slug)))
    description = DESCRIPTION_OVERRIDES.get(
        slug,
        GENERATED_DESCRIPTION_OVERRIDES.get(slug, frontmatter_value(text, "description", slug)),
    )
    return title, description


def desired_row(overview: str, target: str) -> tuple[str, str, bool]:
    """Return the reviewed row label/description and whether both are fixed."""
    title, description = desired_frontmatter(target)
    override = EXPLICIT_ROW_OVERRIDES.get(overview, {}).get(target)
    if override is None:
        return title, description, False
    label, row_description = override
    return label, row_description, True


def apply_frontmatter_overrides() -> None:
    """Apply reviewed manual descriptions/titles before table rows consume them."""
    global would_apply
    for slug in sorted(
        set(DESCRIPTION_OVERRIDES) | set(TITLE_OVERRIDES) | set(SIDEBAR_TITLE_OVERRIDES)
    ):
        p = docs_path(slug)
        assert p.is_file(), f"missing override target: {slug}"
        text = p.read_text(encoding="utf-8")
        replacements: list[tuple[str, str, str]] = []
        if slug in DESCRIPTION_OVERRIDES:
            value = DESCRIPTION_OVERRIDES[slug]
            assert "\n" not in value and '"' not in value and "—" not in value, f"invalid description override: {slug}"
            replacements.append(("description", frontmatter_value(text, "description", slug), value))
        if slug in TITLE_OVERRIDES:
            value = TITLE_OVERRIDES[slug]
            assert "\n" not in value and '"' not in value, f"invalid title override: {slug}"
            replacements.append(("title", frontmatter_value(text, "title", slug), value))
        if slug in SIDEBAR_TITLE_OVERRIDES:
            value = SIDEBAR_TITLE_OVERRIDES[slug]
            assert "\n" not in value and '"' not in value, f"invalid sidebar title override: {slug}"
            replacements.append(
                ("sidebarTitle", frontmatter_value(text, "sidebarTitle", slug), value)
            )

        changed = False
        for field, old, new in replacements:
            if old == new:
                continue
            text, count = re.subn(
                rf"^{re.escape(field)}:\s*.+$",
                f'{field}: "{new}"',
                text,
                count=1,
                flags=re.M,
            )
            assert count == 1, f"{slug}: could not replace {field}"
            changed = True
            would_apply += 1
        if not changed:
            continue
        if CHECK:
            print(f"  would apply frontmatter: {slug}")
        else:
            p.write_text(text, encoding="utf-8")
            print(f"  applied frontmatter: {slug}")


def navigation_order() -> dict[str, int]:
    data = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    paths: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            if value.startswith("examples/"):
                paths.append(value.removesuffix(".mdx").rstrip("/"))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(data)
    return {slug: i for i, slug in enumerate(paths)}


def normalized_words(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


BAD_ROW_PREFIXES = (
    "cookbook example for ",
    "cookbook examples for ",
    "examples for `",
    "runnable workflow examples under:",
    "prerequisites:",
    "requirements:",
    "steps:",
    "setup:",
    "usage:",
    "uv pip install ",
    "pip install ",
    "same as ",
)

BAD_ROW_EXACT = {
    "```shell.",
    "```bash.",
    "tool integration example.",
    "add content to the knowledge.",
    "demonstrates this reasoning cookbook example.",
}


def is_bad_description(description: str, target_title: str, *, allow_echo: bool = True) -> bool:
    value = description.strip()
    lower = value.lower()
    if not value or lower in BAD_ROW_EXACT:
        return True
    if "```" in value or "cookbook/" in lower or lower.startswith(BAD_ROW_PREFIXES):
        return True
    if re.match(r"^(?:\d+[.)]|step\s+\d+\b|run:|export\s+)", lower):
        return True
    if re.search(r"(?:,\.|:\.|\.\.\.)$", value):
        return True
    if re.search(r"\b(?:a|an|and|his|her|its|or|the|their),?\.$", lower):
        return True
    if allow_echo:
        echo = re.sub(r"^(?:this\s+)?(?:example\s+)?demonstrat(?:e|es|ing)\s+", "", lower)
        echo = re.sub(r"\s+(?:cookbook\s+)?example\.?$", "", echo).strip(" .`'")
        if normalized_words(echo) == normalized_words(target_title):
            return True
    return False


def is_suitable_target(description: str, target_title: str) -> bool:
    value = description.strip()
    if "\n" in value or "|" in value or "—" in value or re.search(r"\[[^]]+\]\(", value):
        return False
    if is_bad_description(value, target_title):
        return False
    if normalized_words(value.rstrip(".!?")) == normalized_words(target_title):
        return False
    return value.endswith((".", "!", "?"))


ROW_RE = re.compile(
    r"^\|\s*\[(?P<label>.+)\]\((?P<href>/examples/[^)]+)\)\s*\|\s*(?P<description>.*?)\s*\|\s*$"
)
TABLE_HEADER_RE = re.compile(r"^\|\s*Example\s*\|\s*Description\s*\|\s*$")


def table_rows(text: str, slug: str) -> tuple[list[str], int, int, list[dict[str, str]]]:
    lines = text.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if TABLE_HEADER_RE.fullmatch(line.rstrip("\n"))]
    assert len(headers) == 1, f"{slug}: expected one Example/Description table, found {len(headers)}"
    header = headers[0]
    assert header + 1 < len(lines) and re.fullmatch(r"\|[ |:-]+\|\s*", lines[header + 1]), f"{slug}: malformed table separator"
    start = header + 2
    end = start
    rows: list[dict[str, str]] = []
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        raw = lines[end]
        match = ROW_RE.fullmatch(raw.rstrip("\n"))
        assert match, f"{slug}: unsupported table row: {raw.rstrip()!r}"
        href = match.group("href").removeprefix("/").removesuffix(".mdx").rstrip("/")
        rows.append(
            {
                "label": match.group("label").strip(),
                "target": href,
                "description": match.group("description").strip(),
                "raw": raw,
            }
        )
        end += 1
    assert rows, f"{slug}: table has no rows"
    return lines, start, end, rows


def render_row(row: dict[str, str]) -> str:
    return f'| [{row["label"]}](/' + row["target"] + f') | {row["description"]} |\n'


def repaired_row(overview: str, row: dict[str, str], *, force_description: bool = False) -> tuple[dict[str, str], bool]:
    target = row["target"]
    if overview == "examples/tools/overview":
        tool_description = row["description"].strip()
        tool_lower = tool_description.lower()
        obvious_bad_label = bool(
            target in EXPLICIT_LABEL_REFRESH
            or re.match(r"^(?:setup|steps?|run|install|uv\s+pip|pip\s+install)\b", row["label"], re.I)
        )
        obvious_bad_description = bool(
            "```" in tool_description
            or tool_lower.startswith(
                (
                    "prerequisites:",
                    "requirements:",
                    "steps:",
                    "setup:",
                    "usage:",
                    "uv pip install ",
                    "pip install ",
                )
            )
            or re.match(r"^(?:\d+[.)]|step\s+\d+\b|run:|export\s+)", tool_lower)
            or re.search(r"(?:,\.|:\.|\.\.\.)$", tool_description)
        )
        if not force_description and not obvious_bad_label and not obvious_bad_description:
            return row, False
    title, description, explicit_row = desired_row(overview, target)
    changed = False
    label = row["label"]
    bad_label = bool(
        explicit_row
        or target in EXPLICIT_LABEL_REFRESH
        or re.match(r"^(?:setup|steps?|run|install|uv\s+pip|pip\s+install)\b", label, re.I)
        or (normalized_words(label) == normalized_words(title) and label != title)
    )
    if bad_label:
        label = title
        changed = label != row["label"] or changed

    # The tools landing page is intentionally selective. Only its malformed
    # cells and explicit corrupt labels are repaired; generic-but-grammatical
    # contextual rows remain outside this deterministic pass.
    bad_description = is_bad_description(
        row["description"],
        title,
        allow_echo=overview != "examples/tools/overview",
    )
    if explicit_row or force_description or bad_description:
        assert is_suitable_target(description, title), (
            f"{overview}: unsuitable target description for {target}: {description!r}"
        )
        changed = description != row["description"] or changed
        row = {**row, "description": description}
    if label != row["label"]:
        row = {**row, "label": label}
    if changed:
        row = {**row, "raw": render_row(row)}
    return row, changed


def new_row(overview: str, target: str) -> dict[str, str]:
    title, description, _ = desired_row(overview, target)
    assert is_suitable_target(description, title), (
        f"{overview}: unsuitable target description for {target}: {description!r}"
    )
    return {"label": title, "target": target, "description": description, "raw": ""}


def repair_overview_tables() -> None:
    global would_apply
    nav = navigation_order()
    for overview, overrides in EXPLICIT_ROW_OVERRIDES.items():
        for target, (label, description) in overrides.items():
            assert docs_path(target).is_file(), f"row override target is missing: {overview} -> {target}"
            assert label.strip() == label and "\n" not in label and "|" not in label, (
                f"invalid row label override: {overview} -> {target}"
            )
            assert is_suitable_target(description, label), (
                f"invalid row description override: {overview} -> {target}"
            )
    for overview, targets in EXPLICIT_MISSING_ROWS.items():
        assert overview in nav, f"overview is no longer in navigation: {overview}"
        positions = []
        for target in targets:
            assert target in nav, f"explicit target is no longer in navigation: {overview} -> {target}"
            assert docs_path(target).is_file(), f"explicit target is missing: {overview} -> {target}"
            positions.append(nav[target])
        assert positions == sorted(positions) and len(positions) == len(set(positions)), (
            f"explicit targets are not in docs.json order: {overview}"
        )
    for overview, targets in EXPLICIT_TABLE_ORDER.items():
        assert overview in nav, f"ordered overview is no longer in navigation: {overview}"
        assert all(target in nav for target in targets), f"ordered table target left navigation: {overview}"
        positions = [nav[target] for target in targets]
        assert positions == sorted(positions), f"ordered table is not in docs.json order: {overview}"

    overview_slugs = ROW_REPAIR_OVERVIEWS | set(EXPLICIT_MISSING_ROWS) | set(EXPLICIT_ROW_REFRESH) | set(EXPLICIT_TABLE_ORDER)
    for overview in sorted(overview_slugs):
        p = docs_path(overview)
        assert p.is_file(), f"missing overview: {overview}"
        text = p.read_text(encoding="utf-8")
        # Only pages with the standard two-column table participate. Other
        # overview formats are intentionally left alone.
        if not any(TABLE_HEADER_RE.fullmatch(line) for line in text.splitlines()):
            assert overview not in EXPLICIT_MISSING_ROWS and overview not in EXPLICIT_ROW_REFRESH, (
                f"{overview}: explicit repair page has no supported table"
            )
            continue
        lines, start, end, rows = table_rows(text, overview)
        changed = False
        rewrites = ROW_TARGET_REWRITES.get(overview, {})
        for index, row in enumerate(rows):
            target = rewrites.get(row["target"])
            if target is None:
                continue
            rows[index] = {**row, "target": target, "raw": render_row({**row, "target": target})}
            changed = True
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["target"]] = counts.get(row["target"], 0) + 1
        duplicates = sorted(target for target, count in counts.items() if count > 1)
        assert not duplicates, f"{overview}: duplicate targets: {duplicates}"

        repaired: list[dict[str, str]] = []
        forced = EXPLICIT_ROW_REFRESH.get(overview, set())
        existing_targets = set(counts)
        missing = EXPLICIT_MISSING_ROWS.get(overview, [])
        for target in forced:
            assert target in existing_targets, f"{overview}: explicit refresh target is absent: {target}"
        for row in rows:
            row, row_changed = repaired_row(overview, row, force_description=row["target"] in forced)
            repaired.append(row)
            changed |= row_changed

        for target in missing:
            if target in existing_targets:
                continue
            repaired.append(new_row(overview, target))
            existing_targets.add(target)
            changed = True

        if overview in EXPLICIT_TABLE_ORDER:
            order = EXPLICIT_TABLE_ORDER[overview]
            assert len(order) == len(set(order)), f"{overview}: duplicate explicit table target"
            assert set(existing_targets) == set(order), (
                f"{overview}: table membership drift; expected {order}, found {sorted(existing_targets)}"
            )
            by_target = {row["target"]: row for row in repaired}
            repaired = [by_target[target] for target in order]
            if [row["target"] for row in rows] != order:
                changed = True
            for row in repaired:
                row["raw"] = render_row(row)

        if not changed:
            continue
        replacement = [row["raw"] or render_row(row) for row in repaired]
        new_text = "".join(lines[:start] + replacement + lines[end:])
        assert new_text != text, f"{overview}: repair reported change without text delta"
        would_apply += 1
        if CHECK:
            print(f"  would repair overview: {overview}")
        else:
            p.write_text(new_text, encoding="utf-8")
            print(f"  repaired overview: {overview}")


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

    # 3. Curated page shipped with an empty description.
    sub(
        "tools/mcp/include-exclude-tools.mdx",
        'description: ""',
        'description: "Filter which MCP server tools an agent can use with include_tools '
        'and exclude_tools."',
        required=False,  # already fixed in place; keep idempotent
    )

    # 4. Curated page prose with an em dash.
    sub(
        "tools/models-lab-tools.mdx",
        "voiceover—all working",
        "voiceover, all working",
        required=False,
    )

    # 5. Reviewed frontmatter overrides consumed by the overview row pass.
    apply_frontmatter_overrides()

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

    # 7. Refresh only malformed or explicitly stale overview rows, then add
    #    only the navigation-backed omissions approved by the audit.
    repair_overview_tables()

    if CHECK:
        print(f"check: {would_apply} fixes would apply; title-casing would change {count} pages")
    else:
        print(f"one-offs applied; title-casing fixed on {count} additional pages")


if __name__ == "__main__":
    main()
