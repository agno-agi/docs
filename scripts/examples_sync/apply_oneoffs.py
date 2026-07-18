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
    "examples/agent-os/skills/overview": "Load local skills into an AgentOS agent, including sample system-information scripts.",
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
    "examples/models/openai/chat/overview": "OpenAI Chat examples for multimodal input and output, tools, reasoning, structured output, storage, and retries.",
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
    "examples/workflows/conditional-execution/overview": "Condition workflow examples for branching on input and previous-step output.",
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
    "examples/models/internlm/overview": "Retry failed InternLM model requests with exponential backoff.",
    "examples/models/langdb/overview": "Run LangDB models with basic responses, tools, retries, and structured output.",
    "examples/models/lmstudio/overview": "LM Studio examples for local models, images, knowledge, memory, storage, retries, structured output, and tools.",
    "examples/storage/dynamodb/overview": "Store agent and team sessions in DynamoDB.",
    "examples/models/xiaomi/overview": "Xiaomi MiMo agent examples for basic runs, string model shorthand, web search, structured output, thinking mode, and reasoning.",
    "examples/tools/slack-tools": "Compare all-tools, selected-function, and read-only SlackTools configurations for messaging, channel listing, history, and file access.",
    "examples/tools/models/overview": "Model-backed toolkit examples for image and video generation, code editing, and provider-specific tools.",
    "examples/tools/other/overview": "Tool configuration examples for caching, runtime registration, input schemas, HITL, session state, filtering, and stop-after-call behavior.",
}

TITLE_OVERRIDES = {
    "examples/agent-os/rbac/asymmetric/workos-byot": "WorkOS BYOT",
    "examples/agents/tools/tools-with-literal-type-param": "Tools with Literal Type Parameters",
    "examples/integrations/parallel/research-workflow": "Research Workflow",
    "examples/models/dashscope/tool-use": "DashScope Tool Use",
    "examples/models/openai/chat/text-to-speech-agent": "Text-to-Speech Agent",
    "examples/models/openai/responses/image-generation-agent": "Image Generation Agent",
    "examples/models/vercel/tool-use": "Vercel v0 Tool Use",
    "examples/models/vllm/tool-use": "vLLM Tool Use",
    "examples/models/xai/finance-agent": "Finance Agent",
    "examples/reasoning/models/groq/deepseek-plus-claude": "Qwen3 Plus Claude",
    "examples/storage/mongo/mongodb-for-agent": "MongoDB for Agent",
    "examples/storage/mongo/mongodb-for-team": "MongoDB for Team",
    "examples/tools/mlx-transcribe-tools": "MLX Transcribe Tools",
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
    "examples/models/anthropic/overview": [
        "examples/models/anthropic/adaptive-thinking",
        "examples/models/anthropic/append-trailing-user-message",
        "examples/models/anthropic/markdown-input",
        "examples/models/anthropic/prompt-caching-multi-block",
        "examples/models/anthropic/prompt-caching-with-dynamic-block",
        "examples/models/anthropic/pydantic-tool-input",
        "examples/models/anthropic/server-tools-multi-turn",
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
    "examples/workflows/cel-expressions/router/overview": {
        "examples/workflows/cel-expressions/router/cel-previous-step-route": (
            "CEL Previous Step Route",
            "Use previous_step_outputs to read a named classifier result and route to the matching handler.",
        ),
        "examples/workflows/cel-expressions/router/cel-ternary": (
            "CEL Ternary",
            "Use a CEL ternary expression to choose between two steps based on the input content.",
        ),
        "examples/workflows/cel-expressions/router/cel-using-step-choices": (
            "CEL Using Step Choices",
            "Use step_choices indexes to reference route targets without hardcoding step names.",
        ),
    },
    "examples/reasoning/models/groq/overview": {
        "examples/reasoning/models/groq/deepseek-plus-claude": (
            "Qwen3 Plus Claude",
            "Route reasoning through Qwen3-32B on Groq while Claude writes the final answer.",
        ),
    },
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
            "Issue HS256 tokens across five privilege tiers to show global, per-agent, and wildcard scopes filtering the agent list and gating agent runs.",
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
    "examples/models/anthropic/overview": {
        "examples/models/anthropic/adaptive-thinking": (
            "Anthropic Adaptive Thinking",
            'Let Claude 4.6 decide its own thinking depth with `thinking={"type": "adaptive"}` and an effort level.',
        ),
    },
}

# Invalid-model requests are not deterministic retry tests. These generated
# pages use one shared replacement-only description, and every parent overview
# must consume that generated frontmatter instead of an older manual override.
INVALID_MODEL_RETRY_SLUGS = {
    "examples/models/aimlapi/retry",
    "examples/models/anthropic/retry",
    "examples/models/aws/retry",
    "examples/models/azure/retry",
    "examples/models/cerebras/retry",
    "examples/models/cohere/retry",
    "examples/models/cometapi/retry",
    "examples/models/dashscope/retry",
    "examples/models/deepinfra/retry",
    "examples/models/deepseek/retry",
    "examples/models/fireworks/retry",
    "examples/models/google/gemini/retry",
    "examples/models/groq/retry",
    "examples/models/huggingface/retry",
    "examples/models/ibm/retry",
    "examples/models/internlm/retry",
    "examples/models/langdb/retry",
    "examples/models/litellm/retry",
    "examples/models/llama-cpp/retry",
    "examples/models/lmstudio/retry",
    "examples/models/meta/retry",
    "examples/models/mistral/retry",
    "examples/models/nebius/retry",
    "examples/models/nexus/retry",
    "examples/models/nvidia/retry",
    "examples/models/ollama/chat/retry",
    "examples/models/openai/chat/retry",
    "examples/models/openai/chat/with-retries",
    "examples/models/openrouter/chat/retry",
    "examples/models/perplexity/retry",
    "examples/models/portkey/retry",
    "examples/models/requesty/retry",
    "examples/models/sambanova/retry",
    "examples/models/siliconflow/retry",
    "examples/models/together/retry",
    "examples/models/vercel/retry",
    "examples/models/vertexai/retry",
    "examples/models/vllm/retry",
    "examples/models/xai/retry",
}

# These pages have a reviewed, factual mismatch that is grammatical enough not
# to be caught by the fail-closed malformed-row detector.
EXPLICIT_ROW_REFRESH = {
    "examples/reasoning/tools/overview": {
        "examples/reasoning/tools/cerebras-llama-reasoning-tools",
    },
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
        "examples/agent-os/interfaces/slack/multimodal-team",
        "examples/agent-os/interfaces/slack/multimodal-workflow",
    },
    "examples/agent-os/interfaces/whatsapp/overview": {
        "examples/agent-os/interfaces/whatsapp/multiple-instances",
        "examples/agent-os/interfaces/whatsapp/multimodal-team",
        "examples/agent-os/interfaces/whatsapp/multimodal-workflow",
    },
    "examples/integrations/memory/overview": {
        "examples/memory/integrations/dakera-integration",
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
        "examples/agent-os/rbac/symmetric/basic",
        "examples/agent-os/rbac/symmetric/with-cookie",
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
    "examples/tools/mcp/overview": {
        "examples/tools/mcp/pipedream-linkedin",
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
        "examples/agents/human-in-the-loop/confirmation-required",
        "examples/agents/human-in-the-loop/confirmation-required-mcp-toolkit",
        "examples/agents/human-in-the-loop/confirmation-toolkit",
        "examples/agents/human-in-the-loop/external-tool-execution",
        "examples/agents/human-in-the-loop/user-input-required",
        "examples/agents/approvals/approval-team",
        "examples/agents/approvals/audit-approval-overview",
    },
    "examples/agents/input-output/overview": {"examples/agents/input-output/parser-model"},
    "examples/agents/advanced/overview": {
        "examples/agents/advanced/reasoning-agent-events",
    },
    "examples/agents/hooks/overview": {
        "examples/agents/context-management/filter-tool-calls-from-history",
        "examples/agents/context-management/instructions",
    },
    "examples/agents/multimodal/overview": {
        "examples/agents/multimodal/audio-input-output",
        "examples/agents/multimodal/audio-sentiment-analysis",
        "examples/agents/multimodal/audio-streaming",
        "examples/agents/multimodal/audio-to-text",
    },
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
    "examples/models/cerebras/overview": {
        "examples/models/cerebras/basic",
        "examples/models/cerebras/db",
        "examples/models/cerebras/tool-use",
    },
    "examples/models/cerebras-openai/overview": {
        "examples/models/cerebras-openai/basic",
        "examples/models/cerebras-openai/db",
    },
    "examples/models/aimlapi/overview": {
        "examples/models/aimlapi/basic",
        "examples/models/aimlapi/image-agent",
        "examples/models/aimlapi/image-agent-bytes",
        "examples/models/aimlapi/image-agent-with-memory",
        "examples/models/aimlapi/structured-output",
        "examples/models/aimlapi/tool-use",
    },
    "examples/models/anthropic/overview": {
        "examples/models/anthropic/betas",
        "examples/models/anthropic/context-management",
        "examples/models/anthropic/db",
        "examples/models/anthropic/image-input-file-upload",
        "examples/models/anthropic/image-input-local-file",
        "examples/models/anthropic/knowledge",
        "examples/models/anthropic/memory",
        "examples/models/anthropic/pdf-input-file-upload",
        "examples/models/anthropic/prompt-caching",
        "examples/models/anthropic/prompt-caching-extended",
        "examples/models/anthropic/retry",
        "examples/models/anthropic/skills/overview",
        "examples/models/anthropic/structured-output-strict-tools",
        "examples/models/anthropic/tool-use",
    },
    "examples/models/cometapi/overview": {
        "examples/models/cometapi/multi-model",
        "examples/models/cometapi/retry",
    },
    "examples/models/cohere/overview": {
        "examples/models/cohere/db",
        "examples/models/cohere/tool-use",
    },
    "examples/models/dashscope/overview": {
        "examples/models/dashscope/image-agent",
    },
    "examples/reasoning/models/gemini/overview": {
        "examples/reasoning/models/gemini/basic-reasoning",
    },
    "examples/models/deepseek/overview": {"examples/models/deepseek/tool-use"},
    "examples/models/deepinfra/overview": {
        "examples/models/deepinfra/basic",
        "examples/models/deepinfra/retry",
        "examples/models/deepinfra/tool-use",
    },
    "examples/models/azure/ai-foundry/overview": {
        "examples/models/azure/ai-foundry/db",
        "examples/models/azure/ai-foundry/structured-output",
        "examples/models/azure/ai-foundry/tool-use",
    },
    "examples/models/fireworks/overview": {
        "examples/models/fireworks/basic",
        "examples/models/fireworks/retry",
        "examples/models/fireworks/structured-output",
        "examples/models/fireworks/tool-use",
    },
    "examples/models/groq/overview": {
        "examples/models/groq/db",
        "examples/models/groq/deep-knowledge",
        "examples/models/groq/knowledge",
        "examples/models/groq/research-agent-exa",
        "examples/models/groq/research-agent-seltz",
        "examples/models/groq/transcription-agent",
        "examples/models/groq/tool-use",
    },
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
    "examples/models/langdb/overview": {
        "examples/models/langdb/basic",
        "examples/models/langdb/data-analyst",
        "examples/models/langdb/finance-agent",
        "examples/models/langdb/structured-output",
        "examples/models/langdb/web-search",
    },
    "examples/models/litellm-openai/overview": {
        "examples/models/litellm-openai/tool-use",
    },
    "examples/models/llama-cpp/overview": {
        "examples/models/llama-cpp/retry",
        "examples/models/llama-cpp/tool-use",
    },
    "examples/models/mistral/overview": {
        "examples/models/mistral/image-bytes-input-agent",
        "examples/models/mistral/image-compare-agent",
        "examples/models/mistral/image-file-input-agent",
        "examples/models/mistral/image-ocr-with-structured-output",
        "examples/models/mistral/image-transcribe-document-agent",
        "examples/models/mistral/mistral-small",
        "examples/models/mistral/tool-use",
    },
    "examples/models/nvidia/overview": {"examples/models/nvidia/tool-use"},
    "examples/models/nebius/overview": {"examples/models/nebius/db"},
    "examples/models/nexus/overview": {"examples/models/nexus/tool-use"},
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
    "examples/models/openai/chat/overview": {
        "examples/models/openai/chat/generate-images",
    },
    "examples/models/together/overview": {"examples/models/together/tool-use"},
    "examples/models/openrouter/chat/overview": {
        "examples/models/openrouter/chat/tool-use",
    },
    "examples/models/portkey/overview": {"examples/models/portkey/retry"},
    "examples/models/requesty/overview": {"examples/models/requesty/tool-use"},
    "examples/models/siliconflow/overview": {
        "examples/models/siliconflow/tool-use",
    },
    "examples/models/vllm/overview": {
        "examples/models/vllm/code-generation",
        "examples/models/vllm/db",
    },
    "examples/storage/dynamodb/overview": {
        "examples/storage/dynamodb/dynamo-for-agent",
        "examples/storage/dynamodb/dynamo-for-team",
    },
    "examples/storage/overview": {
        "examples/storage/in-memory/overview",
        "examples/storage/mongo/overview",
        "examples/storage/dynamodb/overview",
    },
    "examples/storage/mongo/overview": {
        "examples/storage/mongo/mongodb-for-agent",
        "examples/storage/mongo/mongodb-for-team",
    },
    "examples/storage/json-db/overview": {
        "examples/storage/json-db/json-for-agent",
        "examples/storage/json-db/json-for-team",
        "examples/storage/json-db/json-for-workflows",
    },
    "examples/tools/mcp/sse-transport/overview": {
        "examples/tools/mcp/sse-transport/client",
    },
    "examples/tools/mcp/streamable-http-transport/overview": {
        "examples/tools/mcp/streamable-http-transport/client",
    },
    "examples/tools/overview": {
        "examples/tools/brandfetch-tools",
        "examples/tools/bravesearch-tools",
        "examples/tools/dalle-tools",
        "examples/tools/discord-tools",
        "examples/tools/googlesheets-tools",
        "examples/tools/mem0-tools",
        "examples/tools/searchapi-tools",
        "examples/tools/serper-tools",
        "examples/tools/slack-tools",
        "examples/tools/webex-tools",
        "examples/tools/zep-tools",
        "examples/tools/exceptions/overview",
        "examples/tools/models/overview",
        "examples/tools/other/overview",
        "examples/tools/tool-decorator/overview",
        "examples/tools/tool-hooks/overview",
    },
    "examples/tools/models/overview": {
        "examples/tools/models/azure-openai-tools",
        "examples/tools/models/openai-tools",
    },
    "examples/workflows/conditional-branching/overview": {
        "examples/workflows/conditional-branching/selector-media-pipeline",
    },
    "examples/agent-os/dbs/overview": {
        "examples/agent-os/dbs/agentos-default-db",
        "examples/agent-os/dbs/dynamo",
        "examples/agent-os/dbs/neon",
        "examples/agent-os/dbs/supabase",
        "examples/agent-os/dbs/surreal-db/overview",
    },
    "examples/teams/basics/overview": {"examples/teams/basics/basic-coordination"},
    "examples/teams/learning/overview": {"examples/teams/learning/team-learned-knowledge"},
    "examples/teams/modes/tasks/overview": {
        "examples/teams/modes/tasks/basic",
        "examples/teams/modes/tasks/dependencies",
        "examples/teams/modes/tasks/parallel",
    },
    "examples/teams/multimodal/overview": {
        "examples/teams/multimodal/generate-image-with-team",
    },
    "examples/teams/overview": {
        "examples/teams/basics/overview",
        "examples/teams/context-compression/overview",
        "examples/teams/context-management/overview",
        "examples/teams/dependencies/overview",
        "examples/teams/distributed-rag/overview",
        "examples/teams/guardrails/overview",
        "examples/teams/hooks/overview",
        "examples/teams/human-in-the-loop/overview",
        "examples/teams/knowledge/overview",
        "examples/teams/learning/overview",
        "examples/teams/memory/overview",
        "examples/teams/metrics/overview",
        "examples/teams/multimodal/overview",
        "examples/teams/reasoning/overview",
        "examples/teams/run-control/overview",
        "examples/teams/search-coordination/overview",
        "examples/teams/session/overview",
        "examples/teams/state/overview",
        "examples/teams/streaming/overview",
        "examples/teams/structured-input-output/overview",
        "examples/teams/tools/overview",
    },
    "examples/teams/task-mode/overview": {
        "examples/teams/task-mode/basic-task-mode",
        "examples/teams/task-mode/parallel-tasks",
        "examples/teams/task-mode/task-mode-with-tools",
        "examples/teams/task-mode/multi-run-session",
        "examples/teams/task-mode/dependency-chain",
        "examples/teams/multimodal/generate-image-with-team",
    },
}

for _retry_slug in INVALID_MODEL_RETRY_SLUGS:
    _retry_overview = f"{_retry_slug.rsplit('/', 1)[0]}/overview"
    EXPLICIT_ROW_REFRESH.setdefault(_retry_overview, set()).add(_retry_slug)

# These reviewed indexes must mirror every target page's current title and
# description. New rows are covered automatically because the refresh set is
# derived from the table rather than maintained target by target.
FULL_ROW_REFRESH_OVERVIEWS = {
    "examples/models/google/gemini/overview",
    "examples/models/openai/chat/overview",
    "examples/models/together/overview",
    "examples/models/xai/overview",
}

ACRONYM_LABEL_REFRESH_OVERVIEWS = {
    "examples/models/openai/responses/overview",
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
    "examples/agent-os/rbac/symmetric/with-cookie",
    "examples/agent-os/tracing/basic-agent-tracing",
    "examples/agent-os/tracing/basic-workflow-tracing",
    "examples/agent-os/tracing/tracing-with-multi-db-scenario",
    "examples/models/azure/ai-foundry/db",
    "examples/models/azure/ai-foundry/structured-output",
    "examples/models/azure/ai-foundry/tool-use",
    "examples/models/litellm-openai/audio-input",
    "examples/models/groq/tool-use",
    "examples/storage/dynamodb/dynamo-for-agent",
    "examples/storage/dynamodb/dynamo-for-team",
    "examples/storage/mongo/mongodb-for-agent",
    "examples/storage/mongo/mongodb-for-team",
    "examples/models/vercel/tool-use",
    "examples/models/vllm/tool-use",
    "examples/tools/bitbucket-tools",
    "examples/tools/desi-vocal-tools",
    "examples/tools/elevenlabs-tools",
    "examples/tools/googlesheets-tools",
    "examples/tools/mlx-transcribe-tools",
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

# Post-tag toolkit pages that are live in docs.json but missing from the
# hand-maintained toolkit index. Cards are rendered without icons so the page
# does not invent visual metadata absent from the target frontmatter.
TOOLKIT_INDEX_CARDS = {
    "Search": [
        (
            "Parallel",
            "/tools/toolkits/search/parallel",
            "Use Parallel with Agno for AI-optimized web search and content extraction.",
        ),
        (
            "Scavio",
            "/tools/toolkits/search/scavio",
            "Search Google, YouTube, marketplaces, and social platforms through the Scavio API.",
        ),
        (
            "Seltz",
            "/tools/toolkits/search/seltz",
            "Run AI-powered semantic search against the Seltz gRPC API with SeltzTools.",
        ),
        (
            "You.com",
            "/tools/toolkits/search/youcom",
            "Search the web with YouTools using domain filters and livecrawl.",
        ),
        (
            "Brave Search",
            "/tools/toolkits/search/bravesearch",
            "Search the web with BraveSearchTools using the Brave Search API.",
        ),
    ],
    "Web Scraping": [
        (
            "ScrapeGraph",
            "/tools/toolkits/web-scrape/scrapegraph",
            "Extract structured data, Markdown, and raw HTML from webpages with ScrapeGraphTools.",
        ),
        (
            "Oxylabs",
            "/tools/toolkits/web-scrape/oxylabs",
            "Access Oxylabs SERP, Amazon product, and universal web scraping APIs.",
        ),
    ],
    "Local": [
        (
            "Coding",
            "/tools/toolkits/local/coding",
            "Give an agent scoped file and shell tools for coding tasks.",
        ),
        (
            "Workspace",
            "/tools/toolkits/local/workspace",
            "Give an agent read, write, edit, search, and shell access to a directory with destructive operations gated by default.",
        ),
    ],
    "File Generation": [
        (
            "File Generation",
            "/tools/toolkits/file-generation/file-generation",
            "Generate files in multiple formats from agents and teams with FileGenerationTools.",
        ),
    ],
    "Native Model Toolkit": [
        (
            "Gemini",
            "/tools/toolkits/models/gemini",
            "Generate images and videos using the Gemini API and Vertex AI models.",
        ),
        (
            "OpenAI",
            "/tools/toolkits/models/openai",
            "Give an agent OpenAI audio transcription, image generation, and text-to-speech tools.",
        ),
    ],
    "Additional Toolkits": [
        (
            "Antigravity",
            "/tools/toolkits/others/antigravity",
            "Delegate subtasks to Google's Managed Agents sandbox from an Agno agent.",
        ),
        (
            "Daytona",
            "/tools/toolkits/others/daytona",
            "Run agent-generated code in a remote sandbox with Daytona.",
        ),
        (
            "GitLab",
            "/tools/toolkits/others/gitlab",
            "Read GitLab projects, merge requests, and issues with GitlabTools.",
        ),
        (
            "Google Drive",
            "/tools/toolkits/others/google-drive",
            "List, search, read, upload, and download Google Drive files.",
        ),
        (
            "LLMs.txt",
            "/tools/toolkits/others/llms-txt",
            "Discover and read documentation from an llms.txt index.",
        ),
        (
            "MoviePy Video Tools",
            "/tools/toolkits/others/moviepy",
            "Process videos, extract audio, and generate or embed captions with MoviePyVideoTools.",
        ),
        (
            "Salesforce",
            "/tools/toolkits/others/salesforce",
            "Query and manage Salesforce CRM records with SOQL, SOSL, and the REST API.",
        ),
        (
            "Trello",
            "/tools/toolkits/others/trello",
            "Create and manage Trello boards, lists, and cards.",
        ),
        (
            "TwelveLabs",
            "/tools/toolkits/others/twelvelabs",
            "Analyze videos and generate multimodal text embeddings with TwelveLabs.",
        ),
        (
            "User Feedback",
            "/tools/toolkits/others/user-feedback",
            "Pause an agent to ask the user structured questions with predefined options.",
        ),
        (
            "Web Browser Tools",
            "/tools/toolkits/others/web-browser",
            "Open a URL in a web browser with WebBrowserTools.",
        ),
    ],
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


def sub_file(p: Path, old: str, new: str, required: bool = True) -> None:
    global would_apply
    path = str(p.relative_to(ROOT))
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


def sub_all_file(p: Path, old: str, new: str, expected: int) -> None:
    global would_apply
    path = str(p.relative_to(ROOT))
    text = p.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 0 and new_count == expected:
        print(f"  already applied: {path}")
        return
    assert old_count == expected and new_count == 0, (
        f"{path}: expected {expected} old and 0 new patterns, "
        f"found {old_count} old and {new_count} new"
    )
    if CHECK:
        print(f"  would apply: {path}")
        would_apply += 1
        return
    p.write_text(text.replace(old, new), encoding="utf-8")
    print(f"  applied: {path}")


def sub(path: str, old: str, new: str, required: bool = True) -> None:
    sub_file(DOCS / path, old, new, required)


def sub_all(path: str, old: str, new: str, expected: int) -> None:
    sub_all_file(DOCS / path, old, new, expected)


def root_sub(path: str, old: str, new: str, required: bool = True) -> None:
    sub_file(ROOT / path, old, new, required)


def normalize_terminal_newlines(path: str, count: int = 1) -> None:
    global would_apply
    assert count >= 0, "terminal newline count must be non-negative"
    p = ROOT / path
    data = p.read_bytes()
    assert b"\r\n" not in data, f"{path}: CRLF is not supported"
    normalized = data.rstrip(b"\n") + (b"\n" * count)
    if data == normalized:
        print(f"  terminal newlines already normalized: {path}")
        return
    if CHECK:
        print(f"  would normalize terminal newlines: {path}")
        would_apply += 1
        return
    p.write_bytes(normalized)
    print(f"  normalized terminal newlines: {path}")


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
    current_description = frontmatter_value(text, "description", slug)
    if slug in INVALID_MODEL_RETRY_SLUGS:
        description = current_description
    else:
        description = DESCRIPTION_OVERRIDES.get(
            slug,
            GENERATED_DESCRIPTION_OVERRIDES.get(slug, current_description),
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


def repaired_row(
    overview: str,
    row: dict[str, str],
    *,
    force_description: bool = False,
    force_label: bool = False,
) -> tuple[dict[str, str], bool]:
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
    label = row["label"]
    if overview in ACRONYM_LABEL_REFRESH_OVERVIEWS:
        label = gen.fix_title_casing(label)
    changed = label != row["label"]
    bad_label = bool(
        force_label
        or explicit_row
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
        changed = True
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

    overview_slugs = (
        ROW_REPAIR_OVERVIEWS
        | set(EXPLICIT_MISSING_ROWS)
        | set(EXPLICIT_ROW_OVERRIDES)
        | set(EXPLICIT_ROW_REFRESH)
        | FULL_ROW_REFRESH_OVERVIEWS
        | ACRONYM_LABEL_REFRESH_OVERVIEWS
        | set(EXPLICIT_TABLE_ORDER)
    )
    for overview in sorted(overview_slugs):
        p = docs_path(overview)
        assert p.is_file(), f"missing overview: {overview}"
        text = p.read_text(encoding="utf-8")
        # Only pages with the standard two-column table participate. Other
        # overview formats are intentionally left alone.
        if not any(TABLE_HEADER_RE.fullmatch(line) for line in text.splitlines()):
            assert (
                overview not in EXPLICIT_MISSING_ROWS
                and overview not in EXPLICIT_ROW_OVERRIDES
                and overview not in EXPLICIT_ROW_REFRESH
                and overview not in FULL_ROW_REFRESH_OVERVIEWS
            ), (
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
        existing_targets = set(counts)
        full_refresh = overview in FULL_ROW_REFRESH_OVERVIEWS
        forced = existing_targets if full_refresh else EXPLICIT_ROW_REFRESH.get(overview, set())
        missing = EXPLICIT_MISSING_ROWS.get(overview, [])
        for target in forced:
            assert target in existing_targets, f"{overview}: explicit refresh target is absent: {target}"
        for row in rows:
            row, row_changed = repaired_row(
                overview,
                row,
                force_description=row["target"] in forced,
                force_label=full_refresh,
            )
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


def render_toolkit_card(title: str, href: str, description: str) -> str:
    assert all(value.strip() == value and "\n" not in value for value in (title, href, description))
    assert title and href.startswith("/tools/toolkits/") and description.endswith((".", "!", "?"))
    assert '"' not in title and '"' not in href
    return (
        f'  <Card\n    title="{title}"\n    href="{href}"\n  >\n'
        f"    {description}\n"
        "  </Card>\n"
    )


def repair_toolkit_index() -> None:
    """Add reviewed post-tag toolkit cards without duplicating upstream additions."""
    global would_apply
    p = ROOT / "tools/toolkits/overview.mdx"
    text = p.read_text(encoding="utf-8")
    changed = False

    file_heading = "## File Generation\n\n<CardGroup cols={3}>"
    if file_heading not in text:
        anchor = "## Native Model Toolkit\n\n<CardGroup cols={3}>"
        assert anchor in text, "toolkit index: Native Model Toolkit anchor is missing"
        text = text.replace(
            anchor,
            file_heading + "\n</CardGroup>\n\n" + anchor,
            1,
        )
        changed = True

    for heading, cards in TOOLKIT_INDEX_CARDS.items():
        marker = f"## {heading}\n\n<CardGroup cols={{3}}>"
        start = text.find(marker)
        assert start >= 0, f"toolkit index: missing section {heading}"
        end = text.find("</CardGroup>", start)
        assert end >= 0, f"toolkit index: unclosed CardGroup for {heading}"
        for title, href, description in cards:
            href_token = f'href="{href}"'
            occurrences = text.count(href_token)
            assert occurrences <= 1, f"toolkit index: duplicate href {href}"
            if occurrences == 1:
                continue
            card = render_toolkit_card(title, href, description)
            text = text[:end] + card + text[end:]
            end += len(card)
            changed = True

    for cards in TOOLKIT_INDEX_CARDS.values():
        for _, href, _ in cards:
            assert text.count(f'href="{href}"') == 1, f"toolkit index: missing href {href}"

    if not changed:
        return
    would_apply += 1
    if CHECK:
        print("  would repair toolkit index")
    else:
        p.write_text(text, encoding="utf-8")
        print("  repaired toolkit index")


def main() -> None:
    global CHECK
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report fix state without writing")
    CHECK = ap.parse_args().check

    # Source-backed corrections identified by the generated-example review.
    sub(
        "reasoning/models/vertex-ai/basic-reasoning-stream.mdx",
        'title: "Basic Reasoning Stream"',
        'title: "Vertex AI Basic Reasoning Stream"',
    )
    sub(
        "reasoning/models/vertex-ai/basic-reasoning-stream.mdx",
        """  <Step title="Authenticate with Google Cloud">
    Sign in with Application Default Credentials:
    ```bash
    gcloud auth application-default login
    ```
  </Step>""",
        """  <Step title="Authenticate with Google Cloud">
    Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then sign in with Application Default Credentials:
    ```bash
    gcloud auth application-default login
    ```
  </Step>""",
    )
    # 1. Docstring title is the generic mode name; page is the structured-debate example.
    sub(
        "teams/modes/broadcast/structured-debate.mdx",
        'title: "Broadcast Mode"',
        'title: "Structured Debate"',
    )

    # 2. Digit-heavy stem (9_11_or_9_9) defeats the numeric-prefix strip; upstream
    #    docstring is a machine stub.
    sub("reasoning/models/groq/or-9-9.mdx", 'title: "11 or 9 9"', 'title: "9.11 or 9.9"')

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

    # 5. Reviewed fixes for preserved curated pages.
    sub(
        "tools/brandfetch-tools.mdx",
        "export BRANDFETCH_CLIENT_KEY=your_client_id",
        "export BRANDFETCH_CLIENT_ID=your_client_id",
    )
    sub(
        "tools/googlecalendar-tools.mdx",
        'Enable Agno agents the "executive assistance" capability to move beyond just reading emails or chat to actively managing your time, coordinating with teams, and resolving scheduling conflicts autonomously with Google Calendar.',
        "Enable Agno agents to list, create, update, and delete Google Calendar events and find free time slots.",
    )
    sub(
        "tools/googlecalendar-tools.mdx",
        "Make Sure you've enabled Google calender API otherwise scopes wont be visible",
        "Make sure you've enabled Google Calendar API. Otherwise, the scopes will not be visible",
    )
    sub(
        "tools/openweather-tools.mdx",
        "Enable Agno agents to fetch real-time weather conditions, multi-day forecasts, and environmental data like air quality directly from the OpenWeather API to make context-aware decisions.",
        "Use OpenWeatherTools to fetch current weather, forecasts, air-quality data, and geocoding results.",
    )
    sub(
        "tools/openweather-tools.mdx",
        """## Prerequisites:
1. Get an API key from https://openweathermap.org/api
2. Set the OPENWEATHER_API_KEY environment variable or pass it directly to the tool""",
        """## Prerequisites

1. [Create an OpenWeather API key](https://openweathermap.org/api).
2. Export `OPENWEATHER_API_KEY` and `OPENAI_API_KEY`.""",
    )
    sub(
        "tools/openweather-tools.mdx",
        'export OPENWEATHER_API_KEY="***"',
        'export OPENAI_API_KEY="your_openai_api_key_here"\nexport OPENWEATHER_API_KEY="your_openweather_api_key_here"',
    )
    sub(
        "tools/aws-lambda-tools.mdx",
        """## Prerequisites:
- Run: `uv pip install boto3` to install dependencies
- Set up AWS credentials (AWS CLI, environment variables, or IAM roles)
- Ensure proper IAM permissions for Lambda operations""",
        """## Prerequisites
- Set up AWS credentials (AWS CLI, environment variables, or IAM roles)
- Ensure proper IAM permissions for Lambda operations""",
    )
    sub(
        "tools/aws-lambda-tools.mdx",
        """# Example 4: Invoke-only agent for testing
agent_tester = Agent(
    tools=[
        AWSLambdaTools(
            region_name="us-east-1",
            enable_list_functions=True,  # Enable listing for reference
            enable_invoke_function=True,  # Enable function testing""",
        """# Example 4: Invoke-only agent for testing
agent_tester = Agent(
    tools=[
        AWSLambdaTools(
            region_name="us-east-1",
            enable_list_functions=True,
            enable_invoke_function=True,""",
    )
    sub(
        "tools/aws-lambda-tools.mdx",
        """cd agno

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python cookbook/91_tools/aws_lambda_tools.py""",
        """cd agno

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate
uv pip install -U boto3
export OPENAI_API_KEY="your_openai_api_key_here"

python cookbook/91_tools/aws_lambda_tools.py""",
    )
    sub(
        "tools/aws-ses-tools.mdx",
        """cd agno/cookbook/91_tools

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python aws_ses_tools.py""",
        """cd agno

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python cookbook/91_tools/aws_ses_tools.py""",
    )
    sub(
        "tools/bitbucket-tools.mdx",
        """cd agno/cookbook/91_tools

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python bitbucket_tools.py""",
        """cd agno

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python cookbook/91_tools/bitbucket_tools.py""",
    )
    sub(
        "tools/github-tools.mdx",
        """    <Tabs>
        <Tab title="Public GitHub">
            export GITHUB_ACCESS_TOKEN="your_token_here"
            export GITHUB_BASE_URL="https://api.github.com"
        </Tab>
        <Tab title="Enterprise GitHub">
            export GITHUB_BASE_URL="https://YOUR-ENTERPRISE-HOSTNAME/api/v3"
        </Tab>
    </Tabs>""",
        """    <Tabs>
      <Tab title="Public GitHub">
        ```bash
        export GITHUB_ACCESS_TOKEN="your_token_here"
        export GITHUB_BASE_URL="https://api.github.com"
        ```
      </Tab>
      <Tab title="Enterprise GitHub">
        ```bash
        export GITHUB_BASE_URL="https://YOUR-ENTERPRISE-HOSTNAME/api/v3"
        ```
      </Tab>
    </Tabs>""",
    )
    sub(
        "tools/github-tools.mdx",
        """## Prerequisites

* Install dependencies: `uv pip install -U agno pygithub openai`.
* Export your OpenAI API key:""",
        """## Prerequisites

* Export your OpenAI API key:""",
    )
    sub(
        "tools/github-tools.mdx",
        """source .venvs/demo/bin/activate

python cookbook/91_tools/github_tools.py""",
        """source .venvs/demo/bin/activate
uv pip install -U pygithub

python cookbook/91_tools/github_tools.py""",
    )
    sub(
        "tools/mem0-tools.mdx",
        """source .venvs/demo/bin/activate

python cookbook/91_tools/mem0_tools.py""",
        """source .venvs/demo/bin/activate
uv pip install -U mem0ai

python cookbook/91_tools/mem0_tools.py""",
    )

    # 6. Post-tag static pages that are outside the pinned cookbook generator.
    root_sub(
        "database/providers/valkey/usage/valkey-for-agent.mdx",
        """## Usage

### Run Valkey""",
        """## Usage

Install dependencies:

```bash
uv pip install -U agno ddgs openai valkey-glide-sync
```

### Run Valkey""",
    )
    root_sub(
        "database/providers/valkey/overview.mdx",
        """## Usage

### Run Valkey""",
        """## Usage

Install dependencies:

```bash
uv pip install -U agno openai valkey-glide-sync
```

### Run Valkey""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-team.mdx",
        """## Usage

### Run Valkey""",
        """## Usage

Install dependencies:

```bash
uv pip install -U agno ddgs openai valkey-glide-sync
```

### Run Valkey""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-workflow.mdx",
        """## Usage

### Run Valkey""",
        """## Usage

Install dependencies:

```bash
uv pip install -U agno ddgs fastapi openai valkey-glide-sync
```

### Run Valkey""",
    )
    root_sub(
        "knowledge/vector-stores/valkey/overview.mdx",
        """## Setup

Valkey vector search requires""",
        """## Setup

Install dependencies:

```bash
uv pip install -U agno openai pypdf valkey-glide-sync
```

Valkey vector search requires""",
        required=False,
    )
    root_sub(
        "knowledge/vector-stores/valkey/overview.mdx",
        """Install dependencies:

```bash
uv pip install -U agno openai pypdf valkey-glide-sync
```

Valkey vector search requires""",
        """Install dependencies:

```bash
uv pip install -U agno openai pypdf valkey-glide-sync
```

Set the API key used by the default OpenAI embedder and agent model:

<CodeGroup>
```bash Mac/Linux
export OPENAI_API_KEY="your_openai_api_key_here"
```

```bash Windows
$Env:OPENAI_API_KEY="your_openai_api_key_here"
```
</CodeGroup>

Valkey vector search requires""",
    )
    root_sub(
        "knowledge/vector-stores/valkey/usage/valkey-db.mdx",
        """  <Step title="Run Valkey">""",
        """  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash Mac/Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run Valkey">""",
    )
    root_sub(
        "tracing/db-functions.mdx",
        "Agno provides convenience functions on your database instance to query traces and spans. These functions work with any supported database (SQLite, PostgreSQL, etc.).",
        "Agno provides convenience functions on your database instance to query traces and spans. Parameter support can vary by database implementation.",
    )
    root_sub(
        "tracing/db-functions.mdx",
        """**Returns:** `List[Span]`

<Note>""",
        """**Returns:** `List[Span]`

<Warning>
  In Agno v2.7.2, synchronous `SqliteDb.get_spans()` does not accept `limit`. Omit `limit` when using SQLite. The other filters and the SQLite example below work as shown.
</Warning>

<Note>""",
    )
    root_sub(
        "reference-api/schema/approvals/get-approval-count.mdx",
        """---
openapi: get /approvals/count
---""",
        """---
openapi: get /approvals/count
---

<Warning>
  This endpoint counts pending approvals. With user isolation enabled, non-admin requests are scoped to the user ID in the JWT even when `user_id` is supplied. Authentication failures can return `401`, and databases without approval support can return `503`; the current OpenAPI operation declares only `200` and `422`.
</Warning>""",
    )
    root_sub(
        "examples/tools/dalle-tools.mdx",
        "The pinned source expected the `openai` package and an `OPENAI_API_KEY`. Its `DalleTools` calls no longer run against the current OpenAI API.",
        "This example expected the `openai` package and an `OPENAI_API_KEY`. Its `DalleTools` calls no longer run against the current OpenAI API.",
    )
    root_sub(
        "tools/toolkits/models/azure-openai.mdx",
        "The pinned source requires `requests`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_IMAGE_DEPLOYMENT`.",
        "This legacy example requires `requests`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_IMAGE_DEPLOYMENT`.",
    )
    root_sub(
        "tools/toolkits/others/dalle.mdx",
        "The pinned source expected the `openai` package and an `OPENAI_API_KEY`.",
        "This legacy example expected the `openai` package and an `OPENAI_API_KEY`.",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-agent.mdx",
        "uv pip install -U agno openai valkey-glide-sync",
        "uv pip install -U agno ddgs openai valkey-glide-sync",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-agent.mdx",
        """from agno.tools.hackernews import HackerNewsTools

# Initialize Valkey db""",
        """from agno.tools.websearch import WebSearchTools

# Initialize Valkey db""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-agent.mdx",
        "tools=[HackerNewsTools()]",
        "tools=[WebSearchTools()]",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-team.mdx",
        "uv pip install -U agno openai valkey-glide-sync",
        "uv pip install -U agno ddgs openai valkey-glide-sync",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-team.mdx",
        "Run: `uv pip install openai agno valkey-glide-sync` to install the dependencies",
        "Run: `uv pip install openai agno ddgs valkey-glide-sync` to install the dependencies",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-team.mdx",
        """from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel""",
        """from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-team.mdx",
        """role="Searches the web for information on a topic",
    tools=[HackerNewsTools()],""",
        """role="Searches the web for information on a topic",
    tools=[WebSearchTools()],""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-workflow.mdx",
        "uv pip install -U agno fastapi openai valkey-glide-sync",
        "uv pip install -U agno ddgs fastapi openai valkey-glide-sync",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-workflow.mdx",
        "Run: `uv pip install openai agno valkey-glide-sync fastapi` to install the dependencies",
        "Run: `uv pip install openai agno ddgs valkey-glide-sync fastapi` to install the dependencies",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-workflow.mdx",
        """from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step""",
        """from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step""",
    )
    root_sub(
        "database/providers/valkey/usage/valkey-for-workflow.mdx",
        """tools=[HackerNewsTools()],
    role="Search the web for the latest news and trends",""",
        """tools=[WebSearchTools()],
    role="Search the web for the latest news and trends",""",
    )
    sub(
        "storage/valkey/valkey-for-team.mdx",
        "Run `uv pip install ddgs valkey-glide-sync` to install dependencies.",
        "Run `uv pip install ddgs openai valkey-glide-sync` to install dependencies.",
    )
    valkey_descriptions = {
        "agent": "Use Valkey as the storage backend for an agent.",
        "team": "Use Valkey as the storage backend for a team.",
        "workflow": "Use ValkeyDb as the session storage backend for a workflow.",
    }
    for example_type, description in valkey_descriptions.items():
        sub(
            f"storage/valkey/valkey-for-{example_type}.mdx",
            f'description: "{description}"\n---',
            f'description: "{description}"\nsource: cookbook/06_storage/valkey/valkey_for_{example_type}.py\n---',
        )
    for example_type in ("agent", "team", "workflow"):
        filename = f"valkey_for_{example_type}.py"
        root_sub(
            f"examples/storage/valkey/valkey-for-{example_type}.mdx",
            f"""## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/06_storage/valkey

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python {filename}
```""",
            f"""## Run the Example

<Steps>
  <Step title="Clone Agno">
    Clone the repository and run the remaining commands from its root:
    ```bash
    git clone https://github.com/agno-agi/agno.git
    cd agno
    ```
  </Step>

  <Step title="Set up the demo environment">
    ```bash
    ./scripts/demo_setup.sh
    source .venvs/demo/bin/activate
    uv pip install -U ddgs openai valkey-glide-sync
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash Mac/Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run Valkey">
    ```bash
    docker run -d --name my-valkey -p 6379:6379 valkey/valkey-bundle
    ```
  </Step>

  <Step title="Run the example">
    ```bash
    python cookbook/06_storage/valkey/{filename}
    ```
  </Step>
</Steps>""",
        )
    sub(
        "agent-os/dbs/valkey-db.mdx",
        "```python\n",
        "```python valkey_db.py\n",
    )
    sub(
        "agent-os/dbs/valkey-db.mdx",
        'description: "Setup the Valkey database."\n---',
        'description: "Setup the Valkey database."\nsource: cookbook/05_agent_os/dbs/valkey_db.py\n---',
    )
    sub(
        "agent-os/dbs/valkey-db.mdx",
        """## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/05_agent_os/dbs

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python valkey_db.py
```""",
        """## Run the Example

<Steps>
  <Step title="Clone Agno">
    Clone the repository and run the remaining commands from its root:
    ```bash
    git clone https://github.com/agno-agi/agno.git
    cd agno
    ```
  </Step>

  <Step title="Set up the demo environment">
    ```bash
    ./scripts/demo_setup.sh
    source .venvs/demo/bin/activate
    uv pip install -U valkey-glide-sync
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash Mac/Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run Valkey">
    ```bash
    docker run -d --name my-valkey -p 6379:6379 valkey/valkey-bundle
    ```
  </Step>

  <Step title="Run the example">
    Run the example from the repository root:
    ```bash
    python cookbook/05_agent_os/dbs/valkey_db.py
    ```
  </Step>
</Steps>

Full source: [cookbook/05_agent_os/dbs/valkey_db.py](https://github.com/agno-agi/agno/blob/main/cookbook/05_agent_os/dbs/valkey_db.py)""",
    )

    root_sub(
        "knowledge/vector-stores/mongodb/usage/mongo-db-hybrid-search.mdx",
        """  </Step>
  <Step title="Set environment variables">""",
        """  </Step>
  <Step title="Create the keyword search index">
    Hybrid search requires a keyword Search index named `default` in addition to the vector index Agno creates. Wait for MongoDB, create the collection if needed, then create the index and wait until it is queryable:
    ```bash
    until [ "$(docker inspect --format='{{.State.Health.Status}}' mongodb-container)" = "healthy" ]; do
      sleep 1
    done

    docker exec mongodb-container mongosh --quiet --eval '
    const database = db.getSiblingDB("agno");
    if (!database.getCollectionNames().includes("recipes")) {
      database.createCollection("recipes");
    }
    if (!database.recipes.aggregate([
      { $listSearchIndexes: { name: "default" } }
    ]).hasNext()) {
      database.recipes.createSearchIndex("default", {
        mappings: {
          dynamic: false,
          fields: { content: { type: "string" } }
        }
      });
    }
    while (!database.recipes.aggregate([
      { $listSearchIndexes: { name: "default" } }
    ]).toArray()[0]?.queryable) {
      sleep(1000);
    }
    '
    ```
  </Step>
  <Step title="Set environment variables">""",
    )
    root_sub(
        "multimodal/agent/usage/audio-streaming.mdx",
        """  </Step>

  <Step title="Run Agent">""",
        """  </Step>

  <Step title="Create the output directory">
    ```bash
    python -c "from pathlib import Path; Path('tmp').mkdir(parents=True, exist_ok=True)"
    ```
  </Step>

  <Step title="Run Agent">""",
    )
    root_sub(
        "multimodal/agent/usage/audio-streaming.mdx",
        """## Key Features

- **Real-time Audio Streaming**: Streams audio responses in real-time using OpenAI's `gpt-audio` model
- **PCM16 Audio Format**: Uses high-quality PCM16 format for audio streaming
- **Transcript Generation**: Provides simultaneous text transcription of generated audio
- **WAV File Creation**: Saves streamed audio directly to a WAV file format
- **Error Handling**: Includes robust error handling for audio decoding

## Use Cases

- Interactive voice assistants
- Real-time storytelling applications
- Audio content generation
- Voice-enabled chatbots
- Dynamic audio responses for applications

## Technical Details

The example configures audio streaming with 24kHz sample rate, mono channel, and 16-bit sample width. The streaming approach allows for real-time audio playback while maintaining high audio quality through the PCM16 format.""",
        """## Key Features

- **Streamed output**: Consumes audio chunks as the model returns them
- **PCM16 format**: Writes 16-bit PCM audio at 24 kHz in mono
- **Transcript output**: Prints transcript chunks as they arrive
- **WAV file**: Saves the audio stream to `tmp/response_stream.wav`
- **Decode failures**: Prints chunk decoding failures and continues consuming the stream

## Next Steps

| Task | Guide |
|------|-------|
| Send and receive audio | [Audio Input and Output](/multimodal/agent/usage/audio-input-output) |
| Transcribe audio | [Audio to Text](/multimodal/agent/usage/audio-to-text) |
| Continue an audio conversation | [Audio Multi-Turn](/multimodal/agent/usage/audio-multi-turn) |

## Output Format

The agent writes 24 kHz, mono, 16-bit PCM audio to `tmp/response_stream.wav`. The script saves the stream to disk. It does not play the audio.""",
    )

    sub(
        "tools/mcp/pipedream-linkedin.mdx",
        """## Run the Example

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Install dependencies">
    ```bash
    uv pip install -U "agno[mcp]" openai
    ```
  </Step>

  <Step title="Export environment variables">
    <CodeGroup>
    ```bash Mac/Linux
    export MCP_SERVER_URL="your_mcp_server_url_here"
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:MCP_SERVER_URL="your_mcp_server_url_here"
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run the example">
    Save the code above as `pipedream_linkedin.py`, then run:
    ```bash
    python pipedream_linkedin.py
    ```
  </Step>
</Steps>""",
        """## Current Status

<Warning>
  This v2.7.2 example uses Pipedream's retired per-app SSE URL. It cannot connect to the current Pipedream MCP service without code and authentication changes. See [Pipedream MCP](https://pipedream.com/docs/connect/mcp) for the current end-user and developer flows.
</Warning>""",
    )

    # Final convergence repairs for static and preserved pages.
    root_sub(
        "sessions/session-management.mdx",
        "Session management in Agno gives you control over how sessions are identified, named, and cached for optimal performance. Runs can pause for human-in-the-loop requirements and continue after those requirements are resolved.",
        "Session management controls how sessions are identified, named, read, and cached.",
    )
    root_sub(
        "sessions/session-management.mdx",
        "This gives you all messages for all runs in the session, including tool calls and system messages.",
        "By default, `get_messages()` skips paused, cancelled, and error runs plus messages already tagged as history. Agent sessions also skip regenerated runs. Team sessions skip member messages. Pass `skip_statuses=[]`, `skip_history_messages=False`, and, for teams, `skip_member_messages=False` to include those records.",
    )
    root_sub(
        "sessions/session-management.mdx",
        """<Warning>
This is only for development and testing purposes. It is not recommended for production use.
</Warning>""",
        """<Warning>
The cache belongs to one Agent or Team instance. Other workers and processes do not share it, and external session updates are not visible through the cached object. Use `cache_session` only when one long-lived instance owns the session. Leave it disabled for horizontally scaled or shared-session deployments.
</Warning>""",
    )
    sub(
        "tools/parallel-tools.mdx",
        "Deep research that takes a plain-language input and returns comprehensive, cited results. Use for multi-hop research that needs minutes (not seconds) and synthesis across many sources.",
        "Deep research that takes a plain-language input and returns comprehensive, cited results. Choose the processor by complexity and latency. `base` typically completes in 15 to 100 seconds, while higher tiers can take minutes.",
    )
    sub(
        "tools/parallel-tools.mdx",
        """  <Step title="Export the required API key">
    ```bash
    export PARALLEL_API_KEY=***
    ```
  </Step>""",
        """  <Step title="Export the required API keys">
    <CodeGroup>
    ```bash Mac/Linux
    export PARALLEL_API_KEY="your_parallel_api_key_here"
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:PARALLEL_API_KEY="your_parallel_api_key_here"
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>""",
    )
    root_sub(
        "tools/toolkits/others/mem0.mdx",
        """Set the `MEM0_API_KEY` environment variable to use the Mem0 Platform. You can get your API key from the [Mem0 dashboard](https://app.mem0.ai/dashboard/api-keys).

```shell
export MEM0_API_KEY=****
```""",
        """Set `MEM0_API_KEY` to use the Mem0 Platform. The example Agent uses Agno's default OpenAI model, so it also requires `OPENAI_API_KEY`. Get the Mem0 key from the [Mem0 dashboard](https://app.mem0.ai/dashboard/api-keys).

<CodeGroup>
```bash Mac/Linux
export MEM0_API_KEY="your_mem0_api_key_here"
export OPENAI_API_KEY="your_openai_api_key_here"
```

```bash Windows
$Env:MEM0_API_KEY="your_mem0_api_key_here"
$Env:OPENAI_API_KEY="your_openai_api_key_here"
```
</CodeGroup>""",
    )
    root_sub(
        "tools/toolkits/others/mem0.mdx",
        "Without an API key, the toolkit runs a local Mem0 `Memory` instance. Configure it with the `config` parameter.",
        "Without a Mem0 API key, the toolkit runs a local Mem0 `Memory` instance. Configure it with the `config` parameter.",
    )
    sub_all(
        "storage/mongo/mongodb-for-team.mdx",
        'model=OpenAIChat("gpt-5.4-mini"),',
        'model=OpenAIChat("gpt-4o"),',
        expected=3,
    )
    sub(
        "storage/mongo/mongodb-for-team.mdx",
        """~~~

## Run the Example""",
        """~~~

<Warning>
  The v2.7.2 cookbook uses the deprecated `gpt-4o` model. The source-fidelity fence above preserves those three model IDs. Replace all three with `gpt-5.4-mini` before running. See [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) and [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
</Warning>

## Run the Example""",
    )
    sub(
        "storage/mongo/mongodb-for-team.mdx",
        """## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/06_storage/mongo

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python mongodb_for_team.py
```""",
        """## Run the Example

<Steps>
  <Step title="Clone Agno">
    Clone the repository and run the remaining commands from its root:
    ```bash
    git clone https://github.com/agno-agi/agno.git
    cd agno
    ```
  </Step>

  <Step title="Set up the demo environment">
    ```bash
    ./scripts/demo_setup.sh
    source .venvs/demo/bin/activate
    uv pip install -U "pymongo[srv]"
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash Mac/Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Start MongoDB">
    ```bash
    ./cookbook/scripts/run_mongodb.sh
    ```
  </Step>

  <Step title="Run the example">
    ```bash
    python cookbook/06_storage/mongo/mongodb_for_team.py
    ```
  </Step>
</Steps>""",
    )
    root_sub(
        "deploy/templates/scout/overview.mdx",
        "| **Slack** | `SLACK_BOT_TOKEN` | `query_slack`. Read-only access to messages, channel history, threads, and users. |",
        "| **Slack** | `SLACK_BOT_TOKEN` | Intended to expose `query_slack` for read-only access. The pinned template also exposes `update_slack`; see the warning below. |",
    )
    root_sub(
        "deploy/templates/scout/overview.mdx",
        """| **MCP** | Registered in `scout/contexts.py` | One `query_mcp_<slug>` per server. |

Setup for each provider""",
        """| **MCP** | Registered in `scout/contexts.py` | One `query_mcp_<slug>` per server. |

<Warning>
  Scout intends Slack access to be read-only, but the pinned template does not pass `write=False` when it creates `SlackContextProvider`. Configuring Slack currently exposes `update_slack`. Leave write scopes ungranted until the template enforces its intended boundary.
</Warning>

Setup for each provider""",
    )
    root_sub(
        "deploy/templates/scout/overview.mdx",
        "Create the Slack app from the manifest in the README's [Chat with Scout in Slack](https://github.com/agno-agi/scout#chat-with-scout-in-slack) section.",
        "Create the Slack app from the manifest in Scout's [Slack setup guide](https://github.com/agno-agi/scout/blob/main/docs/SLACK_CONNECT.md).",
    )
    root_sub(
        "deploy/templates/scout/overview.mdx",
        "Setting `SLACK_BOT_TOKEN` on its own activates the read-only Slack context provider. Add `SLACK_SIGNING_SECRET` and the Slack interface lights up too, so Scout can reply in your workspace.",
        "Setting `SLACK_BOT_TOKEN` activates the Slack context provider. The pinned template also exposes `update_slack` as described above. Adding `SLACK_SIGNING_SECRET` enables the Slack interface so Scout can reply in your workspace.",
    )
    root_sub(
        "models/providers/gateways/groq/usage/translation-agent.mdx",
        """---

## Code""",
        """---

<Warning>
  This v2.7.2 source cannot run as written. It references an input file that is not provided, uses Groq's retired `playai-tts` default, asks for music even though the tool generates speech, and saves WAV bytes with an `.mp3` extension. Provide a real input file, select a current TTS model and voice, change the prompt to request speech, and save the output as `.wav`. See [Groq model deprecations](https://console.groq.com/docs/deprecations) and [Groq text to speech](https://console.groq.com/docs/text-to-speech/).
</Warning>

## Code""",
    )
    root_sub(
        "models/providers/gateways/groq/usage/translation-agent.mdx",
        """## Usage

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Set your API key">
    ```bash
    export GROQ_API_KEY=xxx
    export OPENAI_API_KEY=xxx
    ```
  </Step>

  <Step title="Install dependencies">
    ```bash
    uv pip install -U groq openai agno
    ```
  </Step>

  <Step title="Run Agent">
    Save the code above as `translation_agent.py`, then run:
    ```bash
    python translation_agent.py
    ```
  </Step>
</Steps>""",
        """## Prepare a corrected copy

The source fence is preserved for v2.7.2 fidelity. These packages and API keys cover its imports. Apply every change in the warning above before running it.

<Steps>
  <Step title="Install dependencies">
    ```bash
    uv pip install -U agno groq openai
    ```
  </Step>

  <Step title="Set API keys">
    <CodeGroup>
    ```bash macOS / Linux
    export GROQ_API_KEY="your_groq_api_key_here"
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```powershell Windows
    $Env:GROQ_API_KEY="your_groq_api_key_here"
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>
</Steps>""",
    )
    root_sub(
        "workflows/running-workflows.mdx",
        "See detailed documentation in the [WorkflowRunOutputEvent](/reference/workflows/run-output) documentation.",
        "See the [WorkflowRunOutputEvent](/reference/workflows/run-output) reference.",
    )

    # 7. The pinned Dakera client predates the current container authentication,
    #    routes, and recall response shape. Preserve the source but do not offer
    #    runnable instructions for an incompatible client.
    sub(
        "memory/integrations/dakera-integration.mdx",
        """## Run the Example

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Install dependencies">
    ```bash
    uv pip install -U agno openai
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash Mac/Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```bash Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run the example">
    Save the code above as `dakera_integration.py`, then run:
    ```bash
    python dakera_integration.py
    ```
  </Step>
</Steps>""",
        """## Current Status

<Warning>
  The current `ghcr.io/dakera-ai/dakera:latest` image requires `DAKERA_ROOT_API_KEY`. The pinned client uses `/v1/memories` and `/v1/memories/search`, while the current API uses `/v1/memory/store` and `/v1/memory/recall` and returns recalled entries under `memories`. Update the server environment, client authentication, routes, and response parsing before running this example.
</Warning>""",
    )

    # 8. Static-page corrections identified by the final randomized samples.
    sub(
        "tools/seltz-tools.mdx",
        'description: "Give an agent SeltzTools for fast, clean web data retrieval with results shown inline."',
        'description: "Search the web with SeltzTools and log raw tool results for debugging."',
    )
    sub(
        "tools/seltz-tools.mdx",
        "Enable Agno agents with Seltz to get fast, high-quality web data. It delivers clean context for better reasoning with enterprise-grade security and reliable speed.",
        "`SeltzTools` gives an agent Seltz web search. `show_results=True` logs each search query and raw result for debugging.",
    )
    sub(
        "tools/seltz-tools.mdx",
        """## Prerequisites

- Install dependencies: `pip install seltz agno openai python-dotenv`
- Set required environment variables: `export SELTZ_API_KEY=your_seltz_api_key` and `export OPENAI_API_KEY=your_openai_api_key`.""",
        """## Prerequisites

- Set required environment variables: `export SELTZ_API_KEY=your_seltz_api_key` and `export OPENAI_API_KEY=your_openai_api_key`.""",
    )
    sub(
        "tools/seltz-tools.mdx",
        """```python


from agno.agent import Agent""",
        '''```python
"""Seltz Tools Example.

Run `pip install seltz agno openai python-dotenv` to install dependencies.
"""

from agno.agent import Agent''',
    )
    sub(
        "tools/seltz-tools.mdx",
        """./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python cookbook/91_tools/seltz_tools.py""",
        """./scripts/demo_setup.sh
source .venvs/demo/bin/activate

uv pip install -U seltz

python cookbook/91_tools/seltz_tools.py""",
    )

    sub(
        "agents/approvals/approval-team.mdx",
        """| Both | Team and member | Two pauses, two separate admin approvals. |

<Tabs>""",
        """| Both | Team and member | Two pauses, two separate admin approvals. |

After starting an example, [connect the AgentOS UI](/agent-os/connect-your-os) to `http://localhost:7777` and start a team run. When the run pauses, open **Approvals**, complete any requested fields, approve the request, return to the run, and select **Continue Run**. Case 3 repeats the approval and continuation flow twice.

<Tabs>""",
    )
    sub(
        "agents/approvals/approval-team.mdx",
        """# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/02_agents/11_approvals

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python team_level_approval.py""",
        """# Clone and set up the repo
git clone https://github.com/agno-agi/agno.git
cd agno

# Create and activate the demo virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

export OPENAI_API_KEY="your_openai_api_key_here"

python cookbook/05_agent_os/approvals/team/team_level_approval.py""",
    )
    sub(
        "agents/approvals/approval-team.mdx",
        """# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/02_agents/11_approvals

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python member_agent_level_approval.py""",
        """# Clone and set up the repo
git clone https://github.com/agno-agi/agno.git
cd agno

# Create and activate the demo virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

export OPENAI_API_KEY="your_openai_api_key_here"

python cookbook/05_agent_os/approvals/team/member_agent_level_approval.py""",
    )
    sub(
        "agents/approvals/approval-team.mdx",
        """# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/02_agents/11_approvals

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python team_and_member_agent_both_level_approval.py""",
        """# Clone and set up the repo
git clone https://github.com/agno-agi/agno.git
cd agno

# Create and activate the demo virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

export OPENAI_API_KEY="your_openai_api_key_here"

python cookbook/05_agent_os/approvals/team/team_and_member_agent_both_level_approval.py""",
    )
    sub(
        "agents/approvals/approval-team.mdx",
        "</Tabs>",
        """</Tabs>

## Developer Resources

- [Team-level approval source](https://github.com/agno-agi/agno/blob/main/cookbook/05_agent_os/approvals/team/team_level_approval.py)
- [Member-level approval source](https://github.com/agno-agi/agno/blob/main/cookbook/05_agent_os/approvals/team/member_agent_level_approval.py)
- [Team and member approval source](https://github.com/agno-agi/agno/blob/main/cookbook/05_agent_os/approvals/team/team_and_member_agent_both_level_approval.py)""",
    )

    sub(
        "models/huggingface/overview.mdx",
        "[Hugging Face Llama Essay Writer](/examples/models/huggingface/llama-essay-writer)",
        "[Hugging Face GPT-OSS Essay Writer](/examples/models/huggingface/llama-essay-writer)",
    )

    root_sub(
        "state/agent/last-n-session-messages.mdx",
        '''title: Last N Messages
sidebarTitle: Last N Messages
mode: wide
description: "Limit an agent's session search to the last N past sessions to keep context length manageable."''',
        '''title: Limit Past Session Search
sidebarTitle: Limit Past Session Search
mode: wide
description: "Limit the number of prior session previews returned by search_past_sessions."''',
    )
    root_sub(
        "state/agent/last-n-session-messages.mdx",
        "Let the agent search through previous sessions and limit how many are included in context. This keeps context length manageable while preserving relevant conversation history.",
        "Register the `search_past_sessions` tool and limit how many prior session previews it returns. The previews are tool results that the agent can inspect when it chooses to search past sessions.",
    )
    root_sub(
        "state/agent/last-n-session-messages.mdx",
        """        add_history_to_context=True,
        num_history_runs=3,
        search_past_sessions=True,  # allow searching previous sessions
        num_past_sessions_to_search=2,  # only include the last 2 sessions in the search to avoid context length issues""",
        """        search_past_sessions=True,  # register the prior-session search tool
        num_past_sessions_to_search=2,  # return at most two prior session previews""",
    )
    root_sub(
        "state/agent/last-n-session-messages.mdx",
        """    )  # It should only include the last 2 sessions""",
        """    )  # The search tool can return at most two prior session previews.""",
    )

    root_sub(
        "database/providers/singlestore/usage/singlestore-for-agent.mdx",
        "Get your SingleStore credentials from the [SingleStore portal](https://portal.singlestore.com/).",
        """Get your SingleStore credentials from the [SingleStore portal](https://portal.singlestore.com/), then set the connection values and OpenAI API key:

<CodeGroup>
```bash macOS / Linux
export SINGLESTORE_USERNAME="your_singlestore_username"
export SINGLESTORE_PASSWORD="your_singlestore_password"
export SINGLESTORE_HOST="your_singlestore_host"
export SINGLESTORE_PORT="your_singlestore_port"
export SINGLESTORE_DATABASE="your_singlestore_database"
export OPENAI_API_KEY="your_openai_api_key_here"
```

```powershell Windows
$Env:SINGLESTORE_USERNAME="your_singlestore_username"
$Env:SINGLESTORE_PASSWORD="your_singlestore_password"
$Env:SINGLESTORE_HOST="your_singlestore_host"
$Env:SINGLESTORE_PORT="your_singlestore_port"
$Env:SINGLESTORE_DATABASE="your_singlestore_database"
$Env:OPENAI_API_KEY="your_openai_api_key_here"
```
</CodeGroup>""",
    )

    root_sub(
        "faq/rbac-auth-failed.mdx",
        "| AgentOS platform | `algorithm=\"RS256\"` or omit it (RS256 is the default). Platform-issued public keys are always RS256, so any other value fails verification. |",
        "| AgentOS Control Plane | `algorithm=\"RS256\"` or omit it (RS256 is the default). Control Plane-issued public keys are always RS256, so any other value fails verification. |",
    )
    root_sub(
        "faq/rbac-auth-failed.mdx",
        "Supported algorithms: `RS256` and `ES256` (asymmetric, public key), `HS256` (symmetric, shared secret).",
        "Supported algorithms: `RS256`, `RS384`, `RS512`, `HS256`, `HS384`, `HS512`, `ES256`, `ES384`, and `ES512`.",
    )
    root_sub(
        "faq/rbac-auth-failed.mdx",
        "A few scopes act as gates in the platform and a token missing any of them fails before finer-grained checks run.",
        "A few scopes act as gates in the AgentOS backend, and a token missing any of them fails before finer-grained checks run.",
    )
    root_sub(
        "faq/rbac-auth-failed.mdx",
        "The platform only supports security key authentication on these versions.",
        "The AgentOS Control Plane only supports security key authentication on these versions.",
    )

    root_sub(
        "reference/models/xai.mdx",
        """| `search_parameters` | `Optional[Dict[str, Any]]` | `None`          | Search configuration for xAI live search, sent in the request body    |

`xAI` extends""",
        """| `search_parameters` | `Optional[Dict[str, Any]]` | `None`          | Search configuration for xAI live search, sent in the request body    |

<Warning>
  `grok-4-1-fast-non-reasoning-latest` is retained here because it is the class default in the pinned source. xAI has retired this alias and redirects it to Grok 4.3. Use `xAI(id="grok-4.3", reasoning_effort="none")` for the equivalent current configuration.
</Warning>

`xAI` extends""",
    )
    root_sub(
        "reference/models/azure-open-ai.mdx",
        '| `id`                      | `str`             | `"not-provided"` | The id of the Azure OpenAI model to use. Set this to your model or deployment name   |',
        '| `id`                      | `str`             | `"not-provided"` | The Azure deployment name passed as the model ID. Set this to your deployment name  |',
    )

    root_sub(
        "deploy/templates/modal/reference.mdx",
        "| Tail logs | `modal app logs agentos` |",
        "| Tail logs | `modal app logs agentos --follow` |",
    )
    root_sub(
        "deploy/templates/modal/reference.mdx",
        """| Tear down | `./scripts/modal/down.sh` (add `--yes` to skip the confirmation) |

<Note>""",
        """| Tear down | `./scripts/modal/down.sh` |

<Warning>
  `down.sh --yes` skips only the wrapper script's confirmation. It does not pass `--yes` to `modal app stop`, so Modal may still prompt while stopping the app.
</Warning>

<Note>""",
    )
    root_sub(
        "deploy/templates/modal/reference.mdx",
        "anyone who guesses your modal.run URL can access your platform.",
        "anyone who guesses your modal.run URL can access your AgentOS backend.",
    )

    root_sub(
        "models/providers/cloud/vertexai-claude/usage/basic.mdx",
        'Claude(id="claude-sonnet-4@20250514")',
        'Claude(id="claude-sonnet-4-6")',
    )
    root_sub(
        "models/providers/cloud/vertexai-claude/usage/basic.mdx",
        """    ```bash Windows
    setx CLOUD_ML_REGION xxx
    setx GOOGLE_CLOUD_PROJECT xxx
    ```""",
        """    ```powershell Windows
    $Env:CLOUD_ML_REGION="xxx"
    $Env:GOOGLE_CLOUD_PROJECT="xxx"
    ```""",
    )

    root_sub(
        "use-cases/document-processing/forms-and-intake.mdx",
        """Forms and intake documents bring a different shape: a person's identity at the top, then several parallel lists (employment, education, skills, references). The agent fills out the nested structure in one pass.

```python""",
        """Forms and intake documents bring a different shape: a person's identity at the top, then several parallel lists (employment, education, skills, references). The agent fills out the nested structure in one pass.

Place the resume to extract at `resume.pdf` in the directory where you run this code.

```python""",
    )
    root_sub(
        "use-cases/document-processing/forms-and-intake.mdx",
        'files=[File(url="https://example.com/resume-sjohnson.pdf")]',
        'files=[File(filepath="resume.pdf")]',
    )
    root_sub(
        "use-cases/document-processing/forms-and-intake.mdx",
        "# Resume(full_name='Sarah Johnson', email='sarah@example.com',",
        "# Illustrative output. Your values depend on resume.pdf:\n# Resume(full_name='Sarah Johnson', email='sarah@example.com',",
    )

    root_sub(
        "tools/creating-tools/overview.mdx",
        """There are two main ways to create tools in Agno:
1. Create a python function""",
        """There are two main ways to create tools in Agno:

1. Create a Python function""",
    )

    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        "agent_os = AgentOS(agents=[agent], db=db)",
        """agent_os = AgentOS(
    agents=[agent],
    db=db,
    cors_allowed_origins=[
        "http://localhost:3000",
        "https://app.yourproduct.com",
        "https://os.agno.com",
    ],
)""",
    )
    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        """if __name__ == "__main__":
    agent_os.serve(app="copilot:app", port=7777)
```

## Calling it from a surface""",
        """if __name__ == "__main__":
    agent_os.serve(app="copilot:app", port=7777)
```

Supplying `cors_allowed_origins` replaces the AgentOS defaults. Include every browser and AgentOS UI origin that needs to call the backend.

## Run the API

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Install dependencies">
    ```bash
    uv pip install -U "agno[os]" openai sqlalchemy "psycopg[binary]"
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash macOS / Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```powershell Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Snippet file="run-pgvector-step.mdx" />

  <Step title="Start AgentOS">
    Save the code as `copilot.py`, then run:
    ```bash
    python copilot.py
    ```
  </Step>
</Steps>

## Calling it from a surface""",
    )
    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        "async function askCopilot(message, threadId) {",
        "async function askCopilot(message, threadId, jwt) {",
    )
    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        "| Long job, poll later | `background=true` |",
        "| Long job, poll later | `background=true` and `stream=false` |",
    )
    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        """`AgentOS` is a FastAPI app. Add routes for webhooks, dashboards, or product-specific endpoints. The agent is a regular Python object you can call from anywhere.

```python
app = agent_os.get_app()


@app.post("/webhooks/stripe")
async def handle_stripe(event: dict):
    response = await agent.arun(f"Process Stripe event: {event}", user_id="system")
    return {"ok": True, "response": response.content}
```""",
        """`AgentOS` is a FastAPI app. Add routes for webhooks, dashboards, or product-specific endpoints. The agent is a regular Python object you can call from anywhere.

<Warning>
  A public Stripe webhook must read the raw request body and verify its `Stripe-Signature` with the endpoint secret before parsing or passing an event to the agent. Never accept an unverified decoded dictionary. See [Stripe's webhook signature guide](https://docs.stripe.com/webhooks/signature).
</Warning>""",
    )
    root_sub(
        "use-cases/product-agents/serve-as-an-api.mdx",
        """    authorization=True,
    authorization_config=AuthorizationConfig(user_isolation=True),""",
        """    authorization=True,
    authorization_config=AuthorizationConfig(user_isolation=True),
    cors_allowed_origins=[
        "http://localhost:3000",
        "https://app.yourproduct.com",
        "https://os.agno.com",
    ],""",
    )

    # Sample 29: correct static provider, interface, FAQ, and team pages.
    root_sub(
        "models/providers/native/google/usage/interactions-antigravity.mdx",
        "Unlike Deep Research, Antigravity runs in the foreground. The model still forces `store=True` so the interaction is retrievable.",
        "`GeminiInteractions` in Agno 2.7.2 sends Antigravity requests in the foreground and forces `store=True` so each interaction is retrievable. The Google API also supports background Antigravity execution. Use the Google Gen AI SDK directly when you need background execution.",
    )

    root_sub(
        "models/providers/gateways/huggingface/usage/llama-essay-writer.mdx",
        """title: Llama Essay Writer
description: Write a 300-word essay on a user-provided topic with a HuggingFace agent.""",
        """title: GPT-OSS Essay Writer
description: Write a 300-word essay on a user-provided topic with GPT-OSS 120B through Hugging Face.""",
    )

    root_sub(
        "use-cases/product-agents/interfaces.mdx",
        """| Telegram | `tg:<entity_id>:<chat_id>` with an optional topic suffix | Telegram user ID |
| WhatsApp | `wa:<entity_id>:<user_id>` | Phone number or encrypted user ID |""",
        """| Telegram | `tg:<entity_id>:<chat_id>[:<topic_id>][:<reset_id>]` | Telegram user ID |
| WhatsApp | `wa:<entity_id>:<user_id>[:<reset_id>]` | Phone number or encrypted user ID |""",
    )
    root_sub(
        "use-cases/product-agents/interfaces.mdx",
        """Stored memory can follow a user across surfaces when the interfaces resolve to the same `user_id` and use the same agent database and memory configuration. Session history remains scoped to each interface-generated `session_id`. Interfaces can add surface metadata and dependencies to a run.

## One agent, every surface""",
        """For Telegram and WhatsApp, `/new` preserves earlier sessions and creates a session whose ID has a new eight-character suffix. This command requires a database.

Stored memory can follow a user across surfaces when the interfaces resolve to the same `user_id` and use the same agent database and memory configuration. Session history remains scoped to each interface-generated `session_id`. Interfaces can add surface metadata and dependencies to a run.

## One agent, every surface""",
    )
    root_sub(
        "use-cases/product-agents/interfaces.mdx",
        """from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.whatsapp import Whatsapp""",
        """from agno.os.interfaces.a2a import A2A
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.whatsapp import Whatsapp""",
    )
    root_sub(
        "use-cases/product-agents/interfaces.mdx",
        """        Slack(agent=agent, token=..., signing_secret=...),
        Telegram(agent=agent, token=...),
        Whatsapp(agent=agent, access_token=..., verify_token=...),
        AGUI(agent=agent),""",
        """        Slack(agent=agent, token="xoxb-your-token", signing_secret="your-signing-secret"),
        Telegram(agent=agent, token="your-bot-token"),
        Whatsapp(
            agent=agent,
            access_token="your-access-token",
            phone_number_id="your-phone-number-id",
            verify_token="your-verify-token",
        ),
        AGUI(agent=agent),
        A2A(agents=[agent]),""",
    )

    root_sub(
        "faq/connecting-to-tableplus.mdx",
        """## Step 2: Configure TablePlus

1. Launch TablePlus.""",
        """## Step 2: Create the Session Table

Agno creates database tables when a database-backed feature first uses them. Run this example to create the default `agno_sessions` table:

```python create_session.py
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    db=db,
)
agent.print_response("What is the capital of France?", session_id="tableplus-demo")
```

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Install dependencies">
    ```bash
    uv pip install -U agno openai "psycopg[binary]" sqlalchemy
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash macOS / Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```powershell Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run the example">
    Save the code as `create_session.py`, then run:
    ```bash
    python create_session.py
    ```
  </Step>
</Steps>

Only table types exercised against this database appear. Run the [Postgres memory guide](/memory/working-with-memories/postgres-memory) to create memory tables and the [PgVector guide](/knowledge/vector-stores/pgvector/overview) to create knowledge tables.

## Step 3: Configure TablePlus

1. Launch TablePlus.""",
    )
    root_sub(
        "faq/connecting-to-tableplus.mdx",
        '<img src="/images/tableplus.png" />',
        '<img src="/images/tableplus.png" alt="TablePlus PostgreSQL connection settings" />',
    )

    root_sub(
        "teams/running-teams.mdx",
        """```

## Execution Flow""",
        """```

## Run the example

<Steps>
  <Snippet file="create-venv-step.mdx" />

  <Step title="Install dependencies">
    ```bash
    uv pip install -U agno openai yfinance
    ```
  </Step>

  <Step title="Export your OpenAI API key">
    <CodeGroup>
    ```bash macOS / Linux
    export OPENAI_API_KEY="your_openai_api_key_here"
    ```

    ```powershell Windows
    $Env:OPENAI_API_KEY="your_openai_api_key_here"
    ```
    </CodeGroup>
  </Step>

  <Step title="Run the example">
    Save the code as `running_team.py`, then run:
    ```bash
    python running_team.py
    ```
  </Step>
</Steps>

## Execution Flow""",
    )
    root_sub(
        "teams/running-teams.mdx",
        'images=[Image(url="https://example.com/image.jpg")]',
        'images=[Image(url="https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg")]',
    )
    root_sub(
        "teams/running-teams.mdx",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno retains up to 10,000 events per run in memory and persists run events through the database. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno retains up to 10,000 events per run in memory for reconnection while the AgentOS process remains alive. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        required=False,
    )
    root_sub(
        "teams/running-teams.mdx",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno buffers stream events in the database. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno retains up to 10,000 events per run in memory for reconnection while the AgentOS process remains alive. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        required=False,
    )
    root_sub(
        "teams/running-teams.mdx",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so AgentOS can persist run state. With `stream=True`, AgentOS buffers stream events in the database. After a disconnect, the client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno retains up to 10,000 events per run in memory for reconnection while the AgentOS process remains alive. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        required=False,
    )
    root_sub(
        "teams/running-teams.mdx",
        """Run teams in the background with `arun(background=True)`. The team continues running even if the client disconnects. Combine with `stream=True` for resumable SSE streaming with automatic event buffering and reconnection.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
        """Run teams in the background with `arun(background=True)`. Background execution requires a database so Agno can persist run state. With `stream=True`, Agno retains up to 10,000 events per run in memory for reconnection while the AgentOS process remains alive. After a disconnect, an AgentOS client calls the run's `/resume` endpoint with the last received event index.

See [Background Execution](/background-execution/overview) for polling, resumable streaming, and the `/resume` endpoint.""",
    )

    # Sample 29: configure LangDB's current endpoint without changing the
    # pinned source default documented in the parameter table.
    root_sub(
        "models/providers/gateways/langdb/overview.mdx",
        """description: Use LangDB AI Gateway to access 350+ LLMs with Agno agents.
---

[LangDB](https://langdb.ai/) is an AI Gateway that provides access to 350+ LLMs through OpenAI-compatible APIs, with tools to secure, govern, and optimize AI traffic.

For detailed integration instructions, see the [LangDB Agno documentation](https://docs.langdb.ai/getting-started/working-with-agent-frameworks/working-with-agno).""",
        """description: "Use the LangDB AI Gateway with Agno agents."
---

[LangDB](https://langdb.ai/) routes model requests through an OpenAI-compatible AI gateway. See [LangDB's Agno integration guide](https://docs.langdb.ai/getting-started/working-with-agent-frameworks/working-with-agno) for gateway configuration.""",
    )
    root_sub(
        "models/providers/gateways/langdb/overview.mdx",
        "Set your `LANGDB_API_KEY` and `LANGDB_PROJECT_ID` environment variables. Get your key from [here](https://app.langdb.ai/settings/api_keys).",
        "Create an API key in [LangDB API key settings](https://app.langdb.ai/settings/api_keys), then export the gateway credentials and API base URL.",
    )
    root_sub(
        "models/providers/gateways/langdb/overview.mdx",
        """<CodeGroup>

```bash Mac
export LANGDB_API_KEY=***
export LANGDB_PROJECT_ID=***

```

```bash Windows
setx LANGDB_API_KEY ***
setx LANGDB_PROJECT_ID ***
```

</CodeGroup>""",
        """<CodeGroup>

```bash macOS / Linux
export LANGDB_API_KEY="your_langdb_api_key"
export LANGDB_PROJECT_ID="your_langdb_project_id"
export LANGDB_API_BASE_URL="https://api.langdb.ai"
```

```powershell Windows
$Env:LANGDB_API_KEY="your_langdb_api_key"
$Env:LANGDB_PROJECT_ID="your_langdb_project_id"
$Env:LANGDB_API_BASE_URL="https://api.langdb.ai"
```

</CodeGroup>""",
    )
    root_sub(
        "models/providers/gateways/langdb/overview.mdx",
        "<Note> View more examples [here](/models/providers/gateways/langdb/usage/basic). </Note>",
        "See the [LangDB usage examples](/models/providers/gateways/langdb/usage/basic).",
    )
    root_sub(
        "models/providers/gateways/langdb/overview.mdx",
        "The id of the model to use through LangDB",
        "The ID of the model to use through LangDB",
    )

    langdb_usage_pages = (
        "models/providers/gateways/langdb/usage/basic-stream.mdx",
        "models/providers/gateways/langdb/usage/basic.mdx",
        "models/providers/gateways/langdb/usage/data-analyst.mdx",
        "models/providers/gateways/langdb/usage/structured-output.mdx",
        "models/providers/gateways/langdb/usage/tool-use.mdx",
    )
    for path in langdb_usage_pages:
        root_sub(
            path,
            """  <Step title="Set your API key">
    ```bash
    export LANGDB_API_KEY=xxx
    export LANGDB_PROJECT_ID=xxx
    ```
  </Step>""",
            """  <Step title="Export environment variables">
    ```bash
    export LANGDB_API_KEY="your_langdb_api_key"
    export LANGDB_PROJECT_ID="your_langdb_project_id"
    export LANGDB_API_BASE_URL="https://api.langdb.ai"
    ```
  </Step>""",
        )

    root_sub(
        "models/providers/gateways/langdb/usage/tool-use.mdx",
        'agent.print_response("Whats happening in France?", stream=True)',
        'agent.print_response("What\'s happening in France?", stream=True)',
    )

    # Sample 29: require an explicit current Nebius model because both the
    # retired cookbook ID and the pinned Agno 2.7.2 default are unavailable.
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """Nebius Token Factory is a platform from Nebius that simplifies the process of building applications using AI models. It provides a suite of tools and services for developers to easily test, integrate and fine-tune various AI models, including those for text and image generation.
You can check out the list of available models [here](https://tokenfactory.nebius.com/).

We recommend experimenting to find the best-suited model for your use case.""",
        """Nebius Token Factory provides OpenAI-compatible inference for hosted models. Browse the [model catalog](https://tokenfactory.nebius.com/), query the [model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models), and check [function-calling support](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) before selecting a model.""",
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        "Create an API key in the [Nebius Token Factory console](https://tokenfactory.nebius.com/?modals=create-api-key), then export the key and a current model ID.",
        "Create an API key in the [Nebius Token Factory console](https://tokenfactory.nebius.com/?modals=create-api-key), then export the key and a current text-generation model ID.",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        "Set your `NEBIUS_API_KEY` environment variable. Get your key [from Nebius Token Factory here](https://tokenfactory.nebius.com/?modals=create-api-key).",
        "Create an API key in the [Nebius Token Factory console](https://tokenfactory.nebius.com/?modals=create-api-key), then export the key and a current text-generation model ID.",
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """<CodeGroup>

```bash macOS / Linux
export NEBIUS_API_KEY="your_nebius_api_key"
export NEBIUS_MODEL_ID="your_current_model_id"
```

```powershell Windows
$Env:NEBIUS_API_KEY="your_nebius_api_key"
$Env:NEBIUS_MODEL_ID="your_current_model_id"
```

</CodeGroup>""",
        """<CodeGroup>

```bash macOS / Linux
export NEBIUS_API_KEY="your_nebius_api_key"
export NEBIUS_MODEL_ID="your_current_text_model_id"
```

```powershell Windows
$Env:NEBIUS_API_KEY="your_nebius_api_key"
$Env:NEBIUS_MODEL_ID="your_current_text_model_id"
```

</CodeGroup>""",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """<CodeGroup>

```bash Mac
export NEBIUS_API_KEY=***
```

```bash Windows
setx NEBIUS_API_KEY ***
```

</CodeGroup>""",
        """<CodeGroup>

```bash macOS / Linux
export NEBIUS_API_KEY="your_nebius_api_key"
export NEBIUS_MODEL_ID="your_current_text_model_id"
```

```powershell Windows
$Env:NEBIUS_API_KEY="your_nebius_api_key"
$Env:NEBIUS_MODEL_ID="your_current_text_model_id"
```

</CodeGroup>""",
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        '        id=os.environ["NEBIUS_MODEL_ID"]\n',
        '        id=os.environ["NEBIUS_MODEL_ID"],\n',
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """        id="meta-llama/Llama-3.3-70B-Instruct",
        api_key=os.getenv("NEBIUS_API_KEY")""",
        '        id=os.environ["NEBIUS_MODEL_ID"],',
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """See the [Nebius usage examples](/models/providers/gateways/nebius/usage/basic-stream).

<Warning>
  The pinned Agno 2.7.2 default, `openai/gpt-oss-20b`, is retired from serverless inference. Set `id` to an explicit current model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).
</Warning>""",
        """See the [Nebius usage examples](/models/providers/gateways/nebius/usage/basic-stream).

<Warning>
  The pinned Agno 2.7.2 default, `openai/gpt-oss-20b`, is retired from serverless inference. Set `id` to an explicit current text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).
</Warning>""",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        """See the [Nebius usage examples](/models/providers/gateways/nebius/usage/basic-stream).

<Warning>
  The pinned Agno 2.7.2 default, `openai/gpt-oss-20b`, is retired. Set `id` to an explicit current model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).
</Warning>""",
        """See the [Nebius usage examples](/models/providers/gateways/nebius/usage/basic-stream).

<Warning>
  The pinned Agno 2.7.2 default, `openai/gpt-oss-20b`, is retired from serverless inference. Set `id` to an explicit current text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).
</Warning>""",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/overview.mdx",
        "<Note> View more examples [here](/models/providers/gateways/nebius/usage/basic-stream). </Note>",
        """See the [Nebius usage examples](/models/providers/gateways/nebius/usage/basic-stream).

<Warning>
  The pinned Agno 2.7.2 default, `openai/gpt-oss-20b`, is retired from serverless inference. Set `id` to an explicit current text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).
</Warning>""",
    )

    nebius_usage_pages = (
        "models/providers/gateways/nebius/usage/basic-stream.mdx",
        "models/providers/gateways/nebius/usage/basic.mdx",
        "models/providers/gateways/nebius/usage/knowledge.mdx",
        "models/providers/gateways/nebius/usage/storage.mdx",
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        "models/providers/gateways/nebius/usage/tool-use.mdx",
    )
    for path in nebius_usage_pages:
        if path != "models/providers/gateways/nebius/usage/structured-output.mdx":
            root_sub(
                path,
                "from agno.agent import",
                "import os\n\nfrom agno.agent import",
            )
        if path == "models/providers/gateways/nebius/usage/knowledge.mdx":
            root_sub(
                path,
                """  <Step title="Export environment variables">
    Select an available model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models). `PgVector` uses `OpenAIEmbedder` by default, so this example also requires an OpenAI API key.

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_model_id"
    export OPENAI_API_KEY="your_openai_api_key"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_model_id"
    $Env:OPENAI_API_KEY="your_openai_api_key"
    ```
    </CodeGroup>
  </Step>""",
                """  <Step title="Export environment variables">
    Select an available text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models). `PgVector` uses `OpenAIEmbedder` by default, so this example also requires an OpenAI API key.

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_text_model_id"
    export OPENAI_API_KEY="your_openai_api_key"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_text_model_id"
    $Env:OPENAI_API_KEY="your_openai_api_key"
    ```
    </CodeGroup>
  </Step>""",
                required=False,
            )
            root_sub(
                path,
                """  <Step title="Export environment variables">
    Select an available model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_model_id"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_model_id"
    ```
    </CodeGroup>
  </Step>""",
                """  <Step title="Export environment variables">
    Select an available text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models). `PgVector` uses `OpenAIEmbedder` by default, so this example also requires an OpenAI API key.

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_text_model_id"
    export OPENAI_API_KEY="your_openai_api_key"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_text_model_id"
    $Env:OPENAI_API_KEY="your_openai_api_key"
    ```
    </CodeGroup>
  </Step>""",
                required=False,
            )
            root_sub(
                path,
                """  <Step title="Set your API key">
    ```bash
    export NEBIUS_API_KEY=xxx
    ```
  </Step>""",
                """  <Step title="Export environment variables">
    Select an available text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models). `PgVector` uses `OpenAIEmbedder` by default, so this example also requires an OpenAI API key.

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_text_model_id"
    export OPENAI_API_KEY="your_openai_api_key"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_text_model_id"
    $Env:OPENAI_API_KEY="your_openai_api_key"
    ```
    </CodeGroup>
  </Step>""",
            )
        else:
            root_sub(
                path,
                """  <Step title="Export environment variables">
    Select an available model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_model_id"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_model_id"
    ```
    </CodeGroup>
  </Step>""",
                """  <Step title="Export environment variables">
    Select an available text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_text_model_id"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_text_model_id"
    ```
    </CodeGroup>
  </Step>""",
                required=False,
            )
            root_sub(
                path,
                """  <Step title="Set your API key">
    ```bash
    export NEBIUS_API_KEY=xxx
    ```
  </Step>""",
                """  <Step title="Export environment variables">
    Select an available text-generation model ID from the [Nebius model-list API](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models).

    <CodeGroup>
    ```bash macOS / Linux
    export NEBIUS_API_KEY="your_nebius_api_key"
    export NEBIUS_MODEL_ID="your_current_text_model_id"
    ```

    ```powershell Windows
    $Env:NEBIUS_API_KEY="your_nebius_api_key"
    $Env:NEBIUS_MODEL_ID="your_current_text_model_id"
    ```
    </CodeGroup>
  </Step>""",
            )

    root_sub(
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        "from typing import List\n\nimport os\n\nfrom agno.agent import",
        "import os\nfrom typing import List\n\nfrom agno.agent import",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        "from typing import List\n\nfrom agno.agent import",
        "import os\nfrom typing import List\n\nfrom agno.agent import",
    )
    for path in (
        "models/providers/gateways/nebius/usage/basic-stream.mdx",
        "models/providers/gateways/nebius/usage/basic.mdx",
        "models/providers/gateways/nebius/usage/storage.mdx",
    ):
        root_sub(
            path,
            "model=Nebius()",
            'model=Nebius(id=os.environ["NEBIUS_MODEL_ID"])',
        )

    for path in (
        "models/providers/gateways/nebius/usage/knowledge.mdx",
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        "models/providers/gateways/nebius/usage/tool-use.mdx",
    ):
        root_sub(
            path,
            'model=Nebius(id="Qwen/Qwen3-30B-A3B")',
            'model=Nebius(id=os.environ["NEBIUS_MODEL_ID"])',
        )

    root_sub(
        "models/providers/gateways/nebius/usage/knowledge.mdx",
        'description: "Answer questions from a PDF using a Nebius Qwen3-30B-A3B agent and PgVector."',
        'description: "Answer questions from a PDF using a Nebius agent and PgVector."',
    )
    for path in (
        "models/providers/gateways/nebius/usage/knowledge.mdx",
        "models/providers/gateways/nebius/usage/storage.mdx",
    ):
        root_sub(
            path,
            "```\n\n## Usage",
            """```

Select a text-generation model with [function-calling support](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) for this example.

## Usage""",
        )
    root_sub(
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        'description: "Return a validated Pydantic MovieScript from a Nebius Qwen3-30B-A3B agent using output_schema."',
        'description: "Return a validated Pydantic MovieScript from a Nebius agent using output_schema."',
    )
    root_sub(
        "models/providers/gateways/nebius/usage/structured-output.mdx",
        "```\n\n## Usage",
        """```

Select a text-generation model with [JSON mode support](https://docs.tokenfactory.nebius.com/ai-models-inference/json) for this example.

## Usage""",
    )
    root_sub(
        "models/providers/gateways/nebius/usage/tool-use.mdx",
        'description: "Give a Nebius Qwen3-30B-A3B agent web search with WebSearchTools."',
        'description: "Give a Nebius agent web search with WebSearchTools."',
    )
    root_sub(
        "models/providers/gateways/nebius/usage/tool-use.mdx",
        'agent.print_response("Whats happening in France?", stream=True)',
        'agent.print_response("What\'s happening in France?", stream=True)',
    )
    root_sub(
        "models/providers/gateways/nebius/usage/tool-use.mdx",
        "Select a model with [function-calling support](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) for this example.",
        "Select a text-generation model with [function-calling support](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) for this example.",
        required=False,
    )
    root_sub(
        "models/providers/gateways/nebius/usage/tool-use.mdx",
        """```

## Usage""",
        """```

Select a text-generation model with [function-calling support](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) for this example.

## Usage""",
    )

    # Randomized convergence sample 30: keep provider examples runnable as
    # external model catalogs and APIs change independently of the pinned tag.
    root_sub(
        "examples/models/together/overview.mdx",
        "---\n| Example | Description |",
        """---

<Warning>
Together retires serverless model IDs on a rolling schedule. The Agno 2.7.2 cookbook examples may reference retired IDs. Before running an example, choose a current model from the [serverless catalog](https://docs.together.ai/docs/serverless/models) and verify the capabilities required by that example.
</Warning>

| Example | Description |""",
    )

    together_usage_pages = (
        "models/providers/gateways/together/usage/basic-stream.mdx",
        "models/providers/gateways/together/usage/basic.mdx",
        "models/providers/gateways/together/usage/image-agent-bytes.mdx",
        "models/providers/gateways/together/usage/image-agent-memory.mdx",
        "models/providers/gateways/together/usage/image-agent.mdx",
        "models/providers/gateways/together/usage/structured-output.mdx",
        "models/providers/gateways/together/usage/tool-use.mdx",
    )
    for path in (
        "models/providers/gateways/together/usage/basic.mdx",
        "models/providers/gateways/together/usage/image-agent-memory.mdx",
        "models/providers/gateways/together/usage/image-agent.mdx",
        "models/providers/gateways/together/usage/tool-use.mdx",
    ):
        root_sub(path, "from agno.agent import", "import os\n\nfrom agno.agent import")
    root_sub(
        "models/providers/gateways/together/usage/basic-stream.mdx",
        "from typing import Iterator  # noqa\nimport os\n\nfrom agno.agent import",
        "import os\nfrom typing import Iterator  # noqa\n\nfrom agno.agent import",
        required=False,
    )
    root_sub(
        "models/providers/gateways/together/usage/basic-stream.mdx",
        "from typing import Iterator  # noqa\nfrom agno.agent import",
        "import os\nfrom typing import Iterator  # noqa\n\nfrom agno.agent import",
    )
    root_sub(
        "models/providers/gateways/together/usage/image-agent-bytes.mdx",
        "from pathlib import Path\n\nfrom agno.agent import",
        "import os\nfrom pathlib import Path\n\nfrom agno.agent import",
    )
    root_sub(
        "models/providers/gateways/together/usage/structured-output.mdx",
        "from typing import List\n\nfrom agno.agent import",
        "import os\nfrom typing import List\n\nfrom agno.agent import",
    )
    for path in together_usage_pages:
        root_sub(
            path,
            "    export TOGETHER_API_KEY=xxx",
            "    export TOGETHER_API_KEY=xxx\n    export TOGETHER_MODEL_ID=your-model-id",
        )
    for path in (
        "models/providers/gateways/together/usage/basic-stream.mdx",
        "models/providers/gateways/together/usage/basic.mdx",
        "models/providers/gateways/together/usage/structured-output.mdx",
        "models/providers/gateways/together/usage/tool-use.mdx",
    ):
        root_sub(
            path,
            'model=Together(id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo")',
            'model=Together(id=os.environ["TOGETHER_MODEL_ID"])',
        )
    for path in (
        "models/providers/gateways/together/usage/image-agent-bytes.mdx",
        "models/providers/gateways/together/usage/image-agent-memory.mdx",
        "models/providers/gateways/together/usage/image-agent.mdx",
    ):
        root_sub(
            path,
            'model=Together(id="meta-llama/Llama-Vision-Free")',
            'model=Together(id=os.environ["TOGETHER_MODEL_ID"])',
        )
    for path in (
        "models/providers/gateways/together/usage/basic-stream.mdx",
        "models/providers/gateways/together/usage/basic.mdx",
    ):
        root_sub(
            path,
            "```\n\n## Usage",
            """```

Set `TOGETHER_MODEL_ID` to a current chat model from the [Together serverless catalog](https://docs.together.ai/docs/serverless/models).

## Usage""",
        )
    for path in (
        "models/providers/gateways/together/usage/image-agent-bytes.mdx",
        "models/providers/gateways/together/usage/image-agent-memory.mdx",
        "models/providers/gateways/together/usage/image-agent.mdx",
    ):
        root_sub(
            path,
            "```\n\n## Usage",
            """```

Set `TOGETHER_MODEL_ID` to a current model that accepts image input. See the [Together vision guide](https://docs.together.ai/docs/inference/vision/overview) and [serverless catalog](https://docs.together.ai/docs/serverless/models).

## Usage""",
        )
    root_sub(
        "models/providers/gateways/together/usage/structured-output.mdx",
        "```\n\n## Usage",
        """```

Set `TOGETHER_MODEL_ID` to a current model with [structured-output support](https://docs.together.ai/docs/inference/chat/structured-outputs).

## Usage""",
    )
    root_sub(
        "models/providers/gateways/together/usage/tool-use.mdx",
        "```\n\n## Usage",
        """```

Set `TOGETHER_MODEL_ID` to a current model with [function-calling support](https://docs.together.ai/docs/inference/function-calling/overview).

## Usage""",
    )

    root_sub(
        "models/providers/gateways/together/overview.mdx",
        "See their library of models [here](https://www.together.ai/models).",
        "See the current [serverless model catalog](https://docs.together.ai/docs/serverless/models). Together retires model IDs on a rolling schedule, so verify availability and required capabilities before deployment.",
    )
    root_sub(
        "models/providers/gateways/together/overview.mdx",
        "export TOGETHER_API_KEY=***",
        "export TOGETHER_API_KEY=***\nexport TOGETHER_MODEL_ID=your-model-id",
    )
    root_sub(
        "models/providers/gateways/together/overview.mdx",
        "```bash Windows\nsetx TOGETHER_API_KEY ***\nsetx TOGETHER_MODEL_ID your-model-id\n```",
        "```powershell Windows\n$Env:TOGETHER_API_KEY=\"your_api_key\"\n$Env:TOGETHER_MODEL_ID=\"your_model_id\"\n```",
        required=False,
    )
    root_sub(
        "models/providers/gateways/together/overview.mdx",
        "```bash Windows\nsetx TOGETHER_API_KEY ***\n```",
        "```powershell Windows\n$Env:TOGETHER_API_KEY=\"your_api_key\"\n$Env:TOGETHER_MODEL_ID=\"your_model_id\"\n```",
    )
    root_sub(
        "models/providers/gateways/together/overview.mdx",
        "from agno.agent import Agent",
        "import os\n\nfrom agno.agent import Agent",
    )
    root_sub(
        "models/providers/gateways/together/overview.mdx",
        'model=Together(id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo")',
        'model=Together(id=os.environ["TOGETHER_MODEL_ID"])',
    )

    root_sub(
        "context-providers/providers/web.mdx",
        """<Note>
WebContextProvider is **read-only**. There is no `update_web` tool.
</Note>

## Backends""",
        """<Note>
WebContextProvider is **read-only**. There is no `update_web` tool.
</Note>

## Installation

Install the optional dependency for the selected backend.

| Backend | Install command |
|---------|-----------------|
| `ExaBackend` | `uv pip install \"agno[exa]\"` |
| `ParallelBackend` | `uv pip install \"agno[parallel]\"` |
| `ExaMCPBackend` or `ParallelMCPBackend` | `uv pip install \"agno[mcp]\"` |

## Backends""",
    )

    root_sub(
        "reference/models/n1n.mdx",
        """Access [n1n.ai](https://n1n.ai) models through an OpenAI-compatible interface.

## Authentication""",
        """Access [n1n.ai](https://n1n.ai) models through an OpenAI-compatible interface.

## Installation

```bash
uv pip install -U agno ddgs openai
```

## Authentication""",
    )

    spotify_page = "tools/toolkits/others/spotify.mdx"
    root_sub(
        spotify_page,
        "| `get_user_playlists`          | Get playlists for a specific user                   |",
        "| `get_user_playlists`          | Unavailable to Development Mode apps in Agno 2.7.2 because it expects the earlier response fields |",
    )
    root_sub(
        spotify_page,
        'description: "Enable an Agent to search Spotify for tracks, artists, and albums, and create and manage playlists."',
        'description: "Enable an Agent to search Spotify for tracks, artists, and albums with a read-only toolkit configuration."',
    )
    root_sub(
        spotify_page,
        "**SpotifyTools** enable an Agent to search for songs and manage playlists on Spotify.",
        "**SpotifyTools** enable an Agent to search Spotify's catalog and access authenticated-user playback data.",
    )
    root_sub(
        spotify_page,
        """The following example requires a Spotify access token from [Spotify](https://developer.spotify.com/). The toolkit itself uses `httpx`, which is already a dependency of Agno. The example uses an Anthropic model, so install the `anthropic` library.

```shell
uv pip install anthropic
```""",
        """The example requires a Spotify access token from [Spotify](https://developer.spotify.com/) and an Anthropic API key. It enables only catalog search, so the Spotify token does not need playlist modification scopes.

```shell
uv pip install -U agno anthropic
```""",
    )
    root_sub(
        spotify_page,
        """export SPOTIFY_TOKEN=***
export ANTHROPIC_API_KEY=***
```

## Example""",
        """export SPOTIFY_TOKEN=***
export ANTHROPIC_API_KEY=***
```

<Warning>
Spotify changed several endpoints and response fields for Development Mode apps in February 2026. Extended Quota Mode apps are unaffected. Agno 2.7.2 still uses the earlier paths and fields, so the affected methods below are unavailable to Development Mode apps. Use the read-only example until `SpotifyTools` is updated. See Spotify's [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
</Warning>

## Example""",
    )
    root_sub(
        spotify_page,
        "The following agent will search for tracks and create a playlist on Spotify.",
        "The following agent searches Spotify for tracks and returns their names and URIs.",
    )
    root_sub(
        spotify_page,
        """    access_token=SPOTIFY_TOKEN,
    default_market="US",
)""",
        """    access_token=SPOTIFY_TOKEN,
    default_market="US",
    include_tools=["search_tracks"],
)""",
    )
    root_sub(
        spotify_page,
        """    instructions=[
        "You are a helpful music assistant that can search for songs and manage Spotify playlists.",
        "When asked to create a playlist:",
        "1. First search for relevant tracks based on the user's criteria (mood, artist, genre)",
        "2. Collect the track URIs from the search results",
        "3. Create the playlist with those tracks",
        "When updating a playlist, use the playlist ID from a previous creation or ask the user for it.",
        "Always confirm what you've done and provide the playlist URL when created.",
    ],""",
        """    instructions=[
        "Search Spotify for tracks that match the request.",
        "Return each track's name, artists, and Spotify URI.",
    ],""",
    )
    root_sub(
        spotify_page,
        """response = agent.run(
    "Create a Good Vibes playlist, add 5 upbeat songs by The Weeknd and Coldplay in it."
)""",
        'response = agent.run("Find five tracks by The Weeknd.")',
    )
    root_sub(
        spotify_page,
        "| `search_playlists`            | Search for playlists on Spotify                     |",
        "| `search_playlists`            | Unavailable to Development Mode apps in Agno 2.7.2 because it expects the earlier playlist response fields |",
    )
    root_sub(
        spotify_page,
        "| `get_artist_top_tracks`       | Get top tracks for a specific artist                |",
        "| `get_artist_top_tracks`       | Unavailable to Development Mode apps because Spotify removed the endpoint |",
    )
    root_sub(
        spotify_page,
        "| `create_playlist`             | Create a new playlist for the user                  |",
        "| `create_playlist`             | Unavailable to Development Mode apps in Agno 2.7.2 because it calls the removed user-specific endpoint |",
    )
    root_sub(
        spotify_page,
        "| `add_tracks_to_playlist`      | Add tracks to an existing playlist                  |",
        "| `add_tracks_to_playlist`      | Unavailable to Development Mode apps in Agno 2.7.2 because it calls the removed `/tracks` endpoint |",
    )
    root_sub(
        spotify_page,
        "| `get_playlist`                | Get details of a specific playlist                  |",
        "| `get_playlist`                | For Development Mode apps, use `include_tracks=False`; item parsing expects the earlier field names |",
    )
    root_sub(
        spotify_page,
        "| `remove_tracks_from_playlist` | Remove tracks from an existing playlist             |",
        "| `remove_tracks_from_playlist` | Unavailable to Development Mode apps in Agno 2.7.2 because it calls the removed `/tracks` endpoint |",
    )

    root_sub(
        "models/providers/native/google/usage/imagen-tool-advanced.mdx",
        "```\n\n## Usage",
        """```

<Warning>
The source uses the retired `imagen-4.0-generate-preview-05-20` model, the removed `Agent.run_response` accessor, and raw image bytes where `save_base64_data` expects base64. Apply all three edits below before running. Google will shut down Imagen 4 on August 17, 2026. Migrate to the [Gemini image-generation API](https://ai.google.dev/gemini-api/docs/generate-content/image-generation), which uses `generate_content`, before that date.
</Warning>

## Usage""",
    )
    root_sub(
        "models/providers/native/google/usage/imagen-tool-advanced.mdx",
        '  <Step title="Run Agent">',
        """  <Step title="Update the Imagen model">
    Replace `imagen-4.0-generate-preview-05-20` with `imagen-4.0-generate-001` in the saved file.
  </Step>

  <Step title="Use the v2 run output accessor">
    Replace `response = agent.run_response` with `response = agent.get_last_run_output()` in the saved file.
  </Step>

  <Step title="Encode the image bytes">
    Add `import base64`, then replace `save_base64_data(str(response.images[0].content), "tmp/baleen_whale.png")` with `save_base64_data(base64.b64encode(response.images[0].content).decode("ascii"), "tmp/baleen_whale.png")` in the saved file.
  </Step>

  <Step title="Run Agent">""",
    )

    # 9. Reviewed frontmatter overrides consumed by the overview row pass.
    apply_frontmatter_overrides()

    # 10. Title-casing pass over every page (fixes curated overview stubs:
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

    # 11. Refresh only malformed or explicitly stale overview rows, then add
    #    only the navigation-backed omissions approved by the audit.
    repair_overview_tables()

    # 12. Restore post-tag toolkit cards that shipped in navigation without
    #     corresponding entries in the hand-maintained complete index.
    repair_toolkit_index()

    # 13. Preserve the reviewed byte-level terminal-newline convention after
    #     deterministic reconstruction.
    normalize_terminal_newlines("tracing/db-functions.mdx")
    normalize_terminal_newlines("reference-api/schema/approvals/get-approval-count.mdx")

    if CHECK:
        print(f"check: {would_apply} fixes would apply; title-casing would change {count} pages")
    else:
        print(f"one-offs applied; title-casing fixed on {count} additional pages")


if __name__ == "__main__":
    main()
