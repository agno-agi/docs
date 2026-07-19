#!/usr/bin/env python3
"""Generate a docs example page (.mdx) from an Agno cookbook file.

Usage:
    python scripts/examples_sync/generate.py <cookbook-file.py> --slug examples/agents/tools/callable-tools
    python scripts/examples_sync/generate.py <cookbook-file.py> --slug ... --docs-root /path/to/docs
    python scripts/examples_sync/generate.py <cookbook-file.py> --slug ... --stdout

The page is written to <docs-root>/<slug>.mdx (or stdout with --stdout).
Docs root defaults to the repo root (two levels above this file); agno root
defaults to the AGNO_REPO env var, then the ./agno symlink at the docs root.

Page shape:
    - frontmatter: title (docstring first line), description (docstring second
      paragraph), source (cookbook-relative path, machine-checkable)
    - intro prose (first docstring paragraph)
    - the full cookbook file in a python code block, docstring included
    - "Run the Example": <Steps> with venv snippet, install, env keys, run

Dependencies and env keys are derived from the file's imports by probing the
agno source tree (pip-install hints and getenv() calls in each imported
module), plus curated overrides below. Output is deterministic: running twice
on the same inputs produces identical bytes.

Description overrides: if description-overrides.json exists next to this
script (or at the path in the DESC_OVERRIDES_JSON env var), it is loaded as a
{slug: description} map. When a page's slug has an entry, that description is
used in the frontmatter (quotes escaped via yaml_str) instead of the
docstring-derived one, and no placeholder warning fires.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Curated tables
# ---------------------------------------------------------------------------

INVALID_MODEL_RETRY_DESCRIPTION = (
    "Review retry settings and why invalid model IDs cannot reliably exercise "
    "the retry path."
)
INVALID_MODEL_RETRY_WARNING = (
    "The pinned source assumes an invalid model ID triggers the configured retries. "
    "Invalid-model responses commonly use terminal 400 or 404 statuses, which Agno "
    "does not retry. Do not run this source as a retry test."
)
INVALID_MODEL_RETRY_REPLACEMENT = (
    "Configure `retries`, `delay_between_retries`, and `exponential_backoff` as shown "
    "in [Retry Model Requests](/models/overview#retry-model-requests). Test the retry "
    "path with a controlled transient 429, connection failure, or 5xx response."
)

# Model providers: agno.models.<segment> -> (display name, pip packages, env keys)
# Packages/keys verified against libs/agno/pyproject.toml extras and each
# provider's getenv() calls. OpenAI-compatible providers use the openai SDK.
MODEL_PROVIDERS = {
    "aimlapi": ("AI/ML API", ["openai"], ["AIMLAPI_API_KEY"]),
    "anthropic": ("Anthropic", ["anthropic"], ["ANTHROPIC_API_KEY"]),
    "aws": (
        "AWS Bedrock",
        ["boto3", "aioboto3"],
        ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"],
    ),
    "azure": (
        "Azure AI Foundry",
        ["azure-ai-inference", "aiohttp"],
        ["AZURE_API_KEY", "AZURE_ENDPOINT"],
    ),
    "cerebras": ("Cerebras", ["cerebras-cloud-sdk"], ["CEREBRAS_API_KEY"]),
    "cloudflare": (
        "Cloudflare Workers AI",
        ["openai"],
        ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
    ),
    "cohere": ("Cohere", ["cohere"], ["CO_API_KEY"]),
    "cometapi": ("CometAPI", ["openai"], ["COMETAPI_KEY"]),
    "dashscope": ("DashScope", ["openai"], ["DASHSCOPE_API_KEY"]),
    "deepinfra": ("DeepInfra", ["openai"], ["DEEPINFRA_API_KEY"]),
    "deepseek": ("DeepSeek", ["openai"], ["DEEPSEEK_API_KEY"]),
    "fireworks": ("Fireworks", ["openai"], ["FIREWORKS_API_KEY"]),
    "google": ("Google", ["google-genai"], ["GOOGLE_API_KEY"]),
    "groq": ("Groq", ["groq"], ["GROQ_API_KEY"]),
    "huggingface": ("Hugging Face", ["huggingface-hub"], ["HF_TOKEN"]),
    "ibm": (
        "IBM watsonx",
        ["ibm-watsonx-ai"],
        ["IBM_WATSONX_API_KEY", "IBM_WATSONX_PROJECT_ID"],
    ),
    "inception": ("Inception", ["openai"], ["INCEPTION_API_KEY"]),
    "internlm": ("InternLM", ["openai"], ["INTERNLM_API_KEY"]),
    "langdb": ("LangDB", ["openai"], ["LANGDB_API_KEY", "LANGDB_PROJECT_ID"]),
    "litellm": ("LiteLLM", ["litellm"], ["LITELLM_API_KEY"]),
    "llama_cpp": ("llama.cpp", ["openai"], []),
    "lmstudio": ("LM Studio", ["openai"], []),
    "meta": ("Meta Llama", ["llama-api-client"], ["LLAMA_API_KEY"]),
    "minimax": ("MiniMax", ["openai"], ["MINIMAX_API_KEY"]),
    "mistral": ("Mistral", ["mistralai"], ["MISTRAL_API_KEY"]),
    "moonshot": ("Moonshot", ["openai"], ["MOONSHOT_API_KEY"]),
    "n1n": ("N1N", ["openai"], ["N1N_API_KEY"]),
    "nebius": ("Nebius", ["openai"], ["NEBIUS_API_KEY"]),
    "neosantara": ("Neosantara", ["openai"], ["NEOSANTARA_API_KEY"]),
    "nexus": ("Nexus", ["openai"], []),
    "nvidia": ("NVIDIA", ["openai"], ["NVIDIA_API_KEY"]),
    "ollama": ("Ollama", ["ollama"], []),
    "openai": ("OpenAI", ["openai"], ["OPENAI_API_KEY"]),
    "openrouter": ("OpenRouter", ["openai"], ["OPENROUTER_API_KEY"]),
    "perplexity": ("Perplexity", ["openai"], ["PERPLEXITY_API_KEY"]),
    "portkey": ("Portkey", ["portkey-ai", "openai"], ["PORTKEY_API_KEY"]),
    "requesty": ("Requesty", ["openai"], ["REQUESTY_API_KEY"]),
    "sambanova": ("SambaNova", ["openai"], ["SAMBANOVA_API_KEY"]),
    "siliconflow": ("SiliconFlow", ["openai"], ["SILICONFLOW_API_KEY"]),
    "together": ("Together", ["openai"], ["TOGETHER_API_KEY"]),
    "vercel": ("Vercel v0", ["openai"], ["V0_API_KEY"]),
    "vertexai": (
        "Claude on Vertex AI",
        ["anthropic[vertex]"],
        ["ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION"],
    ),
    "vllm": ("vLLM", ["openai"], ["VLLM_API_KEY"]),
    "xai": ("xAI", ["openai"], ["XAI_API_KEY"]),
    "xiaomi": ("Xiaomi MiMo", ["openai"], ["MIMO_API_KEY"]),
}

# Some provider packages export classes backed by different SDKs. Resolve
# these before falling back to the module-segment mapping above.
MODEL_CLASS_PROVIDERS = {
    "aws": {
        "Claude": (
            "AWS Bedrock Claude",
            ["boto3", "aioboto3", "anthropic[bedrock]"],
            ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"],
        ),
    },
    "azure": {
        "AzureAIFoundry": (
            "Azure AI Foundry",
            ["azure-ai-inference", "aiohttp"],
            ["AZURE_API_KEY", "AZURE_ENDPOINT"],
        ),
        "AzureOpenAI": (
            "Azure OpenAI",
            ["openai"],
            ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        ),
        "AzureFoundryClaude": (
            "Azure AI Foundry Claude",
            ["anthropic"],
            ["ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_RESOURCE"],
        ),
        "Claude": (
            "Azure AI Foundry Claude",
            ["anthropic"],
            ["ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_RESOURCE"],
        ),
    },
    "meta": {
        "Llama": ("Meta Llama", ["llama-api-client"], ["LLAMA_API_KEY"]),
        "LlamaOpenAI": ("Meta Llama", ["openai"], ["LLAMA_API_KEY"]),
    },
    "cerebras": {
        "CerebrasOpenAI": (
            "Cerebras OpenAI-compatible API",
            ["cerebras-cloud-sdk", "openai"],
            ["CEREBRAS_API_KEY"],
        ),
    },
    "cloudflare": {
        "Cloudflare": (
            "Cloudflare Workers AI",
            ["openai"],
            ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
        ),
    },
    "litellm": {
        "LiteLLMOpenAI": (
            "LiteLLM",
            ["litellm", "openai"],
            ["LITELLM_API_KEY"],
        ),
    },
    "ollama": {
        "OllamaResponses": ("Ollama Responses", ["ollama", "openai"], []),
    },
    "portkey": {
        "Portkey": ("Portkey", ["portkey-ai", "openai"], ["PORTKEY_API_KEY"]),
    },
}

# agno module prefix -> agno pip extra (installed as agno[extra]).
# Matches how the rest of the docs install these features.
EXTRA_MODULES = {
    "agno.os.interfaces.a2a": "a2a",
    "agno.os.interfaces.agui": "agui",
    "agno.os.interfaces.slack": "slack",
    "agno.os.interfaces.telegram": "telegram",
    "agno.os.interfaces.whatsapp": "os",
    "agno.os": "os",
    "agno.context.mcp": "mcp",
    "agno.context.slack": "slack",
    "agno.scheduler": "scheduler",
    "agno.tools.mcp": "mcp",
    "agno.tools.mcp_toolbox": "mcp",
    "agno.tools.scheduler": "scheduler",
    "agno.tools.telegram": "telegram",
    "agno.tracing": "os",  # tracing ships with the AgentOS/opentelemetry bundle
}

# Packages each agno extra installs (libs/agno/pyproject.toml on feat/v2.7,
# nested agno[...] references resolved, names PEP 503-normalized). Used to
# drop packages from the install line that the extra already provides.
EXTRA_PROVIDES: dict[str, set[str]] = {
    "a2a": {"a2a-sdk"},
    "agui": {"ag-ui-protocol", "jsonpatch"},
    "clickhouse": {"clickhouse-connect"},
    "mcp": {"mcp", "fastmcp"},
    "os": {
        "fastapi", "python-multipart", "uvicorn", "websockets", "sqlalchemy",
        "pyjwt", "starlette", "opentelemetry-sdk", "openinference-instrumentation-agno",
        # via agno[scheduler]
        "croniter", "pytz",
    },
    "scheduler": {"croniter", "pytz"},
    "slack": {"slack-sdk", "aiohttp"},
    "telegram": {"pytelegrambotapi", "telebot", "aiohttp"},
}

# Interface and toolkit credentials loaded from helper modules that are not
# reached by the single-module source probe.
REQUIRED_ENV_OVERRIDES = {
    "agno.knowledge.embedder.azure_openai": {
        "AZURE_EMBEDDER_OPENAI_API_KEY",
        "AZURE_EMBEDDER_OPENAI_ENDPOINT",
    },
    "agno.context.calendar": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.context.gdrive": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.context.gmail": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.os.interfaces.slack": {"SLACK_SIGNING_SECRET", "SLACK_TOKEN"},
    "agno.os.interfaces.telegram": {"TELEGRAM_TOKEN"},
    "agno.os.interfaces.whatsapp": {
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
    },
    "agno.tools.google.calendar": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.tools.googlecalendar": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.tools.google.drive": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.tools.google.gmail": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.tools.google.slides": {
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PROJECT_ID",
    },
    "agno.tools.jira": {"JIRA_SERVER_URL", "JIRA_USERNAME", "JIRA_TOKEN"},
    "agno.tools.oxylabs": {"OXYLABS_USERNAME", "OXYLABS_PASSWORD"},
    "agno.tools.shopify": {"SHOPIFY_SHOP_NAME", "SHOPIFY_ACCESS_TOKEN"},
    "agno.tools.spider": {"SPIDER_API_KEY"},
    "agno.tools.zendesk": {
        "ZENDESK_USERNAME",
        "ZENDESK_COMPANY_NAME",
        "ZENDESK_PASSWORD",
    },
}

# Human-written frontmatter descriptions, keyed by docs slug. See the module
# docstring; missing file means no overrides.
_DESC_OVERRIDES_PATH = Path(
    os.environ.get("DESC_OVERRIDES_JSON")
    or Path(__file__).resolve().parent / "description-overrides.json"
)
DESC_OVERRIDES: dict[str, str] = (
    json.loads(_DESC_OVERRIDES_PATH.read_text(encoding="utf-8"))
    if _DESC_OVERRIDES_PATH.is_file()
    else {}
)

# Overrides where the source-probe misses packages (import guards live in
# shared helper modules) or reports the wrong thing.
PACKAGE_OVERRIDES = {
    "agno.db.postgres": ["sqlalchemy", "psycopg[binary]"],
    "agno.db.async_postgres": ["sqlalchemy", "asyncpg"],
    "agno.db.mysql": ["sqlalchemy", "pymysql"],
    "agno.db.async_mysql": ["sqlalchemy", "asyncmy"],
    "agno.db.sqlite": ["sqlalchemy"],
    "agno.db.async_sqlite": ["sqlalchemy", "aiosqlite"],
    "agno.db.singlestore": ["sqlalchemy", "pymysql"],
    "agno.db.redis": ["redis"],
    "agno.db.mongo": ["pymongo"],
    "agno.db.dynamo": ["boto3"],
    "agno.db.firestore": ["google-cloud-firestore"],
    "agno.db.gcs": ["google-cloud-storage"],
    "agno.db.surrealdb": ["surrealdb"],
    "agno.context.calendar": [
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
    ],
    "agno.context.gdrive": [
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
    ],
    "agno.context.gmail": [
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
    ],
    "agno.vectordb.pineconedb": ["pinecone==5.4.2"],
    "agno.vectordb.pgvector": ["sqlalchemy", "psycopg[binary]", "pgvector"],
    "agno.knowledge.embedder.openai": ["openai"],
    "agno.knowledge.embedder.google": ["google-genai"],
    "agno.tools.duckduckgo": ["ddgs"],
    "agno.eval.performance": ["memory_profiler"],
}

# Consolidated DB packages export both sync and async classes. Infer drivers
# from imported class names and retain both when both classes are imported.
DB_CLASS_PACKAGES = {
    "mysql": {"MySQLDb": ["pymysql"], "AsyncMySQLDb": ["asyncmy"]},
    "postgres": {
        "PostgresDb": ["psycopg[binary]"],
        "AsyncPostgresDb": [],
    },
    "sqlite": {"SqliteDb": [], "AsyncSqliteDb": ["aiosqlite"]},
}

# Third-party (non-agno) import name -> pip package(s). Stdlib is filtered
# out separately; anything not listed here installs under its import name
# (underscores hyphenated). Values verified against libs/agno/pyproject.toml.
THIRD_PARTY_PACKAGES: dict[str, str | list[str]] = {
    "a2a": "a2a-sdk",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "googleapiclient": "google-api-python-client",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "jwt": "PyJWT",
    "cv2": "opencv-python",
    "fitz": "pymupdf",
    "readability": "readability-lxml",
    "sklearn": "scikit-learn",
    "agents": "openai-agents",
    "brave": "brave-search",
    "github": "pygithub",
    "gitlab": "python-gitlab",
    "phoenix": "arize-phoenix",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "mem0": "mem0ai",
    "linkup": "linkup-sdk",
    "maxim": "maxim-py",
    "serpapi": "google-search-results",
    "spider": "spider-client",
    "tavily": "tavily-python",
    "traceloop": "traceloop-sdk",
    "parallel": "parallel-web",
    "newspaper": ["newspaper4k", "lxml_html_clean"],
    "openinference": "openinference-instrumentation-agno",
    "opentelemetry": ["opentelemetry-sdk", "opentelemetry-exporter-otlp"],
    # Upstream cookbook helper referenced by 90_models/anthropic/skills but
    # not shipped anywhere; nothing to install.
    "file_download_helper": [],
}

# `google` is a namespace package; map by submodule and never emit bare
# `google` (a squatted PyPI name).
GOOGLE_SUBPACKAGES = {
    "auth": ["google-auth"],
    "oauth2": ["google-auth"],
    "api_core": ["google-api-core"],
    "genai": ["google-genai"],
    "generativeai": ["google-generativeai"],
    "protobuf": ["protobuf"],
    "cloud.storage": ["google-cloud-storage"],
    "cloud.bigquery": ["google-cloud-bigquery"],
    "cloud.firestore": ["google-cloud-firestore"],
    "cloud.exceptions": ["google-cloud-storage"],
}

# pip-install hint tokens (from agno module error messages) that are not
# real PyPI packages.
PIP_HINT_FIXES: dict[str, list[str]] = {
    "ffmpeg": [],  # system binary, not a PyPI package (moviepy pulls imageio-ffmpeg)
}

# Ships with agno core; never worth an explicit install line.
CORE_DEPS = {
    "agnoctl", "docstring-parser", "docstring_parser", "h11", "httpx",
    "packaging", "pydantic", "pydantic-settings", "pyyaml", "rich",
    "typing-extensions", "typing_extensions",
}

# Env var names that are read by agno modules but are not user credentials.
ENV_DENYLIST_RE = re.compile(
    r"(_BASE_URL|_URL|_HOST|_ENDPOINT|_REGION|_VERSION|_MODEL|_PROJECT|_LOCATION|"
    r"_DEPLOYMENT|_PROFILE|_ORG|_DIR|_PATH|_PORT|_DB|_NAMESPACE|_AUTH_TOKEN)$"
)
ENV_DENYLIST = {
    "AWS_SESSION_TOKEN",
    "AWS_ACCESS_KEY",  # legacy alias; AWS_ACCESS_KEY_ID is canonical
    "AWS_SECRET_KEY",
}
# Required credentials that the suffix/denylist rules would wrongly drop.
ENV_ALLOWLIST = {
    "LANGSMITH_PROJECT",  # read with no default; sent as the Langsmith-Project header
}

# AgentOS supports JWT configuration but does not require it. A cookbook file
# that explicitly reads this key still adds it through required_env_keys_in_source().
PROBED_ENV_DENYLIST = {
    "AGNO_ENCRYPTION_KEY",
    "JWT_VERIFICATION_KEY",
    "WHATSAPP_ENCRYPTION_KEY",
}

# Local services an example depends on -> docker step. Triggered by module
# prefix (agno modules) or import name (third-party clients). PgVector is
# handled separately via the run-pgvector-step.mdx snippet.
SERVICE_TRIGGERS = {
    "mysql": ("agno.db.mysql", "agno.db.async_mysql"),
    "mongodb": ("agno.db.mongo", "agno.vectordb.mongodb", "pymongo", "motor"),
    "qdrant": ("agno.vectordb.qdrant", "qdrant_client"),
    "redis": ("agno.db.redis", "agno.vectordb.redis", "redis"),
    "surrealdb": ("agno.db.surrealdb", "agno.vectordb.surrealdb", "surrealdb"),
}
SERVICE_STEPS = {
    "mysql": (
        "Run MySQL",
        "docker run -d --name mysql -e MYSQL_ROOT_PASSWORD=ai -e MYSQL_DATABASE=ai "
        "-e MYSQL_USER=ai -e MYSQL_PASSWORD=ai -p 3306:3306 mysql:8",
    ),
    "mongodb": ("Run MongoDB", "docker run -d -p 27017:27017 --name mongodb mongo:latest"),
    "qdrant": ("Run Qdrant", "docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest"),
    "redis": ("Run Redis", "docker run -d --name my-redis -p 6379:6379 redis"),
    "surrealdb": (
        "Run SurrealDB",
        "docker run -d --rm --name surrealdb --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root",
    ),
}

# Casing fixes for filename-derived titles.
ACRONYMS = {
    "a2a": "A2A", "agentos": "AgentOS", "agui": "AG-UI", "ai": "AI",
    "api": "API", "aws": "AWS", "chromadb": "ChromaDB", "csv": "CSV",
    "db": "DB", "dbs": "DBs", "deepinfra": "DeepInfra", "deepseek": "DeepSeek",
    "duckdb": "DuckDB", "duckduckgo": "DuckDuckGo", "dynamodb": "DynamoDB",
    "e2b": "E2B", "gcp": "GCP", "gcs": "GCS", "github": "GitHub",
    "gitlab": "GitLab", "gpt": "GPT", "hackernews": "HackerNews",
    "hitl": "HITL", "http": "HTTP", "huggingface": "Hugging Face",
    "bigquery": "BigQuery", "ibm": "IBM", "id": "ID", "io": "I/O", "json": "JSON", "jwt": "JWT",
    "lancedb": "LanceDB", "litellm": "LiteLLM", "llm": "LLM", "mcp": "MCP",
    "mongodb": "MongoDB", "mysql": "MySQL", "nvidia": "NVIDIA",
    "ocr": "OCR", "openai": "OpenAI", "openrouter": "OpenRouter",
    "os": "OS", "oss": "OSS", "pdf": "PDF", "pgvector": "PgVector",
    "pii": "PII",
    "postgres": "Postgres", "qdrant": "Qdrant", "rag": "RAG", "rbac": "RBAC",
    "singlestore": "SingleStore", "sql": "SQL", "sqlite": "SQLite",
    "sse": "SSE", "ssrf": "SSRF", "surrealdb": "SurrealDB", "ui": "UI",
    "url": "URL", "uv": "uv", "vertexai": "Vertex AI", "vllm": "vLLM",
    "websearch": "WebSearch", "whatsapp": "WhatsApp", "xai": "xAI",
    "xml": "XML", "yaml": "YAML", "youtube": "YouTube",
    "zdr": "ZDR",
}

# Words kept lowercase in filename-derived titles (unless first).
SMALL_WORDS = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}

# Titles the docstring cannot yield in docs voice, keyed by docs slug.
# Consulted at render time, before description/intro derivation.
TITLE_OVERRIDES = {
    "examples/agent-os/remote/remote-agent": "Remote Agent",
    "examples/agent-os/remote/remote-team": "Remote Team",
    "examples/agent-os/background-tasks/background-hooks-team": "Background Hooks Team",
    "examples/agent-os/background-tasks/background-hooks-workflow": "Background Hooks Workflow",
    "examples/agent-os/client-a2a/servers/google-adk-server": "Google ADK A2A Server",
    "examples/agent-os/customize/custom-fastapi-app": "Custom FastAPI App",
    "examples/agent-os/customize/custom-health-endpoint": "Custom Health Endpoint",
    "examples/agent-os/factories/agent/basic-factory": "Basic Agent Factory",
    "examples/agent-os/factories/hitl-factory": "Factory with HITL Tool",
    "examples/agent-os/factories/workflow/basic-workflow-factory": "Basic Workflow Factory",
    "examples/agent-os/rbac/symmetric/basic": "Symmetric RBAC Basic",
    "examples/agent-os/rbac/symmetric/with-cookie": "Symmetric RBAC with Cookie Tokens",
    "examples/agent-os/scheduler/team-workflow-schedules": "Scheduling Teams and Workflows",
    "examples/agents/multimodal/audio-to-text": "Audio to Text",
    "examples/models/azure/ai-foundry/basic": "Azure AI Foundry Basic",
    "examples/models/azure/openai/basic": "Azure OpenAI Basic",
    "examples/models/anthropic/betas": "Betas",
    "examples/models/cometapi/structured-output": "CometAPI Structured Output",
    "examples/models/dashscope/image-agent": "DashScope Image Agent",
    "examples/models/dashscope/tool-use": "DashScope Tool Use",
    "examples/models/google/gemini/external-url-input": "External URL Input",
    "examples/models/groq/reasoning/demo-qwen-2-5-32b": "Demo Qwen 2.5 32B",
    "examples/models/huggingface/llama-essay-writer": "Hugging Face GPT-OSS Essay Writer",
    "examples/models/langdb/basic": "LangDB Basic",
    "examples/models/langdb/structured-output": "LangDB Structured Output",
    "examples/models/vertexai/claude/betas": "Betas",
    "examples/storage/postgres/async-postgres/async-postgres-for-agent": "Async Postgres for Agent",
    "examples/models/openrouter/responses/basic": "Basic Usage",
    "examples/models/openrouter/responses/fallback": "Fallback Routing",
    "examples/models/openrouter/responses/stream": "Streaming",
    "examples/models/openrouter/responses/tool-use": "Tools",
    "examples/models/openrouter/chat/tool-use": "Tools",
    "examples/models/meta/llama-openai/metrics": "Llama OpenAI Metrics",
    "examples/models/meta/llama/metrics": "Llama Metrics",
    "examples/reasoning/models/groq/deepseek-plus-claude": "Qwen3 Plus Claude",
    "examples/storage/in-memory/in-memory-storage-for-team": "In-Memory Storage for Team",
    "examples/tools/mcp/cli": "MCP CLI",
    "examples/tools/mcp/gibsonai": "GibsonAI MCP Server",
    "examples/tools/mcp/supabase": "Supabase MCP Agent",
    "examples/tools/mcp/local-server/server": "FastMCP Local Server",
    "examples/tools/mcp/notion-mcp-agent": "Notion MCP Agent",
    "examples/tools/mlx-transcribe-tools": "MLX Transcribe Tools",
    "examples/tools/models/gemini-image-generation": "Gemini Image Generation",
    "examples/tools/models/gemini-video-generation": "Gemini Video Generation",
    "examples/tools/other/human-in-the-loop": "Human in the Loop",
    "examples/tools/clickup-tools": "ClickUp Tools",
    "examples/tools/spotify-tools": "Spotify Tools",
    "examples/tools/exceptions/retry-tool-call-from-post-hook": "Post-Hook Retry",
    "examples/tools/googlesheets-tools": "Google Sheets Tools",
    "examples/tools/trafilatura-tools": "Trafilatura Tools",
    "examples/tools/webbrowser-tools": "WebBrowser Tools",
}

# These examples read files or directory trees that already exist in the Agno
# checkout. Other uses of __file__ create/download outputs or locate the script
# itself and remain runnable when the code block is saved standalone.
REPO_LAYOUT_SLUGS = {
    "examples/agent-os/knowledge/agentos-docling-markdown-analyst",
    "examples/agent-os/knowledge/agentos-excel-analyst",
    "examples/agent-os/os-config/yaml-config",
    "examples/agent-os/skills/skills-with-agentos",
    "examples/agents/skills/basic-skills",
    "examples/basics/run",
    "examples/context/engineering-briefing",
    "examples/context/filesystem",
    "examples/context/multi-provider",
    "examples/context/workspace",
    "examples/models/google/gemini/file-search-advanced",
    "examples/models/google/gemini/file-search-basic",
    "examples/models/google/gemini/file-search-rag-pipeline",
    "examples/teams/reasoning/reasoning-multi-purpose-team",
    "examples/teams/skills/basic-skills-team",
    "examples/tools/antigravity/antigravity-directory-tools",
    "examples/tools/docling-tools/basic-examples",
    "examples/tools/docling-tools/ocr-example",
    "examples/tools/docling-tools/paths",
    "examples/tools/docling-tools/run",
    "examples/tools/mcp-tools",
    "examples/tools/mcp/filesystem",
    "examples/tools/mcp/groq-mcp",
    "examples/tools/mcp/include-tools",
}

# Source-specific requirements that cannot be derived safely from imports.
# Keys are cookbook-relative paths without the leading `cookbook/`.
INFINITY_STEP = (
    "Start Infinity",
    "Install Infinity and start the reranker on port 7997:",
    "uv pip install -U \"infinity-emb[all]\"\ninfinity_emb v2 --model-id BAAI/bge-reranker-base --port 7997",
)
LMSTUDIO_STEP = (
    "Prepare LM Studio",
    "Load `qwen2.5-7b-instruct-1m` in LM Studio and start its local server at `http://127.0.0.1:1234/v1`.",
    None,
)
LMSTUDIO_VISION_STEP = (
    "Prepare LM Studio",
    "Load `llama3.2-vision` in LM Studio and start its local server at `http://127.0.0.1:1234/v1`.",
    None,
)
LMSTUDIO_RETRY_STEP = (
    "Prepare LM Studio",
    "Start the LM Studio local server at `http://127.0.0.1:1234/v1`. The source uses a deliberately invalid model ID to exercise retries.",
    None,
)
LLAMA_CPP_STEP = (
    "Start llama.cpp",
    "Serve `ggml-org/gpt-oss-20b-GGUF` at `http://127.0.0.1:8080/v1`:",
    "llama-server -hf ggml-org/gpt-oss-20b-GGUF --ctx-size 0 --jinja -ub 2048 -b 2048",
)
LLAMA_CPP_INSTALL_STEP = (
    "Install llama.cpp",
    "Install the `llama-server` binary. This command supports macOS and Linux with Homebrew; see the [llama.cpp installation guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md) for other platforms:",
    "brew install llama.cpp",
)
GEMINI_31_PRO_WARNING = "Google shut down Gemini 3 Pro Preview on March 9, 2026. The pinned `gemini-3-pro-preview` ID currently aliases to `gemini-3.1-pro-preview`; replace it explicitly before running."
GEMINI_31_PRO_MIGRATION_STEP = (
    "Use Gemini 3.1 Pro Preview",
    "Replace `gemini-3-pro-preview` with `gemini-3.1-pro-preview` in the saved Python file before running.",
    None,
)
CEREBRAS_RETIRED_MODEL_IDS = {
    "llama-3.3-70b",
    "llama-4-scout-17b-16e-instruct",
    "qwen-3-32b",
}
CEREBRAS_RETIRED_MODEL_WARNING = (
    "This example uses a Cerebras model ID that has been retired. Replace the "
    "retired ID with `gpt-oss-120b` before running. Review the "
    "[Cerebras migration notes](https://inference-docs.cerebras.ai/support/deprecation) "
    "when the example uses reasoning, tools, or structured output."
)
COHERE_RETIRED_VISION_WARNING = (
    "The pinned source uses `c4ai-aya-vision-8b`, which Cohere retired on "
    "April 4, 2026. Replace it with `command-a-vision-07-2025` before running. "
    "See [Cohere's retirement notice](https://docs.cohere.com/changelog/2026-04-04-embed-v2-aya-8b-retirement)."
)
COHERE_VISION_MIGRATION_STEP = (
    "Use Command A Vision",
    "Replace `c4ai-aya-vision-8b` with `command-a-vision-07-2025` in the saved Python file before running.",
    None,
)
GROQ_MODEL_MIGRATIONS: dict[str, tuple[str, str, str]] = {
    "llama-3.3-70b-versatile": (
        "For free and developer tiers, Groq will shut down `llama-3.3-70b-versatile` on August 16, 2026. Replace it with `openai/gpt-oss-120b` before that date.",
        "Replace Llama 3.3",
        "Replace `llama-3.3-70b-versatile` with `openai/gpt-oss-120b` in the saved file.",
    ),
    "qwen/qwen3-32b": (
        "Groq shut down `qwen/qwen3-32b` for free and developer tiers on July 17, 2026. Replace it with `qwen/qwen3.6-27b`.",
        "Replace Qwen3 32B",
        "Replace `qwen/qwen3-32b` with `qwen/qwen3.6-27b` in the saved file.",
    ),
    "meta-llama/llama-4-scout-17b-16e-instruct": (
        "Groq shut down `meta-llama/llama-4-scout-17b-16e-instruct` for free and developer tiers on July 17, 2026. Replace it with the vision-capable `qwen/qwen3.6-27b`.",
        "Replace Llama 4 Scout",
        "Replace `meta-llama/llama-4-scout-17b-16e-instruct` with `qwen/qwen3.6-27b` in the saved file.",
    ),
    "deepseek-r1-distill-llama-70b": (
        "Groq retired `deepseek-r1-distill-llama-70b` on October 2, 2025. Replace it with `openai/gpt-oss-120b`.",
        "Replace DeepSeek R1 Distill",
        "Replace `deepseek-r1-distill-llama-70b` with `openai/gpt-oss-120b` in the saved file.",
    ),
    "deepseek-r1-distill-llama-70b-specdec": (
        "Groq retired `deepseek-r1-distill-llama-70b-specdec` on March 24, 2025. Replace it with `openai/gpt-oss-120b`.",
        "Replace DeepSeek R1 SpecDec",
        "Replace `deepseek-r1-distill-llama-70b-specdec` with `openai/gpt-oss-120b` in the saved file.",
    ),
    "Qwen-2.5-32b": (
        "Groq retired the source's `Qwen-2.5-32b` model in April 2025. Replace it with `qwen/qwen3.6-27b`.",
        "Replace Qwen 2.5 32B",
        "Replace `Qwen-2.5-32b` with `qwen/qwen3.6-27b` in the saved file.",
    ),
    "Deepseek-r1-distill-qwen-32b": (
        "Groq retired the source's `Deepseek-r1-distill-qwen-32b` model in April 2025. Replace it with `qwen/qwen3.6-27b`.",
        "Replace DeepSeek Qwen Distill",
        "Replace `Deepseek-r1-distill-qwen-32b` with `qwen/qwen3.6-27b` in the saved file.",
    ),
}
AZURE_FOUNDRY_RETIRED_VISION_WARNING = (
    "Microsoft retired `Llama-3.2-11B-Vision-Instruct` on June 13, 2026. Deploy "
    "`Llama-4-Scout-17B-16E-Instruct`, point `AZURE_ENDPOINT` at that deployment, "
    "and replace the model ID before running. See the "
    "[Azure model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule?view=foundry-classic)."
)
AZURE_FOUNDRY_VISION_MIGRATION_STEP = (
    "Use Llama 4 Scout",
    "Deploy `Llama-4-Scout-17B-16E-Instruct`, update `AZURE_ENDPOINT`, and replace `Llama-3.2-11B-Vision-Instruct` in the saved file.",
    None,
)
LITELLM_STEP = (
    "Start LiteLLM",
    "Start the local OpenAI-compatible proxy on port 4000:",
    "litellm --model gpt-4o --host 127.0.0.1 --port 4000",
)
MCP_TOOLBOX_STEP = (
    "Start MCP Toolbox",
    "Start the demo database and toolbox service on port 5001:",
    "cd cookbook/91_tools/mcp/mcp_toolbox_demo\ndocker compose up -d\ncd ../../../..",
)
CLIENT_SERVER_STEP = (
    "Start the AgentOS server",
    "In another terminal, start the [client example server](/examples/agent-os/client/server) on port 7777:",
    "python cookbook/05_agent_os/client/server.py",
)
AUTHENTICATED_MONGODB_STEP = (
    "Run MongoDB",
    None,
    "docker run -d -p 27017:27017 --name mongodb "
    "-e MONGO_INITDB_ROOT_USERNAME=mongoadmin "
    "-e MONGO_INITDB_ROOT_PASSWORD=secret mongo:latest",
)
VIDEO_PATH_STEP = (
    "Set the video path",
    "Replace `{video with location}` in the prompt with the path to a local video file.",
    None,
)
SLACK_INTERFACE_STEP = (
    "Configure Slack",
    "Complete [Slack setup](/agent-os/interfaces/slack/setup): create and install the app, "
    "expose the server through public HTTPS, and add the scopes listed in the example. "
    "The default event request URL is `<public-url>/slack/events`; HITL examples also use "
    "`<public-url>/slack/interactions` for interactivity. Use any custom prefix shown in "
    "the example instead of `/slack`.",
    None,
)

SOURCE_RENDER_OVERRIDES: dict[str, dict[str, object]] = {
    "integrations/parallel/07_research_workflow.py": {
        "intro_override": "Run source gathering and cited-brief writing as defined workflow steps. Agent outputs can vary between runs.",
    },
    "00_quickstart/agent_search_over_knowledge.py": {
        "package_add": {"beautifulsoup4"},
    },
    "00_quickstart/run.py": {
        # The documented prerequisite runs agent_search_over_knowledge.py,
        # whose URL insert selects WebsiteReader at runtime.
        "package_add": {"beautifulsoup4"},
    },
    "02_agents/07_knowledge/knowledge_filters.py": {
        "pre_code_warning": "The pinned source inserts `ThaiRecipes.pdf` without cuisine metadata, so its static and agentic cuisine filters cannot match that document. Add `metadata={\"cuisine\": \"thai\"}` to `knowledge.insert(...)` before running.",
    },
    "06_storage/sqlite/sqlite_for_team.py": {
        "pre_code_warning": "The pinned source docstring names a removed cookbook path. Use the generated Run step below, which runs `cookbook/06_storage/sqlite/sqlite_for_team.py`.",
    },
    "91_tools/google_bigquery_tools.py": {
        "intro_override": "Configure GoogleBigQueryTools with a Google Cloud project, location, and dataset.",
        "pre_code_warning": "The pinned source docstring names `BQTools`, and its Agent instruction names `run_sql`. The imported toolkit is `GoogleBigQueryTools`; its registered SQL function is `run_sql_query`.",
    },
    "02_agents/01_quickstart/agent_with_tools.py": {
        "suppress_intro": True,
    },
    "05_agent_os/scheduler/scheduler_tools_agent.py": {
        "intro_override": "Serve an AgentOS scheduler agent, then use a separate chat process to create and manage recurring schedules.",
        "run_title": "Start AgentOS",
        "run_command": "python scheduler_tools_agent.py serve",
        "run_after": "Keep the server running while you use the chat process.",
        "post_run_steps": [
            (
                "Start the chat process",
                "In a second terminal in the same directory, start the chat client:",
                "python scheduler_tools_agent.py chat",
            )
        ],
    },
    "05_agent_os/team_tasks/team_tasks_streaming.py": {
        "pre_code_warning": "The pinned source docstring contains a stale file path and an invalid JSON request to a removed `/v1/.../runs/stream` route. Use the generated run and streaming steps below instead.",
        "run_title": "Start AgentOS",
        "run_after": "Keep the server running while you send the streaming request.",
        "post_run_steps": [
            (
                "Test task streaming",
                "In a second terminal, send form fields to the v2.7.4 team run endpoint:",
                "curl -N -X POST http://localhost:7777/teams/research-team/runs \\\n  -H \"Accept: text/event-stream\" \\\n  -F \"message=What are the key benefits of microservices architecture?\" \\\n  -F \"stream=true\"",
            )
        ],
    },
    "11_memory/memory_manager/03_custom_memory_instructions.py": {
        "intro_override": "Run one custom memory-capture scenario for academic interests, then a separate default scenario over multi-turn messages.",
    },
    "11_memory/06_multi_user_multi_session_chat_concurrent.py": {
        "intro_override": "A shared agent runs three user conversations concurrently with `asyncio.gather` and persists user memories across sessions.",
    },
    "04_workflows/02_conditional_execution/condition_with_parallel.py": {
        "suppress_intro": True,
        "pre_code_warning": "This example's sample input activates only the Hacker News branch. The code fence remains source-exact. Apply the input replacement below to exercise the Hacker News, web, and Exa branches together.",
        "pre_run_steps": [
            (
                "Exercise all research branches",
                "Replace all four `Latest AI developments in machine learning` inputs in the saved file with `AI research news`.",
                None,
            )
        ],
    },
    "04_workflows/08_human_in_the_loop/executor_hitl/08_agent_user_input_step.py": {
        "pre_code_warning": "The pinned source docstring points to `libs/agno/agno/test.py`, which does not exist. Use the generated run command below.",
    },
    "07_knowledge/04_advanced/05_knowledge_protocol.py": {
        "suppress_intro": True,
    },
    "02_agents/12_multimodal/image_to_text.py": {
        "pre_run_steps": [
            (
                "Add the sample image",
                "Place a JPEG named `sample.jpg` in the same directory as `image_to_text.py`.",
                None,
            )
        ],
    },
    "02_agents/12_multimodal/image_to_image.py": {
        # FalTools checks FAL_API_KEY, while fal-client authenticates with FAL_KEY.
        "env_add": {"FAL_KEY"},
        "env_values": {
            "FAL_API_KEY": "your_fal_key_here",
            "FAL_KEY": "your_fal_key_here",
        },
        "pre_code_warning": "The pinned source constructs `FalTools()` with `enable_image_to_image=False`, the toolkit default, so the `image_to_image` tool is unavailable as written. Apply the migration below before running it.",
        "pre_run_steps": [
            (
                "Enable image-to-image",
                "Replace `tools=[FalTools()]` with `tools=[FalTools(enable_generate_media=False, enable_image_to_image=True)]` in the saved file.",
                None,
            )
        ],
    },
    "02_agents/12_multimodal/image_to_audio.py": {
        "pre_run_steps": [
            (
                "Add the sample image",
                "Place a JPEG named `sample.jpg` in the same directory as `image_to_audio.py`.",
                None,
            )
        ],
    },
    "02_agents/12_multimodal/audio_streaming.py": {
        "pre_run_steps": [
            (
                "Create the output directory",
                "Create the directory used for the WAV file:",
                'python -c "from pathlib import Path; Path(\'tmp\').mkdir(parents=True, exist_ok=True)"',
            )
        ],
    },
    "02_agents/12_multimodal/video_caption.py": {
        # The source's prose paragraph is an incomplete install instruction.
        "suppress_intro": True,
        "pre_run_steps": [VIDEO_PATH_STEP],
    },
    "03_teams/19_multimodal/video_caption_generation.py": {
        "pre_run_steps": [VIDEO_PATH_STEP],
    },
    "02_agents/18_checkpointing/01_crash_recovery.py": {
        # CRASH_DB is an internal parent-to-worker handoff with a default.
        "env_remove": {"CRASH_DB"},
    },
    "02_agents/20_time_travel/02_fork_run.py": {
        "suppress_intro": True,
    },
    "02_agents/12_multimodal/media_input_for_tool.py": {
        "package_remove": {"openai"},
        "env_remove": {"OPENAI_API_KEY"},
        "provider_remove": {"OpenAI"},
    },
    "12_context/07_google_drive.py": {
        "env_add": {"GOOGLE_SERVICE_ACCOUNT_FILE"},
        "env_remove": {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID"},
    },
    "07_knowledge/05_integrations/rag/local_rag_langchain_qdrant.py": {
        "package_add": {"beautifulsoup4", "fastembed"},
        "service_remove": {"qdrant"},
    },
    "12_context/21_gdrive_office.py": {
        "package_add": {
            "google-api-python-client",
            "google-auth",
            "google-auth-httplib2",
            "python-docx",
            "openpyxl",
            "python-pptx",
        },
        "env_add": {"GOOGLE_SERVICE_ACCOUNT_FILE"},
        "env_remove": {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID"},
    },
    "07_knowledge/05_integrations/readers/docling/docling_audio.py": {
        "package_add": {"openai-whisper"},
        "repo_layout": True,
        "pre_run_steps": [
            (
                "Install FFmpeg",
                "Install the FFmpeg system package and verify it is available:",
                "ffmpeg -version",
            )
        ],
    },
    "07_knowledge/05_integrations/readers/docling/docling_documents.py": {
        "package_add": {"openai-whisper"},
        "repo_layout": True,
    },
    "07_knowledge/05_integrations/cloud/06_multi_source.py": {
        "package_remove": {"aioboto3", "boto3", "msal"},
        "env_remove": {
            "AWS_REGION",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
            "AZURE_CONTAINER",
            "AZURE_SAS_TOKEN",
            "AZURE_STORAGE_ACCOUNT",
            "AZURE_TENANT_ID",
            "GCP_PROJECT",
            "GCS_BUCKET_NAME",
            "GITHUB_DEFAULT_REPO",
            "GITHUB_TOKEN",
            "S3_BUCKET_NAME",
            "SHAREPOINT_CLIENT_ID",
            "SHAREPOINT_CLIENT_SECRET",
            "SHAREPOINT_HOSTNAME",
            "SHAREPOINT_SITE_ID",
            "SHAREPOINT_TENANT_ID",
        },
        "pre_run_steps": [
            (
                "Install optional cloud clients",
                "Install only the clients for the optional remote sources you enable:",
                "uv pip install -U boto3 aioboto3 google-cloud-storage msal azure-identity azure-storage-blob",
            ),
            (
                "Configure optional cloud sources",
                "Set only the variables for the remote sources you enable. GitHub uses `GITHUB_TOKEN` and optionally `GITHUB_DEFAULT_REPO`. S3 uses `S3_BUCKET_NAME` and `AWS_REGION`. Google Cloud Storage uses `GCS_BUCKET_NAME` and `GCP_PROJECT`. SharePoint uses `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`, `SHAREPOINT_HOSTNAME`, and optionally `SHAREPOINT_SITE_ID`. Azure Blob Storage uses `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_STORAGE_ACCOUNT`, and `AZURE_CONTAINER`.",
                None,
            ),
        ],
    },
    "03_teams/05_knowledge/01_team_with_knowledge.py": {
        "env_remove": {"LANCEDB_API_KEY"},
    },
    "03_teams/22_metrics/06_loop_team_and_member_metrics.py": {
        # The Azure endpoint and key are optional OpenAI-compatible overrides.
        "env_remove": {"AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"},
    },
    "03_teams/23_checkpointing/01_crash_recovery.py": {
        # CRASH_DB is an internal parent-to-worker handoff with a default.
        "env_remove": {"CRASH_DB"},
        "suppress_intro": True,
    },
    "03_teams/25_time_travel/01_continue_from.py": {
        "intro_override": "Continue a completed team run from a selected message boundary with `acontinue_run()`.",
    },
    "04_workflows/06_advanced_concepts/run_control/remote_workflow.py": {
        "repo_layout": True,
        "extra_add": {"os"},
        "package_add": {"chromadb", "ddgs", "openai", "sqlalchemy"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Configure the remote workflow",
                "Point the client at the companion server and its registered workflow:",
                "export AGNO_REMOTE_BASE_URL=http://localhost:7778\nexport AGNO_REMOTE_WORKFLOW_ID=qa-workflow",
            ),
            (
                "Start the remote AgentOS",
                "In another terminal, start the server that registers `qa-workflow`:",
                "python cookbook/05_agent_os/remote/server.py",
            ),
        ],
    },
    "04_workflows/06_advanced_concepts/run_control/executor_events.py": {
        "intro_override": "Setting `stream_executor_events=False` suppresses intermediate executor events. Terminal executor events still propagate.",
    },
    "04_workflows/06_advanced_concepts/run_control/event_storage.py": {
        "package_remove": {"fastapi"},
    },
    "04_workflows/08_human_in_the_loop/error/01_error_retry_skip.py": {
        "package_remove": {"fastapi"},
        "pre_code_warning": "The source fails the simulated API call 99% of the time but prints that the failure rate is 70%.",
    },
    "04_workflows/06_advanced_concepts/long_running/disruption_catchup.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"ddgs", "openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the workflow server",
                "In another terminal, start the AgentOS server that registers `content-creation-workflow`:",
                "python cookbook/05_agent_os/workflow/basic_workflow.py",
            )
        ],
    },
    "04_workflows/06_advanced_concepts/long_running/events_replay.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"ddgs", "openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the workflow server",
                "In another terminal, start the AgentOS server that registers `content-creation-workflow`:",
                "python cookbook/05_agent_os/workflow/basic_workflow.py",
            )
        ],
    },
    "04_workflows/06_advanced_concepts/long_running/websocket_reconnect.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"ddgs", "openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the workflow server",
                "In another terminal, start the AgentOS server that registers `content-creation-workflow`:",
                "python cookbook/05_agent_os/workflow/basic_workflow.py",
            )
        ],
    },
    "04_workflows/06_advanced_concepts/background_execution/websocket_server.py": {
        # Plain uvicorn does not include a WebSocket protocol implementation.
        "package_add": {"websockets"},
    },
    "04_workflows/06_advanced_concepts/background_execution/websocket_client.py": {
        "repo_layout": True,
        "needs_agno": True,
        "package_add": {"ddgs", "fastapi", "openai", "sqlalchemy", "uvicorn[standard]"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the WebSocket server",
                "In another terminal, start the companion server on `ws://localhost:8000/ws`:",
                "python cookbook/04_workflows/06_advanced_concepts/background_execution/websocket_server.py",
            )
        ],
    },
    "93_components/get_agent.py": {
        "repo_layout": True,
        "package_add": {"openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Save the agent",
                "Persist the `agno-agent` record before loading it:",
                "python cookbook/93_components/save_agent.py",
            )
        ],
    },
    "93_components/get_team.py": {
        "repo_layout": True,
        "package_add": {"openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Save the team",
                "Persist the `content-team` record before loading it:",
                "python cookbook/93_components/save_team.py",
            )
        ],
    },
    "93_components/get_workflow.py": {
        "repo_layout": True,
        "package_add": {"openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Save the workflow",
                "Persist the `content-creation-workflow` record before loading it:",
                "python cookbook/93_components/save_workflow.py",
            )
        ],
    },
    "90_models/openai/chat/access_memories_in_memory_completed_event.py": {
        "package_add": {"pgvector"},
    },
    "90_models/litellm_openai/audio_input_agent.py": {
        "package_add": {"litellm[proxy]"},
        "package_remove": {"litellm"},
        "env_add": {"LITELLM_API_KEY", "OPENAI_API_KEY"},
        "intro_override": "Download an MP3 and pass it as audio input to a `gpt-audio` model served by a local LiteLLM proxy.",
        "pre_run_steps": [
            (
                "Start LiteLLM",
                "Start the audio-capable local proxy on port 4000:",
                "litellm --model gpt-audio --host 127.0.0.1 --port 4000",
            )
        ],
    },
    "05_agent_os/remote/adk_server.py": {
        "package_add": {"google-adk", "a2a-sdk"},
        "env_add": {"GOOGLE_API_KEY"},
    },
    "observability/arize_phoenix_via_openinference.py": {
        "package_add": {"openinference-instrumentation-agno"},
    },
    "observability/arize_phoenix_via_openinference_local.py": {
        "package_add": {"openinference-instrumentation-agno"},
        "pre_run_steps": [
            (
                "Start Phoenix",
                "Start the local Phoenix receiver on port 6006:",
                "python -m phoenix.server.main serve",
            )
        ],
    },
    "observability/workflows/arize_phoenix_via_openinference_workflow.py": {
        "package_add": {"openinference-instrumentation-agno"},
    },
    "observability/mlflow_via_openinference.py": {
        "package_add": {"mlflow"},
        "pre_run_steps": [
            (
                "Start MLflow",
                "Start the local MLflow receiver on port 5000:",
                "mlflow server --host 127.0.0.1 --port 5000",
            )
        ],
    },
    "observability/mlflow_via_autolog.py": {
        "package_add": {"mlflow"},
        "pre_run_steps": [
            (
                "Start MLflow",
                "Start the local MLflow receiver on port 5000:",
                "mlflow server --host 127.0.0.1 --port 5000",
            )
        ],
    },
    "observability/langwatch_op.py": {"env_add": {"LANGWATCH_API_KEY"}},
    "observability/maxim_ops.py": {
        "package_add": {"maxim-py"},
        "env_add": {"MAXIM_API_KEY", "MAXIM_LOG_REPO_ID"},
    },
    "observability/latitude_via_openinference.py": {
        "env_add": {"LATITUDE_PROJECT"},
    },
    "observability/opik_via_openinference.py": {
        "env_add": {"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"},
    },
    "observability/traceloop_op.py": {"env_add": {"TRACELOOP_API_KEY"}},
    "09_evals/agent_as_judge/agent_as_judge_batch.py": {
        "env_add": {"OPENAI_API_KEY"},
        "pre_code_warning": "The pinned source reads `eval_runs[-1]`, but `SqliteDb.get_eval_runs()` returns the newest evaluation first. Replace the index before running so the reported ID belongs to the evaluation that just completed.",
        "pre_run_steps": [
            (
                "Read the latest evaluation",
                "Replace `latest = eval_runs[-1]` with `latest = eval_runs[0]` in the saved file.",
                None,
            )
        ],
    },
    "09_evals/performance/comparison/autogen_instantiation.py": {
        "env_add": {"OPENAI_API_KEY"},
        "package_add": {"autogen-ext[openai]"},
        "package_remove": {"autogen-ext"},
    },
    "09_evals/performance/comparison/langgraph_instantiation.py": {
        "env_add": {"OPENAI_API_KEY"},
    },
    "09_evals/performance/db_logging.py": {
        "needs_pgvector": False,
        "pre_run_steps": [
            (
                "Start Postgres",
                "Start Postgres on the port used by this example:",
                "docker run -d --name postgres -e POSTGRES_USER=ai -e POSTGRES_PASSWORD=ai -e POSTGRES_DB=ai -p 5432:5432 postgres:17",
            )
        ],
    },
    "03_teams/16_search_coordination/03_distributed_infinity_search.py": {
        "pre_run_steps": [INFINITY_STEP],
    },
    "07_knowledge/05_integrations/rag/agentic_rag_infinity_reranker.py": {
        "intro_override": "Run agentic RAG over the Agno docs with LanceDB hybrid search, Cohere embeddings, and a local Infinity reranker on port 7997.",
        "pre_run_steps": [INFINITY_STEP],
    },
    "90_models/vllm/basic.py": {
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM in the environment that will serve the model:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "Serve the model used by this example:",
                "vllm serve Qwen/Qwen2.5-7B-Instruct",
            )
        ],
    },
    "90_models/vllm/db.py": {
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM in the environment that will serve the model:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "Serve the model used by this example:",
                "vllm serve Qwen/Qwen2.5-7B-Instruct",
            )
        ],
    },
    "90_models/vllm/memory.py": {
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM in the environment that will serve the model:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "Serve the model used by this example with tool calling enabled:",
                "vllm serve microsoft/Phi-3-mini-128k-instruct --dtype float32 --enable-auto-tool-choice --tool-call-parser pythonic",
            )
        ],
    },
    "90_models/vllm/tool_use.py": {
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM in the environment that will serve the model:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "Serve the model used by this example with automatic tool calling enabled:",
                "vllm serve NousResearch/Nous-Hermes-2-Mistral-7B-DPO --enable-auto-tool-choice --tool-call-parser hermes",
            ),
        ],
    },
    # The pinned retry example imports a nonexistent ``vLLM`` symbol and fails
    # before model authentication. Keep its setup unchanged until the cookbook
    # source is fixed and regenerated.
    "90_models/vllm/retry.py": {"env_remove": {"VLLM_API_KEY"}},
    "90_models/google/gemini/vertexai_with_credentials.py": {
        "pre_run_steps": [
            (
                "Provide service account credentials",
                "Load a `google.oauth2.service_account.Credentials` object and replace the placeholder project ID before running the example.",
                None,
            )
        ],
    },
    "90_models/cohere/image_agent.py": {
        "pre_code_warning": COHERE_RETIRED_VISION_WARNING,
        "pre_run_steps": [COHERE_VISION_MIGRATION_STEP],
    },
    "90_models/cohere/image_agent_bytes.py": {
        "pre_code_warning": COHERE_RETIRED_VISION_WARNING,
        "pre_run_steps": [COHERE_VISION_MIGRATION_STEP],
    },
    "90_models/cohere/image_agent_local_file.py": {
        "pre_code_warning": COHERE_RETIRED_VISION_WARNING,
        "pre_run_steps": [COHERE_VISION_MIGRATION_STEP],
    },
    "90_models/lmstudio/basic.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/db.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/image_agent.py": {"pre_run_steps": [LMSTUDIO_VISION_STEP]},
    "90_models/lmstudio/knowledge.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/memory.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/retry.py": {"pre_run_steps": [LMSTUDIO_RETRY_STEP]},
    "90_models/lmstudio/structured_output.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/tool_use.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/meta/llama_openai/metrics.py": {
        "pre_code_warning": "The pinned source reads `agent.run_response.messages`, but `Agent` does not expose that attribute. Update the saved file before running.",
        "pre_run_steps": [
            (
                "Correct the message metrics loop",
                "Replace `agent.run_response.messages` with `run_response.messages` in the saved file.",
                None,
            )
        ],
    },
    "90_models/llama_cpp/basic.py": {
        "pre_run_steps": [LLAMA_CPP_INSTALL_STEP, LLAMA_CPP_STEP]
    },
    "90_models/llama_cpp/structured_output.py": {
        "pre_run_steps": [LLAMA_CPP_INSTALL_STEP, LLAMA_CPP_STEP]
    },
    "90_models/llama_cpp/tool_use.py": {
        "pre_run_steps": [LLAMA_CPP_INSTALL_STEP, LLAMA_CPP_STEP]
    },
    "91_tools/moviepy_video_tools.py": {"pre_run_steps": [VIDEO_PATH_STEP]},
    "91_tools/mlx_transcribe_tools.py": {
        "pre_code_warning": (
            "Run this example on macOS or Linux with a supported MLX backend. Windows is not supported. "
            "Linux requires one of `mlx[cpu]`, `mlx[cuda12]`, or `mlx[cuda13]`. See "
            "[MLX installation](https://ml-explore.github.io/mlx/build/html/install.html)."
        ),
        "pre_run_steps": [
            (
                "Install an MLX backend",
                "On macOS, the dependency step installs the standard MLX package. On Linux, install exactly one backend for your hardware before running: `uv pip install -U \"mlx[cpu]\"`, `uv pip install -U \"mlx[cuda12]\"`, or `uv pip install -U \"mlx[cuda13]\"`.",
                None,
            ),
            (
                "Install ffmpeg",
                "Install `ffmpeg` using the macOS or Ubuntu command in the source header.",
                None,
            ),
            (
                "Add an audio file",
                "For a standalone file, replace the `agno_root_dir` assignment with "
                "`agno_root_dir = Path(__file__).parent.resolve()`. Save the code as "
                "`mlx_transcribe_tools.py`, then add the audio file to `storage/audio` "
                "beside the script.",
                None,
            ),
        ],
    },
    "91_tools/discord_tools.py": {
        "pre_run_steps": [
            (
                "Configure the Discord bot and IDs",
                "Create a Discord application and bot. Enable the Message Content privileged intent in the bot settings, then install the bot in the target server with the `bot` scope and View Channels, Send Messages, and Read Message History permissions. Grant Manage Messages only if you enable deletion. Enable Developer Mode in Discord, then replace `YOUR_CHANNEL_ID` and `YOUR_SERVER_ID` in the saved Python file with IDs copied from that server.",
                None,
            )
        ],
    },
    "90_models/ollama/chat/demo_gemma.py": {
        "pre_run_steps": [
            (
                "Add the sample image",
                "Place an image named `super-agents.png` in the same directory as the script, or update `image_path` to point to your own image.",
                None,
            )
        ],
    },
    "90_models/ollama/chat/image_agent.py": {
        "pre_run_steps": [
            (
                "Add the sample image",
                "Place an image named `super-agents.png` in the same directory as the script, or update `image_path` to point to your own image.",
                None,
            )
        ],
    },
    "90_models/litellm_openai/basic.py": {
        "package_add": {"litellm[proxy]"},
        "package_remove": {"litellm"},
        "env_add": {"LITELLM_API_KEY", "OPENAI_API_KEY"},
        "pre_run_steps": [LITELLM_STEP],
    },
    "90_models/litellm_openai/tool_use.py": {
        "package_add": {"litellm[proxy]"},
        "package_remove": {"litellm"},
        "env_add": {"LITELLM_API_KEY", "OPENAI_API_KEY"},
        "pre_run_steps": [LITELLM_STEP],
    },
    "05_agent_os/remote/02_remote_team.py": {
        "repo_layout": True,
        "extra_add": {"os"},
        "package_add": {"chromadb", "ddgs", "openai", "sqlalchemy"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_code_warning": "The pinned source docstring names removed `agent_os_setup.py` and `AgentOSRunner`. Start `server.py` in the generated Run step below; this example uses `RemoteTeam`.",
        "pre_run_steps": [
            (
                "Start the remote AgentOS",
                "In another terminal, start the server on port 7778:",
                "python cookbook/05_agent_os/remote/server.py",
            )
        ],
    },
    "05_agent_os/remote/06_remote_agent_as_team_member.py": {
        "repo_layout": True,
        "extra_add": {"os"},
        "package_add": {"chromadb", "ddgs", "openai", "sqlalchemy"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the remote AgentOS",
                "In another terminal, start the server on port 7778:",
                "python cookbook/05_agent_os/remote/server.py",
            )
        ],
    },
    "05_agent_os/remote/07_a2a_agent_as_team_member.py": {
        "repo_layout": True,
        "extra_add": {"a2a", "os"},
        "package_add": {"a2a-sdk", "chromadb", "ddgs", "openai", "sqlalchemy"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the A2A server",
                "In another terminal, start the server on port 7779:",
                "python cookbook/05_agent_os/remote/agno_a2a_server.py",
            )
        ],
    },
    "05_agent_os/learnings/rest_api_learnings.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"openai", "sqlalchemy"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start AgentOS",
                "In another terminal, start the learnings server on port 7777:",
                "python cookbook/05_agent_os/learnings/learnings_with_agentos.py",
            )
        ],
    },
    "05_agent_os/mcp_demo/test_client.py": {
        "repo_layout": True,
        "extra_add": {"mcp", "os"},
        "package_add": {"anthropic", "ddgs", "sqlalchemy"},
        "env_add": {"ANTHROPIC_API_KEY"},
        "pre_run_steps": [
            (
                "Start the AgentOS MCP server",
                "In another terminal, start the server on port 7777:",
                "python cookbook/05_agent_os/mcp_demo/mcp_server_example.py",
            )
        ],
    },
    "05_agent_os/mcp_demo/dynamic_headers/client.py": {
        "intro_override": "Forward per-run user and session context from AgentOS to an MCP server with dynamic HTTP headers.",
        "package_add": {"fastmcp"},
        "pre_run_steps": [
            (
                "Start the MCP server",
                "Follow the [server example](/examples/agent-os/mcp-demo/dynamic-headers/server) to save `server.py`, then start it in another terminal and keep it running:",
                "python server.py",
            )
        ],
    },
    "05_agent_os/integrations/shopify_demo.py": {
        "intro_override": "For a new app on your own store, create and install it in Shopify's [Dev Dashboard](https://shopify.dev/docs/apps/build/dev-dashboard/create-apps-using-dev-dashboard), request an access token with the [client credentials grant](https://shopify.dev/docs/apps/build/dev-dashboard/get-api-access-tokens), and export the returned token as `SHOPIFY_ACCESS_TOKEN`. The Shopify Admin path in the pinned source applies only to existing admin-created custom apps.",
    },
    "90_models/google/gemini/image_editing.py": {
        "pre_run_steps": [
            (
                "Use an image-generation model",
                "Before running the source-fidelity code, change `gemini-3.5-flash` to `gemini-3.1-flash-image`. Gemini 3.5 Flash accepts image input but does not generate images.",
                None,
            )
        ],
    },
    "90_models/google/gemini/image_generation.py": {
        "pre_run_steps": [
            (
                "Use an image-generation model",
                "Before running the source-fidelity code, change `gemini-3.5-flash` to `gemini-3.1-flash-image`. Gemini 3.5 Flash accepts image input but does not generate images.",
                None,
            )
        ],
    },
    "90_models/google/gemini_interactions/image_generation.py": {
        "pre_run_steps": [
            (
                "Use the stable image model",
                "Before running the source-fidelity code, change `gemini-3.1-flash-image-preview` to `gemini-3.1-flash-image`. The preview model has been shut down.",
                None,
            )
        ],
    },
    "05_agent_os/interfaces/whatsapp/image_generation_model.py": {
        "pre_run_steps": [
            (
                "Use the stable image model",
                "Before running the source-fidelity code, change `gemini-3-pro-image-preview` to `gemini-3-pro-image`. The preview model has been shut down.",
                None,
            )
        ],
    },
    "05_agent_os/interfaces/whatsapp/agent_with_media.py": {
        "pre_run_steps": [
            (
                "Expose the server",
                "Start ngrok for port 7777 and copy its public HTTPS URL. Keep ngrok running:",
                "ngrok http 7777",
            )
        ],
        "run_title": "Start AgentOS",
        "run_after": "Keep the server running while you configure and verify the webhook.",
        "post_run_steps": [
            (
                "Configure the webhook",
                "Follow [WhatsApp setup](/agent-os/interfaces/whatsapp/setup). In Meta, set the callback URL to `https://<your-ngrok-url>/whatsapp/webhook`, use the same verify token as `WHATSAPP_VERIFY_TOKEN`, and subscribe to the `messages` field. Verify the webhook while AgentOS and ngrok are running.",
                None,
            )
        ],
    },
    "90_models/xai/finance_agent.py": {
        "intro_override": "Use YFinanceTools with Grok to report stock prices, analyst recommendations, company data, and news.",
    },
    "91_tools/mcp/pipedream_linkedin.py": {
        "intro_override": "The pinned source uses a retired Pipedream per-app SSE URL and cannot connect to the current service without code and authentication changes. See [Pipedream MCP](https://pipedream.com/docs/connect/mcp) for the current connection flows.",
    },
    "91_tools/mcp/pipedream_slack.py": {
        "intro_override": "The source-fidelity example uses Pipedream's retired per-app SSE URL and cannot connect to the current service without code and authentication changes.",
        "replacement_only": True,
        "replacement_heading": "Current Status",
        "run_replacement": "<Warning>\n  This v2.7.4 example cannot connect to the current Pipedream MCP service as written. End users should use Pipedream's OAuth-authenticated v2 setup. Application developers should use the authenticated v3 endpoint. See [Pipedream MCP for end users](https://pipedream.com/docs/connect/mcp/users) and [Develop with Pipedream MCP](https://pipedream.com/docs/connect/mcp/developers).\n</Warning>",
    },
    "91_tools/async_generator_tool_with_pydantic_args.py": {
        "pre_code_warning": "The pinned source omits `stream_events=True`, so Agno discards the yielded custom progress events and both final assertions fail. Add the option before running.",
        "pre_run_steps": [
            (
                "Enable custom events",
                "In the saved file, add `stream_events=True` next to `stream=True` in the `agent.arun()` call.",
                None,
            )
        ],
    },
    "91_tools/mcp/graphiti.py": {
        "intro_override": "Use Agno's MCP integration with Graphiti to build a personal diary assistant that stores and recalls entries from a knowledge graph.",
        "pre_run_steps": [
            (
                "Start Graphiti MCP",
                "Start a Graphiti MCP server at `http://localhost:8000/sse`. See the [Graphiti MCP server instructions](https://github.com/getzep/graphiti/tree/main/mcp_server).",
                None,
            )
        ],
    },
    "91_tools/mcp/gibsonai.py": {
        "pre_run_steps": [
            (
                "Authenticate GibsonAI",
                "Install the Gibson CLI and authenticate before starting its MCP server:",
                "uvx --from gibson-cli@latest gibson auth login",
            )
        ],
    },
    "91_tools/mcp/sse_transport/client.py": {
        "intro_override": "Connect to MCP servers that use SSE transport with MCPTools and MultiMCPTools.",
        "repo_layout": True,
        "pre_run_steps": [
            (
                "Start the SSE server",
                "In another terminal, start the companion MCP server on port 8000:",
                "python cookbook/91_tools/mcp/sse_transport/server.py",
            )
        ],
    },
    "91_tools/mcp/mcp_toolbox_for_db.py": {
        "repo_layout": True,
        "pre_run_steps": [MCP_TOOLBOX_STEP],
    },
    "11_memory/integrations/dakera_integration.py": {
        "intro_override": "The source-fidelity example stores memory in self-hosted Dakera, then sends recalled memory to OpenAI as agent context. Its pinned client targets an older Dakera API and requires migration before use.",
    },
    "03_teams/19_multimodal/generate_image_with_team.py": {
        "intro_override": "The source-fidelity team uses `DalleTools`, whose supported DALL-E models are deprecated. Migrate the image member to GPT Image 2 before use.",
    },
    "05_agent_os/interfaces/telegram/agent_with_media.py": {
        "intro_override": "The Telegram bot's DALL-E image path requires migration to GPT Image 2. Its media analysis and ElevenLabs paths remain as shown.",
    },
    "07_knowledge/05_integrations/rag/agentic_rag_with_lightrag.py": {
        "repo_layout": True,
        "env_remove": {"LIGHTRAG_API_KEY"},
        "intro_override": "Load a PDF, a Wikipedia topic, and a URL into a LightRAG-backed knowledge base and query it with an agent.",
        "pre_run_steps": [
            (
                "Start LightRAG",
                "Start a LightRAG server at `http://localhost:9621` before running the example. Set `LIGHTRAG_API_KEY` only if the server requires authentication.",
                None,
            )
        ],
    },
    "05_agent_os/dbs/singlestore.py": {
        "pre_run_steps": [
            (
                "Prepare SingleStore",
                "Start a SingleStore database named `ai` at `localhost:3306` with the credentials in the source.",
                None,
            )
        ],
    },
    "06_storage/mongo/async_mongo/async_mongodb_for_agent.py": {
        "service_remove": {"mongodb"},
        "pre_run_steps": [AUTHENTICATED_MONGODB_STEP],
    },
    "06_storage/mongo/async_mongo/async_mongodb_for_team.py": {
        "service_remove": {"mongodb"},
        "pre_run_steps": [AUTHENTICATED_MONGODB_STEP],
    },
    "06_storage/mongo/async_mongo/async_mongodb_for_workflow.py": {
        "service_remove": {"mongodb"},
        "pre_run_steps": [AUTHENTICATED_MONGODB_STEP],
    },
    "91_tools/searxng_tools.py": {
        "pre_run_steps": [
            (
                "Start SearxNG",
                "Start a SearxNG instance at `http://localhost:53153` before running the example.",
                None,
            )
        ],
    },
    "91_tools/spotify_tools.py": {
        "pre_run_steps": [
            (
                "Create a Spotify access token",
                "Create a Spotify OAuth user access token with `user-read-private` and the playlist scopes required by your playlist visibility: `playlist-modify-public` and/or `playlist-modify-private`. See [Spotify authorization scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes).",
                None,
            )
        ],
    },
    "05_agent_os/client_a2a/servers/google_adk_server.py": {
        "package_add": {"google-adk", "a2a-sdk", "uvicorn"},
        "env_add": {"GOOGLE_API_KEY"},
        "run_title": "Start the server",
        "run_after": "The server listens at `http://localhost:8001` by default.",
    },
    "02_agents/16_skills/sample_skills/code-review/scripts/check_style.py": {
        "run_command": "python check_style.py < path/to/file.py",
    },
    "02_agents/16_skills/sample_skills/git-workflow/scripts/commit_message.py": {
        "run_command": "python commit_message.py validate \"feat: add search\"",
    },
    "05_agent_os/skills/sample_skills/system-info/scripts/list_directory.py": {
        "run_note": "The system-info skill executes this helper as a subprocess and passes the directory path as its first argument.",
    },
    "05_agent_os/human_in_the_loop/workflow/workflow_db.py": {
        "run_note": "This shared database module is imported by the workflow examples in the same directory.",
    },
    "05_agent_os/dbs/surreal_db/teams.py": {
        "run_note": "This helper is imported by the SurrealDB AgentOS application.",
    },
    "05_agent_os/dbs/surreal_db/run.py": {
        "package_remove": {"firecrawl"},
        "pre_code_warning": "The source's search agent registers only Firecrawl scraping, while its finance agent registers only current-price lookup. Enable the tools promised by their roles before running. Also disable auto-reload so the MCP connection can keep one application lifespan.",
        "pre_run_steps": [
            (
                "Enable the promised research tools",
                "When saving `workflows.py`, replace `FirecrawlTools()` with `FirecrawlTools(enable_search=True)`. When saving `teams.py`, replace `YFinanceTools()` with `YFinanceTools(all=True)`.",
                None,
            ),
            (
                "Keep one MCP lifespan",
                "When saving `run.py`, replace `agent_os.serve(app=\"run:app\", reload=True)` with `agent_os.serve(app=\"run:app\")`.",
                None,
            ),
        ],
    },
    "05_agent_os/dbs/surreal_db/workflows.py": {
        "package_remove": {"fastapi", "firecrawl"},
        "run_note": "This helper is imported by the SurrealDB AgentOS application.",
    },
    # Confirmed post-generation curation. Keep these source-specific controls
    # next to the generator so regeneration reproduces the reviewed docs.
    "90_models/google/gemini/vertexai.py": {
        "suppress_intro": True,
    },
    "90_models/anthropic/prompt_caching.py": {
        "intro_override": "Use prompt caching with Anthropic agents to cache the system prompt passed to the model.",
    },
    "90_models/vertexai/claude/prompt_caching.py": {
        "intro_override": "Use prompt caching with Claude on Vertex AI to cache the system prompt passed to the model.",
    },
    "90_models/google/gemini/s3_url_file_input.py": {
        "pre_run_steps": [
            (
                "Configure AWS credentials",
                "Configure boto3 through environment variables, `~/.aws/credentials`, or an IAM role. The source presigns `s3://agno-public/recipes/ThaiRecipes.pdf`; if you use another object, update the bucket and key and give the AWS identity permission to read it.",
                None,
            )
        ],
    },
    "90_models/ollama/chat/retry.py": {
        "ollama_model_remove": {"ollama-wrong-id"},
        "pre_run_steps": [
            (
                "Prepare Ollama",
                "Install Ollama and start its local daemon at `http://localhost:11434`. Do not pull the deliberately invalid model ID because the source uses it to exercise retries.",
                "ollama serve",
            )
        ],
    },
    "04_workflows/08_human_in_the_loop/output_review/05_full_review_cycle.py": {
        "intro_override": "This workflow pauses after Agent A for output review, then supports approval, rejection with feedback and retry, or cancellation.",
    },
    "04_workflows/08_human_in_the_loop/executor_hitl/02_agent_confirmation_stream.py": {
        "intro_override": "This streaming variant of [Agent Confirmation](/examples/workflows/human-in-the-loop/executor-hitl/agent-confirmation) emits `StepExecutorPausedEvent` when the tool call pauses.",
    },
    "04_workflows/08_human_in_the_loop/dual_level_hitl/01_step_confirmation_and_tool_confirmation.py": {
        "intro_override": "The workflow pauses before the step runs, then pauses again before the agent's tool call.",
    },
    "04_workflows/08_human_in_the_loop/dual_level_hitl/02_step_user_input_and_tool_confirmation.py": {
        "intro_override": "The workflow collects the city at the step boundary, then pauses before the agent's tool call.",
    },
    "04_workflows/08_human_in_the_loop/dual_level_hitl/03_condition_and_tool_confirmation.py": {
        "intro_override": "The workflow asks whether to run the selected condition branch, then pauses before the branch agent's tool call.",
    },
    "04_workflows/08_human_in_the_loop/dual_level_hitl/04_router_selection_and_tool_confirmation.py": {
        "intro_override": "The workflow asks the user to choose a route, then pauses before the chosen agent's tool call.",
    },
    "04_workflows/08_human_in_the_loop/router/04_router_confirmation.py": {
        "intro_override": "The router selects a branch, then asks the user to confirm that selection before execution.",
    },
    "06_storage/in_memory/in_memory_storage_for_workflow.py": {
        "suppress_intro": True,
    },
    "06_storage/dynamodb/dynamo_for_team.py": {
        "suppress_intro": True,
    },
    "06_storage/singlestore/singlestore_for_team.py": {
        "env_remove": {"SINGLESTORE_SSL_CERT"},
    },
    "07_knowledge/02_building_blocks/02_hybrid_search.py": {
        "intro_override": "Compare vector, keyword, and hybrid search with Qdrant. See [Reranking](/examples/knowledge/building-blocks/reranking) to refine the results.",
    },
    "07_knowledge/04_advanced/02_custom_chunking.py": {
        "package_remove": {"rapidocr-onnxruntime"},
    },
    "07_knowledge/05_integrations/cloud/01_aws.py": {
        "env_add": {"AWS_S3_BUCKET"},
    },
    "07_knowledge/05_integrations/cloud/05_github_dynamic_repo.py": {
        "env_remove": {"GITHUB_TOKEN"},
    },
    "07_knowledge/05_integrations/readers/01_documents.py": {
        "repo_layout": True,
    },
    "07_knowledge/05_integrations/readers/docling/docling_images.py": {
        "repo_layout": True,
    },
    "07_knowledge/05_integrations/readers/docling/docling_markup.py": {
        "repo_layout": True,
    },
    "07_knowledge/05_integrations/readers/docling/docling_pdf.py": {
        "repo_layout": True,
    },
    "07_knowledge/05_integrations/readers/docling/docling_xlsx.py": {
        "intro_override": "Load one XLSX spreadsheet with DoclingReader in HTML output mode, then query its product and price data with an agent.",
        "repo_layout": True,
    },
    "08_learning/10_demo/agents.py": {
        "extra_add": {"os"},
        "repo_layout": True,
        "run_note": "This helper defines `ops_assistant` for the demo. Run `python cookbook/08_learning/10_demo/seed.py`, then `python cookbook/08_learning/10_demo/run.py` from the Agno repository root.",
    },
    "90_models/anthropic/image_input_local_file.py": {
        "intro_override": "Download a PNG locally and pass its filepath to Claude as an image input.",
    },
    "90_models/anthropic/image_input_file_upload.py": {
        "intro_override": "Upload a PNG through the Anthropic Files API and pass the returned file handle to Claude as an image input.",
    },
    "90_models/openai/chat/custom_role_map.py": {
        "env_remove": {"OPENAI_API_KEY"},
        "provider_remove": {"OpenAI"},
    },
    "90_models/openai/chat/pdf_input_file_upload.py": {
        "intro_override": "Pass a local PDF as base64-inlined file input to an OpenAI Chat agent.",
        "pre_code_warning": "The source docstring incorrectly refers to Google GenAI. `OpenAIChat` base64-inlines a local file path, contrary to the source comment's automatic large-file upload claim. The source also uses deprecated `gpt-4o`. Replace the model before running.",
        "pre_run_steps": [
            (
                "Download the sample PDF",
                "Download `ThaiRecipes.pdf` next to the saved script:",
                "python -c \"from urllib.request import urlretrieve; urlretrieve('https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf', 'ThaiRecipes.pdf')\"",
            ),
            (
                "Update the model",
                "Replace `OpenAIChat(id=\"gpt-4o\")` with `OpenAIChat(id=\"gpt-5.4-mini\")` in the saved file.",
                None,
            ),
        ],
    },
    "90_models/openai/responses/image_generation_agent.py": {
        "intro_override": "The source-fidelity code uses `OpenAIChat` and `gpt-image-1` despite its Responses category. Replace them with `OpenAIResponses` and `gpt-image-2` before running the example.",
        "pre_run_steps": [
            (
                "Use the Responses API",
                "Replace the `OpenAIChat` import and constructor with `OpenAIResponses(id=\"gpt-5.2\")`.",
                None,
            ),
            (
                "Encode the image bytes",
                "Add `import base64`. Encode `response.images[0].content` with `base64.b64encode(...).decode(\"utf-8\")`, then pass that string to `save_base64_data`.",
                None,
            )
        ],
    },
    "90_models/mistral/image_file_input_agent.py": {
        "intro_override": "The source-fidelity code uses deprecated `pixtral-12b-2409`. Replace it with `ministral-14b-2512` and add `sample.jpeg` before running the example.",
        "pre_run_steps": [
            (
                "Add the sample image",
                "Place a JPEG named `sample.jpeg` in the same directory as the code file.",
                None,
            ),
        ],
    },
    "90_models/google/gemini_interactions/deep_research_file_search.py": {
        "pre_run_steps": [
            (
                "Plan the File Search store lifecycle",
                "Each run creates a persistent File Search store. Reuse a populated store for repeated queries, and delete demo stores you no longer need in Google AI Studio or with the [File Search API](https://ai.google.dev/gemini-api/docs/file-search).",
                None,
            )
        ],
    },
    "12_context/02_web_exa_mcp.py": {
        "intro_override": "Use Exa's keyless MCP endpoint for web research. For direct SDK access, see [Exa Web Context](/examples/context/web-exa).",
    },
    "12_context/05_slack.py": {
        "env_remove": {"SLACK_TOKEN", "SLACK_USER_TOKEN"},
    },
    "12_context/06_slack_search_media.py": {
        "env_remove": {"SLACK_TOKEN", "SLACK_USER_TOKEN"},
    },
    "12_context/09_web_plus_slack.py": {
        "env_remove": {"SLACK_TOKEN", "SLACK_USER_TOKEN"},
    },
    "12_context/12_engineering_briefing.py": {
        "env_remove": {"SLACK_TOKEN", "SLACK_USER_TOKEN"},
        "pre_run_steps": [
            (
                "Prepare Slack channels",
                "Create public channels named `#agents` and `#test-agents`, then invite the Slack app to both. Update the hardcoded channel names in the prompt if you use different channels. See [chat.postMessage channel membership](https://api.slack.com/methods/chat.postMessage#channels).",
                None,
            )
        ],
    },
    "12_context/15_wiki_git.py": {
        "env_remove": {"WIKI_LOCAL_PATH"},
    },
    "12_context/15a_wiki_notion.py": {
        "env_remove": {"WIKI_LOCAL_PATH"},
    },
    "12_context/18_gmail.py": {
        "intro_override": "Compare Gmail read-only and read-write context. See [Calendar](/examples/context/calendar) and [Google Workspace](/examples/context/google-workspace) for related providers.",
    },
    # Fresh-eyes batch D.
    "90_models/llama_cpp/retry.py": {
        "pre_run_steps": [
            LLAMA_CPP_INSTALL_STEP,
            (
                "Start llama.cpp",
                "Serve `ggml-org/gpt-oss-20b-GGUF` at `http://127.0.0.1:8080/v1` so the deliberately invalid model ID exercises retries:",
                "llama-server -hf ggml-org/gpt-oss-20b-GGUF --ctx-size 0 --jinja -ub 2048 -b 2048",
            )
        ],
    },
    "90_models/dashscope/knowledge_tools.py": {
        "env_add": {"OPENAI_API_KEY"},
    },
    "90_models/litellm/append_trailing_user_message.py": {
        "env_add": {"ANTHROPIC_API_KEY"},
        "env_remove": {"LITELLM_API_KEY"},
        "env_title": "Export your Anthropic API key",
    },
    "90_models/nexus/retry.py": {
        "env_add": {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start Nexus",
                "Run a local [Nexus gateway](https://nexusrouter.com/docs) at `http://localhost:8000`. Configure the gateway with the provider keys exported above.",
                None,
            )
        ],
    },
    "90_models/perplexity/knowledge.py": {
        "env_add": {"OPENAI_API_KEY"},
    },
    "91_tools/tool_decorator/toolkit_per_tool_instructions.py": {
        "env_remove": {"OPENAI_API_KEY"},
    },
    "91_tools/mcp/mcp_toolbox_demo/agent_os.py": {
        "repo_layout": True,
        "pre_run_steps": [MCP_TOOLBOX_STEP],
    },
    "91_tools/mcp/mcp_toolbox_demo/agent.py": {
        "repo_layout": True,
        "pre_run_steps": [MCP_TOOLBOX_STEP],
    },
    "91_tools/mcp/mcp_toolbox_demo/hotel_management_typesafe.py": {
        "repo_layout": True,
        "pre_run_steps": [MCP_TOOLBOX_STEP],
    },
    "91_tools/mcp/mcp_toolbox_demo/hotel_management_workflows.py": {
        "repo_layout": True,
        "pre_run_steps": [MCP_TOOLBOX_STEP],
    },
    "91_tools/mcp/airbnb.py": {
        "intro_override": "Connect an OpenAI `gpt-4o` agent to the Airbnb MCP server over stdio and search property listings.",
    },
    "91_tools/google/gmail/daily_digest.py": {
        "intro_override": "Group recent emails by category and record a priority for each message in a structured daily digest.",
    },
    "91_tools/mcp/multiple_servers_allow_partial_failure.py": {
        "env_remove": {"ACCUWEATHER_API_KEY"},
    },
    "91_tools/mcp/include_exclude_tools.py": {
        "pre_run_steps": [
            (
                "Review the source limitation",
                'This example does not pass `GOOGLE_MAPS_API_KEY` to the Google Maps MCP server, and `include_tools=["airbnb_search"]` filters out every Maps tool. Correct both settings before running the restaurant query.',
                None,
            ),
            (
                "Update the sample times",
                "Replace the August 2025 Airbnb dates with future dates and replace `right now` with an explicit local date and time.",
                None,
            ),
        ],
    },
    "91_tools/mcp/oxylabs.py": {
        "env_remove": {"GOOGLE_API_KEY"},
    },
    "91_tools/mcp/stagehand.py": {
        "env_add": {"BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"},
        "intro_override": "Scrape Hacker News headlines and top comments into a structured reader's digest with the Stagehand MCP server.",
        "pre_run_steps": [
            (
                "Build the Stagehand MCP server",
                "Install Node.js, then clone and build the server in the directory where you will save `stagehand.py`:",
                "git clone https://github.com/browserbase/mcp-server-browserbase\ncd mcp-server-browserbase/stagehand\nnpm install\nnpm run build\ncd ../..",
            )
        ],
    },
    "91_tools/mcp/bgpt.py": {
        "env_remove": {"BGPT_API_KEY"},
        "pre_run_steps": [
            (
                "Configure optional BGPT access",
                "The free tier works without `BGPT_API_KEY`. Set it only when you need more than 50 results.",
                None,
            )
        ],
    },
    "91_tools/sql_tools.py": {
        "package_add": {"psycopg[binary]"},
    },
    # Fresh-eyes batch E.
    "91_tools/custom_tool_events.py": {
        "intro_override": "Yield custom events from a custom tool and consume them while streaming.",
    },
    "91_tools/docker_tools.py": {
        "pre_run_steps": [
            (
                "Start Docker",
                "Install Docker Desktop or Docker Engine, start the daemon, and verify the client can connect:",
                "docker ps",
            )
        ],
    },
    "91_tools/models/azure_openai_tools.py": {
        "intro_override": "This source-fidelity example uses `AzureOpenAITools`, whose supported DALL-E models are retired. It is preserved as a legacy reference.",
        "pre_code_warning": "Azure DALL-E 2 and DALL-E 3 deployments are retired, and the v2.7.4 toolkit supports no current image model. Do not run this source as written.",
        "replacement_only": True,
        "replacement_heading": "Current Alternatives",
        "run_replacement": "Use a current Azure image-generation client by following [Microsoft's migration guidance](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/dall-e), or use [Image Generation Agent](/models/providers/native/openai/responses/usage/image-generation-agent) with OpenAI GPT Image 2.",
    },
    "91_tools/jira_tools.py": {
        "env_add": {"JIRA_TOKEN"},
        "env_remove": {"JIRA_API_TOKEN", "JIRA_PASSWORD"},
        "pre_run_steps": [
            (
                "Choose Jira authentication",
                "`JIRA_TOKEN` is the preferred secret. To use a Jira password instead, replace `JIRA_TOKEN` with `JIRA_PASSWORD`.",
                None,
            )
        ],
    },
    "91_tools/website_tools.py": {
        "intro_override": "Use WebsiteTools to let an agent fetch and summarize a page. With no knowledge base attached, the toolkit registers one `read_url` function.",
    },
    "91_tools/google/sheets/action_tracker.py": {
        "env_add": {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID"},
        "pre_run_steps": [
            (
                "Configure the optional output sheet",
                "Set `ACTION_ITEMS_SHEET_ID` to write action items to a different spreadsheet. When unset, the example writes them to `MEETING_NOTES_SHEET_ID`.",
                None,
            )
        ],
    },
    "05_agent_os/demo.py": {
        "intro_override": "Authentication is optional. Set `OS_SECURITY_KEY` to enable it for this AgentOS.",
        "pre_run_steps": [
            (
                "Optional: enable authentication",
                "Set `OS_SECURITY_KEY` before running to require AgentOS authentication. Leave it unset to run without authentication.",
                None,
            )
        ],
    },
    "05_agent_os/advanced_demo/_agents.py": {
        "env_add": {"OPENAI_API_KEY"},
        "run_note": "This helper is imported by [Advanced Demo](/examples/agent-os/advanced-demo/demo). Keep it as `_agents.py` next to `demo.py`, then run the demo entry point.",
    },
    "05_agent_os/advanced_demo/demo.py": {
        "env_add": {"OPENAI_API_KEY"},
    },
    "05_agent_os/advanced_demo/mcp_demo.py": {
        "env_remove": {"GITHUB_ACCESS_TOKEN"},
        "pre_run_steps": [
            (
                "Choose the GitHub token name",
                "Export `GITHUB_TOKEN` as shown above. `GITHUB_ACCESS_TOKEN` is accepted as a fallback name for the same personal access token.",
                None,
            )
        ],
    },
    "05_agent_os/advanced_demo/_teams.py": {
        "run_note": "This helper is imported by [Advanced Demo](/examples/agent-os/advanced-demo/demo). Keep it as `_teams.py` next to `demo.py`, then run the demo entry point.",
    },
    "05_agent_os/client_a2a/05_connect_to_google_adk.py": {
        "repo_layout": True,
        "package_add": {"a2a-sdk", "google-adk", "uvicorn"},
        "env_add": {"GOOGLE_API_KEY"},
        "pre_run_steps": [
            (
                "Start the Google ADK server",
                "In another terminal, start the [Google ADK A2A server](/examples/agent-os/client-a2a/servers/google-adk-server) on port 8001:",
                "python cookbook/05_agent_os/client_a2a/servers/google_adk_server.py",
            )
        ],
    },
    "05_agent_os/client/12_continue_run_sse_reconnect.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the confirmation server",
                "In another terminal, start an AgentOS whose tool requires confirmation on port 7777:",
                "python cookbook/05_agent_os/human_in_the_loop/agent/agent_tool_requires_confirmation.py",
            )
        ],
    },
    "05_agent_os/customize/custom_health_endpoint.py": {
        "intro_override": "Add a custom health endpoint to an AgentOS FastAPI application.",
    },
    "05_agent_os/dbs/agentos_default_db.py": {
        "intro_override": "Authentication is optional. Set `OS_SECURITY_KEY` to enable it for this AgentOS.",
        "pre_run_steps": [
            (
                "Optional: enable authentication",
                "Set `OS_SECURITY_KEY` before running to require AgentOS authentication. Leave it unset to run without authentication.",
                None,
            )
        ],
    },
    "05_agent_os/dbs/dynamo.py": {
        "env_add": {"AWS_REGION"},
    },
    "05_agent_os/dbs/firestore.py": {
        "pre_run_steps": [
            (
                "Set the Firestore project",
                "Replace `PROJECT_ID = \"agno-os-test\"` in the code with a GCP project ID that has Firestore enabled.",
                None,
            )
        ],
    },
    "05_agent_os/dbs/neon.py": {
        "env_values": {
            "NEON_DB_URL": "postgresql+psycopg://user:password@ep-xxx.neon.tech/dbname?sslmode=require"
        },
    },
    "05_agent_os/interfaces/slack/hitl_required_approval.py": {
        "intro_override": "Build an infrastructure agent that requires administrator approval for database schema migrations. The `@approval` decorator persists approval records across restarts and provides an audit trail.",
    },
    "05_agent_os/interfaces/slack/hitl_user_input.py": {
        "intro_override": "Open engineering tickets from Slack conversations. The agent extracts `title` and `description`, then Slack collects `priority` and `component` before the tool runs.",
    },
    "05_agent_os/interfaces/slack/support_team.py": {
        "pre_run_steps": [
            (
                "Configure Slack",
                "Complete [Slack setup](/agent-os/interfaces/slack/setup): create the app, expose the local server through public HTTPS, and set the event request URL to `<public-url>/slack/events`. Add `search:read` under User Token Scopes, reinstall the app, and export its `xoxp-` User OAuth Token as `SLACK_USER_TOKEN`.",
                None,
            )
        ],
    },
    "05_agent_os/interfaces/agui/reasoning_agent.py": {
        "source_link_ref": "pinned-tag",
    },
    "05_agent_os/interfaces/telegram/reasoning_agent.py": {
        "intro_override": "Run a Telegram bot with structured reasoning, DuckDuckGo web search, and SQLite session persistence.",
    },
    # Fresh-eyes batch F. These controls capture setup or framing that cannot
    # be inferred reliably from the primary source file alone.
    "05_agent_os/knowledge/agno_docs_agent.py": {
        "package_add": {"beautifulsoup4"},
        "intro_override": "Serve an Agno docs knowledge agent through AgentOS. Its pinned media instruction branches require migration before use.",
        "pre_code_warning": "The pinned source tells the agent to call `text_to_speech` and `create_image`, but registers neither tool.",
        "pre_run_steps": [
            (
                "Remove the media instructions",
                "Delete the `Explain important concepts using audio` and `Explain concepts with images` branches from `instructions`. Remove `and optional audio explanations for complex concepts` from `description` before running.",
                None,
            )
        ],
    },
    "05_agent_os/mcp_demo/oauth_authkit_example.py": {
        "intro_override": "Pass a FastMCP AuthProvider as `mcp_auth` to delegate MCP OAuth to an external authorization server. This example uses WorkOS AuthKit for identity, RBAC, and SSO. See [Built-in OAuth](/examples/agent-os/mcp-demo/oauth-builtin-example) for AgentOS-hosted authorization.",
    },
    "05_agent_os/mcp_demo/oauth_builtin_example.py": {
        "intro_override": "Run AgentOS as its own OAuth authorization server for the MCP endpoint. Connecting requires the deployer secret on a consent page.",
    },
    "05_agent_os/os_config/basic.py": {
        "pre_run_steps": [
            (
                "Create the second database",
                "Create the `ai2` database used by the second PostgresDb instance:",
                'docker exec pgvector psql -U ai -d ai -c "CREATE DATABASE ai2;"',
            )
        ],
    },
    "05_agent_os/rbac/asymmetric/basic.py": {
        "env_remove": {"JWT_SIGNING_KEY", "JWT_VERIFICATION_KEY"},
        "pre_run_steps": [
            (
                "Configure optional JWT keys",
                "To supply your own RSA keys, set `JWT_SIGNING_KEY` and `JWT_VERIFICATION_KEY` to a valid PEM-format keypair. When they are unset, the example generates a pair and caches it at `/tmp/agno_rbac_demo_keys.json`.",
                None,
            )
        ],
    },
    "05_agent_os/rbac/asymmetric/custom_scope_mappings.py": {
        "env_remove": {"JWT_SIGNING_KEY", "JWT_VERIFICATION_KEY"},
        "pre_run_steps": [
            (
                "Configure optional JWT keys",
                "To supply your own RSA keys, set `JWT_SIGNING_KEY` and `JWT_VERIFICATION_KEY` to a valid PEM-format keypair. When they are unset, the example generates a pair and caches it at `/tmp/agno_rbac_demo_keys.json`.",
                None,
            )
        ],
    },
    "05_agent_os/rbac/symmetric/advanced_scopes.py": {
        "intro_override": "Issue HS256 tokens for five privilege tiers and use global, per-agent, and wildcard scopes to filter agents and gate runs.",
    },
    "05_agent_os/rbac/symmetric/custom_scope_mappings.py": {
        "pre_run_steps": [
            (
                "Configure the optional JWT secret",
                "Set `JWT_VERIFICATION_KEY` to override the hardcoded demonstration secret used to sign and verify tokens.",
                None,
            )
        ],
    },
    "05_agent_os/rbac/symmetric/user_isolation.py": {
        "intro_override": "Build on [Symmetric RBAC Basic](/examples/agent-os/rbac/symmetric/basic) by adding user-scoped database session isolation.",
        "pre_run_steps": [
            (
                "Configure the optional JWT secret",
                "Set `JWT_VERIFICATION_KEY` to override the hardcoded demonstration secret used to sign and verify tokens.",
                None,
            )
        ],
    },
    "05_agent_os/remote/05_agent_os_gateway.py": {
        "repo_layout": True,
        "extra_add": {"a2a", "os"},
        "package_add": {"chromadb", "ddgs", "google-adk", "openai"},
        "env_add": {"GOOGLE_API_KEY"},
        "pre_run_steps": [
            (
                "Start the remote AgentOS",
                "In a separate terminal, start the [remote AgentOS server](/examples/agent-os/remote/server) on port 7778:",
                "python cookbook/05_agent_os/remote/server.py",
            ),
            (
                "Start the Agno A2A server",
                "In a separate terminal, start the [Agno A2A server](/examples/agent-os/remote/agno-a2a-server) on port 7779:",
                "python cookbook/05_agent_os/remote/agno_a2a_server.py",
            ),
            (
                "Start the Google ADK A2A server",
                "In a separate terminal, start the [Google ADK A2A server](/examples/agent-os/remote/adk-server) on port 7780. This server uses `GOOGLE_API_KEY`.",
                "python cookbook/05_agent_os/remote/adk_server.py",
            ),
        ],
    },
    "05_agent_os/remote/04_remote_adk_agent.py": {
        "repo_layout": True,
        "package_add": {"a2a-sdk", "google-adk", "uvicorn"},
        "env_add": {"GOOGLE_API_KEY"},
        "pre_run_steps": [
            (
                "Start the Google ADK A2A server",
                "In another terminal, start the [Google ADK A2A server](/examples/agent-os/remote/adk-server) on port 7780:",
                "python cookbook/05_agent_os/remote/adk_server.py",
            )
        ],
    },
    "05_agent_os/remote/03_remote_agno_a2a_agent.py": {
        "repo_layout": True,
        "extra_add": {"a2a", "os"},
        "package_add": {"chromadb", "ddgs", "openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_code_warning": "The pinned source contains two stale `cookbook/06_agent_os` paths, including one printed at runtime. Use the `cookbook/05_agent_os` server path in the run steps below.",
        "pre_run_steps": [
            (
                "Start the Agno A2A server",
                "In another terminal, start the [Agno A2A server](/examples/agent-os/remote/agno-a2a-server) on port 7779:",
                "python cookbook/05_agent_os/remote/agno_a2a_server.py",
            )
        ],
    },
    "03_teams/12_learning/10_team_agentic_learning.py": {
        "pre_code_warning": "The pinned source imports `LearningMode` from a module that does not exist in Agno v2.7.4. Update the import before running.",
        "pre_run_steps": [
            (
                "Fix the LearningMode import",
                "Replace `from agno.learn.mode import LearningMode` with `from agno.learn import LearningMode` in the saved Python file.",
                None,
            )
        ],
    },
    "05_agent_os/scheduler/rest_api_schedules.py": {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"openai"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the scheduler server",
                "In another terminal, start [Scheduler with AgentOS](/examples/agent-os/scheduler/scheduler-with-agentos) on port 7777:",
                "python cookbook/05_agent_os/scheduler/scheduler_with_agentos.py",
            )
        ],
    },
    "05_agent_os/scheduler/schedule_management.py": {
        "repo_layout": True,
        "needs_agno": True,
        "needs_pgvector": True,
        "extra_add": {"os"},
        "package_add": {"openai", "psycopg[binary]"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the scheduler server",
                "In another terminal, start [Basic Schedule](/examples/agent-os/scheduler/basic-schedule) on port 7777:",
                "python cookbook/05_agent_os/scheduler/basic_schedule.py",
            )
        ],
    },
    "05_agent_os/skills/sample_skills/system-info/scripts/get_system_info.py": {
        "run_note": "The system-info skill executes this helper as a subprocess with no arguments. The pinned script prints JSON before its current main guard exits.",
    },
    "05_agent_os/tracing/dbs/basic_agent_with_clickhousedb.py": {
        "pre_run_steps": [
            (
                "Run ClickHouse",
                "Start ClickHouse on the ports and with the credentials used by the example:",
                "docker run -d --name clickhouse-server -e CLICKHOUSE_DB=ai -e CLICKHOUSE_USER=ai -e CLICKHOUSE_PASSWORD=ai -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 -p 8123:8123 -p 9000:9000 clickhouse/clickhouse-server",
            )
        ],
    },
    "05_agent_os/tracing/03_agent_with_knowledge_tracing.py": {
        "intro_override": "Trace an AgentOS knowledge agent. Its pinned media instruction branches require migration before use.",
        "pre_code_warning": "The pinned source tells the agent to call `text_to_speech` and `create_image`, but registers neither tool.",
        "pre_run_steps": [
            (
                "Remove the media instructions",
                "Delete the `Explain important concepts using audio` and `Explain concepts with images` branches from `instructions`. Remove `and optional audio explanations for complex concepts` from `description` before running.",
                None,
            )
        ],
    },
    "05_agent_os/workflow/workflow_with_custom_function_updating_session_state.py": {
        "needs_pgvector": False,
    },
    "05_agent_os/antigravity/data_enrichment.py": {
        "env_remove": {"RUN_DEMO"},
        "pre_run_steps": [
            (
                "Choose how to run the example",
                "Leave `RUN_DEMO` unset to serve AgentOS. Set `RUN_DEMO=1` to run the inline demonstration instead.",
                None,
            )
        ],
    },
    "05_agent_os/human_in_the_loop/workflow/dual_level_hitl.py": {
        "intro_override": "Collect a destination at the step boundary, then pause again for confirmation before the agent books the flight.",
    },
    "09_evals/accuracy/db_logging.py": {
        "pre_run_steps": [
            (
                "Start Postgres",
                "Start Postgres on the port used by this example:",
                "docker run -d --name postgres -e POSTGRES_USER=ai -e POSTGRES_PASSWORD=ai -e POSTGRES_DB=ai -p 5432:5432 postgres:17",
            )
        ],
    },
    "09_evals/performance/comparison/pydantic_ai_instantiation.py": {
        "env_add": {"OPENAI_API_KEY"},
    },
    "09_evals/performance/comparison/smolagents_instantiation.py": {
        "package_remove": {"memory-profiler"},
        "suppress_intro": True,
    },
    "09_evals/performance/instantiate_agent_with_tool.py": {
        "env_remove": {"OPENAI_API_KEY"},
    },
    "09_evals/performance/instantiate_agent.py": {
        "package_remove": {"openai"},
        "env_remove": {"OPENAI_API_KEY"},
    },
    "09_evals/reliability/db_logging.py": {
        "pre_run_steps": [
            (
                "Start Postgres",
                "Start Postgres on the port used by this example:",
                "docker run -d --name postgres -e POSTGRES_USER=ai -e POSTGRES_PASSWORD=ai -e POSTGRES_DB=ai -p 5432:5432 postgres:17",
            )
        ],
    },
    "09_evals/suite/suite_team_scoring.py": {
        "suppress_intro": True,
    },
    "05_agent_os/interfaces/a2a/basic_agent/client.py": {
        "repo_layout": True,
        "needs_agno": True,
        "package_add": {"openai", "uvicorn"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [
            (
                "Start the A2A server",
                "In another terminal, start the [Basic A2A Server](/examples/integrations/a2a/basic-agent/--main--) on port 9999:",
                "python cookbook/05_agent_os/interfaces/a2a/basic_agent/__main__.py",
            )
        ],
    },
    "11_memory/integrations/mem0_integration.py": {
        "env_add": {"MEM0_API_KEY"},
    },
    "observability/agent_ops.py": {
        "env_add": {"AGENTOPS_API_KEY"},
    },
    "observability/weave_op.py": {
        "env_add": {"WANDB_API_KEY"},
    },
    "integrations/parallel/05_web_plus_knowledge.py": {
        "intro_override": "Give one agent an Agno Knowledge base backed by local Chroma and Parallel Search for live web results. The agent selects the source for each question.",
    },
    # Postfix fresh-eyes fixes. These controls preserve pinned source fences
    # while correcting generated metadata and setup around them.
    "02_agents/03_context_management/instructions_with_state.py": {
        "intro_override": "Build run-specific agent instructions from `RunContext.session_state` with an instructions callable.",
    },
    "02_agents/08_guardrails/pii_detection.py": {
        "intro_override": "Use `PIIDetectionGuardrail` to reject requests containing PII or replace detected values with masked placeholders.",
        "pre_code_warning": "The pinned source catches `InputCheckError` around `print_response()`, but Agno v2.7.4 converts that guardrail exception into a run with `RunStatus.error`. The source therefore prints false success messages for blocked inputs. Use the status-checking pattern in the [PII Detection guide](/guardrails/usage/agent/pii-detection) instead.",
        "pre_run_steps": [
            (
                "Use run status checks",
                "Add `from agno.run import RunStatus`. Replace each `try`/`except InputCheckError` block with `response = agent.run(...)`, then treat `response.status == RunStatus.error` as blocked.",
                None,
            )
        ],
    },
    "02_agents/18_checkpointing/02_tool_error_persistence.py": {
        "intro_override": "Run two failure scenarios, then retry the failed agent run in place with `Agent.acontinue_run()`.",
    },
    "03_teams/23_checkpointing/02_tool_error_persistence.py": {
        "intro_override": "Run two failure scenarios, then retry the failed team run in place with `Team.acontinue_run()`.",
    },
    "03_teams/15_distributed_rag/03_distributed_rag_with_reranking.py": {
        "pre_code_warning": "This example passes `url=` to `insert_many()` and `ainsert_many()`. Agno v2.7.4 reads the `urls` argument, so these calls insert no documents. The code fence remains source-exact. Apply the replacement below before running.",
        "pre_run_steps": [
            (
                "Fix the batch insert arguments",
                "Replace all six `url=\"https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf\"` arguments in the saved file with `urls=[\"https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf\"]`.",
                None,
            )
        ],
    },
    "04_workflows/06_advanced_concepts/session_state/rename_session.py": {
        "intro_override": "Call `Workflow.set_session_name(autogenerate=True)` after a run to generate a session name.",
    },
    "08_learning/04_entity_memory/02_entity_relationships.py": {
        "intro_override": "Use entity memory in AGENTIC mode to create and query typed relationships between organizations, people, teams, and services.",
    },
    "10_reasoning/agents/analyse_treaty_of_versailles.py": {
        "pre_code_warning": "DeepSeek will retire the source's `deepseek-reasoner` alias after July 24, 2026 at 15:59 UTC. Replace it with `deepseek-v4-flash` before running. See the [DeepSeek V4 migration notice](https://api-docs.deepseek.com/news/news260424/).",
        "pre_run_steps": [
            (
                "Update the DeepSeek model",
                "Replace `DeepSeek(id=\"deepseek-reasoner\")` with `DeepSeek(id=\"deepseek-v4-flash\")` in the saved file.",
                None,
            )
        ],
    },
    "12_context/20_google_workspace.py": {
        "intro_override": "Combine Google Drive, Gmail, and Calendar context providers in one agent for cross-service workflows.",
        "pre_code_warning": "`GOOGLE_DELEGATED_USER` makes Google Drive, Gmail, and Calendar impersonate the same Workspace user. The source still gives Drive service-account search instructions, including `sharedWithMe` fallbacks. Confirm domain-wide delegation covers all three APIs and adapt the Drive instructions to the delegated user's files before running.",
        "env_add": {"GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_DELEGATED_USER"},
        "env_remove": {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID"},
    },
    "90_models/google/gemini/agent_with_thinking_budget.py": {
        "pre_code_warning": "Google has scheduled `gemini-2.5-pro` for shutdown on October 16, 2026 and recommends `gemini-3.1-pro-preview`. Gemini 3 models use `thinking_level` instead of a token `thinking_budget`. See [Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations) and [Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking).",
        "pre_run_steps": [
            (
                "Migrate the Gemini thinking configuration",
                "Replace `Gemini(id=\"gemini-2.5-pro\", thinking_budget=1280, include_thoughts=True)` with `Gemini(id=\"gemini-3.1-pro-preview\", thinking_level=\"low\", include_thoughts=True)` in the saved file.",
                None,
            )
        ],
    },
    "90_models/google/gemini/url_context.py": {
        "pre_code_warning": "This example's source docstring names the legacy `google-generativeai` package. Agno v2.7.4 uses the Google Gen AI SDK from `google-genai`. Use the generated install step below.",
    },
    "10_reasoning/models/gemini/basic_reasoning.py": {
        "intro_override": "Compare Gemini 2.5 Flash with thinking disabled against a fixed 1,024-token reasoning model, then inspect the captured reasoning content.",
        "pre_code_warning": "The source labels its first agent \"No Reasoning,\" but `gemini-2.5-flash` uses dynamic thinking when `thinking_budget` is unset. Set `thinking_budget=0` on that model to disable thinking for the comparison. See [Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking).",
        "pre_run_steps": [
            (
                "Disable thinking on the regular agent",
                "Replace `Gemini(id=\"gemini-2.5-flash\")` in `regular_agent` with `Gemini(id=\"gemini-2.5-flash\", thinking_budget=0)` in the saved file.",
                None,
            )
        ],
    },
    "90_models/google/gemini/imagen_tool_advanced.py": {
        "pre_code_warning": "Google discontinued the source's `imagen-4.0-generate-preview-05-20` endpoint. The source also uses the removed `Agent.run_response` attribute and passes raw image bytes to a base64 decoder. Apply all three edits below before running. See the [Vertex AI release notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes#February_17_2026).",
        "pre_run_steps": [
            (
                "Update the Imagen model",
                "Replace `imagen-4.0-generate-preview-05-20` with `imagen-4.0-generate-001` in the saved file.",
                None,
            ),
            (
                "Use the v2 run output accessor",
                "Replace `response = agent.run_response` with `response = agent.get_last_run_output()` in the saved file.",
                None,
            ),
            (
                "Encode the image bytes",
                "Add `import base64`, then replace `save_base64_data(str(response.images[0].content), \"tmp/baleen_whale.png\")` with `save_base64_data(base64.b64encode(response.images[0].content).decode(\"ascii\"), \"tmp/baleen_whale.png\")` in the saved file.",
                None,
            ),
        ],
    },
    "90_models/together/basic.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` serverless model. Select a current chat model from the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together deprecations](https://docs.together.ai/docs/deprecations).",
        "env_add": {"TOGETHER_CHAT_MODEL_ID"},
        "env_values": {"TOGETHER_CHAT_MODEL_ID": "your_current_together_chat_model_id_here"},
        "pre_run_steps": [
            (
                "Use the selected chat model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo\")` with `Together(id=os.environ[\"TOGETHER_CHAT_MODEL_ID\"])` in the saved file.",
                None,
            )
        ],
    },
    "90_models/together/structured_output.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` serverless model. Select a current chat model marked for structured outputs in the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together structured outputs](https://docs.together.ai/docs/inference/chat/structured-outputs).",
        "env_add": {"TOGETHER_STRUCTURED_MODEL_ID"},
        "env_values": {"TOGETHER_STRUCTURED_MODEL_ID": "your_current_together_structured_model_id_here"},
        "pre_run_steps": [
            (
                "Use a structured-output model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo\")` with `Together(id=os.environ[\"TOGETHER_STRUCTURED_MODEL_ID\"])` in the saved file.",
                None,
            )
        ],
    },
    "90_models/together/tool_use.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` serverless model. Select a current chat model marked for function calling in the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together function calling](https://docs.together.ai/docs/inference/function-calling/overview).",
        "env_add": {"TOGETHER_TOOL_MODEL_ID"},
        "env_values": {"TOGETHER_TOOL_MODEL_ID": "your_current_together_tool_model_id_here"},
        "pre_run_steps": [
            (
                "Use a function-calling model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo\")` with `Together(id=os.environ[\"TOGETHER_TOOL_MODEL_ID\"])` in the saved file.",
                None,
            )
        ],
    },
    "90_models/together/image_agent.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Llama-Vision-Free` serverless model. Select a current vision model from the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together vision inputs](https://docs.together.ai/docs/inference/vision/overview).",
        "env_add": {"TOGETHER_VISION_MODEL_ID"},
        "env_values": {"TOGETHER_VISION_MODEL_ID": "your_current_together_vision_model_id_here"},
        "pre_run_steps": [
            (
                "Use the selected vision model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Llama-Vision-Free\")` with `Together(id=os.environ[\"TOGETHER_VISION_MODEL_ID\"])` in the saved file.",
                None,
            )
        ],
    },
    "90_models/together/image_agent_bytes.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Llama-Vision-Free` serverless model. Select a current vision model from the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together vision inputs](https://docs.together.ai/docs/inference/vision/overview).",
        "env_add": {"TOGETHER_VISION_MODEL_ID"},
        "env_values": {"TOGETHER_VISION_MODEL_ID": "your_current_together_vision_model_id_here"},
        "pre_run_steps": [
            (
                "Use the selected vision model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Llama-Vision-Free\")` with `Together(id=os.environ[\"TOGETHER_VISION_MODEL_ID\"])` in the saved file.",
                None,
            ),
            (
                "Add the sample image",
                "Place a JPEG named `sample.jpg` in the same directory as `image_agent_bytes.py`.",
                None,
            ),
        ],
    },
    "90_models/together/image_agent_with_memory.py": {
        "pre_code_warning": "Together retired the source's `meta-llama/Llama-Vision-Free` serverless model. Select a current vision model from the [Together serverless catalog](https://docs.together.ai/docs/serverless/models) before running. See [Together vision inputs](https://docs.together.ai/docs/inference/vision/overview).",
        "env_add": {"TOGETHER_VISION_MODEL_ID"},
        "env_values": {"TOGETHER_VISION_MODEL_ID": "your_current_together_vision_model_id_here"},
        "pre_run_steps": [
            (
                "Use the selected vision model",
                "Add `import os`, then replace `Together(id=\"meta-llama/Llama-Vision-Free\")` with `Together(id=os.environ[\"TOGETHER_VISION_MODEL_ID\"])` in the saved file.",
                None,
            )
        ],
    },
    "90_models/together/reasoning_agent.py": {
        "pre_code_warning": "Together retired the source's `Qwen/Qwen3-235B-A22B-Thinking-2507` serverless model. Select a current model from the [Together reasoning model list](https://docs.together.ai/docs/inference/chat/reasoning) before running. See [Together deprecations](https://docs.together.ai/docs/deprecations).",
        "env_add": {"TOGETHER_REASONING_MODEL_ID"},
        "env_values": {"TOGETHER_REASONING_MODEL_ID": "your_current_together_reasoning_model_id_here"},
        "pre_run_steps": [
            (
                "Use the selected reasoning model",
                "Add `import os`, then replace `\"Qwen/Qwen3-235B-A22B-Thinking-2507\"` with `os.environ[\"TOGETHER_REASONING_MODEL_ID\"]` in the saved file.",
                None,
            )
        ],
    },
    "90_models/dashscope/image_agent.py": {
        "intro_override": "Analyze two image URLs with a tool-capable Qwen3-VL model and enrich both responses with web search.",
        "pre_code_warning": "The source combines `WebSearchTools` with `qwen-vl-plus`, while Alibaba documents function calling for the Qwen3-VL families. Its second Wikimedia thumbnail URL also returns HTTP 400. Apply both migrations before running. See [Alibaba's function-calling model list](https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling).",
        "pre_run_steps": [
            (
                "Use a tool-capable vision model",
                "Replace `DashScope(id=\"qwen-vl-plus\")` with `DashScope(id=\"qwen3-vl-plus\")` in the saved file.",
                None,
            ),
            (
                "Replace the unavailable image",
                "Replace `https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg` with `https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg` in the saved file.",
                None,
            ),
        ],
    },
    "91_tools/googlesheets_tools.py": {
        "intro_override": "Read a Google Sheet with `GoogleSheetsTools` after configuring service-account or OAuth credentials.",
        "pre_code_warning": "Fresh setups must enable the Google Sheets API and configure Google credentials. The source's OAuth redirect path is stale: `InstalledAppFlow.run_local_server(port=8080)` uses `http://localhost:8080/`, not `http://localhost:8080/flowName=GeneralOAuthFlow`. See the [Google Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python).",
        "pre_run_steps": [
            (
                "Configure Google Sheets authentication",
                "Enable the Google Sheets API. Then choose one credential flow: set `GOOGLE_SERVICE_ACCOUNT_FILE` to a service-account JSON key and share the target sheet with that account's email; or create an OAuth desktop client, save its JSON as `credentials.json` beside the script, and authorize in the browser. With `oauth_port=8080`, use `http://localhost:8080/` as the local redirect URI. If your OAuth client requires registered redirect URIs, register that exact URL.",
                None,
            )
        ],
    },
    "06_storage/mysql/async_mysql/async_mysql_for_workflow.py": {
        "pre_run_steps": [
            (
                "Wait for MySQL",
                "Wait until the container accepts connections before starting the workflow:",
                "docker exec mysql sh -c 'until mysqladmin ping -h 127.0.0.1 -uai -pai --silent; do sleep 1; done'",
            )
        ],
    },
    "90_models/google/gemini_interactions/tool_use.py": {
        "intro_override": "Give a `GeminiInteractions` agent `WebSearchTools`, then invoke it with synchronous, streaming, and asynchronous response calls.",
    },
    "90_models/meta/llama/async_knowledge.py": {
        "pre_code_warning": "The pinned source's install docstring lists unused `ddgs` and omits `openai` plus `psycopg[binary]`, which its default embedder and PostgreSQL URL require. Use the generated installation step below.",
    },
    "90_models/openai/chat/memory.py": {
        "pre_code_warning": "The pinned source docstring points to the nonexistent `cookbook/agents/personalized_memories_and_summaries.py` path. Save this fence as `memory.py` and use the generated run step below.",
    },
    "90_models/anthropic/prompt_caching_extended.py": {
        "pre_code_warning": "Anthropic retired the source's `claude-sonnet-4-20250514` model on June 15, 2026. Replace it with `claude-sonnet-4-6` before running. See [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations).",
        "pre_run_steps": [
            (
                "Update the Claude model",
                "Replace `Claude(id=\"claude-sonnet-4-20250514\")` with `Claude(id=\"claude-sonnet-4-6\")` in the saved file.",
                None,
            )
        ],
    },
    "90_models/azure/openai/knowledge.py": {
        "env_add": {"AZURE_OPENAI_DEPLOYMENT", "AZURE_EMBEDDER_DEPLOYMENT"},
        "pre_run_steps": [
            (
                "Configure Azure deployments",
                "Confirm that `AZURE_OPENAI_DEPLOYMENT` and `AZURE_EMBEDDER_DEPLOYMENT` refer to deployed `gpt-5.2` and `text-embedding-3-small` resources. Azure API calls use deployment names rather than model names. See [Azure OpenAI deployment setup](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource?view=foundry-classic#deploy-a-model).",
                None,
            )
        ],
    },
    "90_models/google/gemini_interactions/antigravity_environment_config.py": {
        "intro_override": "Reuse an existing Antigravity sandbox by ID, or create a new one from repository sources and documented network rules.",
        "pre_code_warning": "The pinned source uses an obsolete Antigravity `EnvironmentConfig`: repository sources no longer accept `type=\"git\"` and `url`, and `network.allow_internet_access` is not part of the current schema. Apply the migration below before running the custom-environment agent. See [Google's environment schema](https://ai.google.dev/gemini-api/docs/agent-environment).",
        "pre_run_steps": [
            (
                "Configure or skip environment reuse",
                "Before running, replace `env_xxxxxxxx` in `agent_reuse` with the ID of an existing environment. To run only the custom path, comment out the `agent_reuse.print_response(...)` block instead.",
                None,
            ),
            (
                "Update the environment configuration",
                "Replace the `environment` dictionary in `agent_custom` with `{'type': 'remote', 'sources': [{'type': 'repository', 'source': 'https://github.com/agno-agi/agno', 'target': '/workspace/agno'}]}`. Unrestricted outbound network access is the default.",
                None,
            )
        ],
    },
    "90_models/aimlapi/basic.py": {
        "pre_code_warning": "The pinned source uses `gpt-5.2`, but AIMLAPI's current GPT-5.2 model ID is `openai/gpt-5-2`. Apply the migration below before running. See [AIMLAPI's GPT-5.2 reference](https://docs.aimlapi.com/api-references/text-models-llm/openai/gpt-5.2).",
        "pre_run_steps": [
            (
                "Update the AIMLAPI model ID",
                "Replace `AIMLAPI(id=\"gpt-5.2\")` with `AIMLAPI(id=\"openai/gpt-5-2\")` in the saved file.",
                None,
            )
        ],
    },
    "91_tools/mcp/brave.py": {
        "pre_code_warning": "The pinned source uses the deprecated `@modelcontextprotocol/server-brave-search` package and `claude-sonnet-4-20250514`, which Anthropic retired on June 15, 2026. Apply both migrations below before running. See [Brave's maintained MCP server](https://github.com/brave/brave-search-mcp-server) and [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations).",
        "node_prepare_text": "The maintained Brave MCP server requires Node.js 22 or later. Install it, then confirm `node --version` reports v22 or later and `npx` is available:",
        "pre_run_steps": [
            (
                "Update the Brave MCP server",
                "Replace `npx -y @modelcontextprotocol/server-brave-search` with `npx -y @brave/brave-search-mcp-server --transport stdio` in the saved file.",
                None,
            ),
            (
                "Update the Claude model",
                "Replace `Claude(id=\"claude-sonnet-4-20250514\")` with `Claude(id=\"claude-sonnet-4-6\")` in the saved file.",
                None,
            )
        ],
    },
    "90_models/google/gemini/gemini_2_to_3.py": {
        "pre_code_warning": GEMINI_31_PRO_WARNING,
        "pre_run_steps": [GEMINI_31_PRO_MIGRATION_STEP],
    },
    "90_models/google/gemini/gemini_3_pro.py": {
        "pre_code_warning": GEMINI_31_PRO_WARNING,
        "pre_run_steps": [GEMINI_31_PRO_MIGRATION_STEP],
    },
    "90_models/google/gemini/gemini_3_pro_thinking_level.py": {
        "pre_code_warning": GEMINI_31_PRO_WARNING,
        "pre_run_steps": [GEMINI_31_PRO_MIGRATION_STEP],
    },
    "90_models/google/gemini/gcs_file_input.py": {
        "suppress_intro": True,
        "pre_code_warning": "For `gemini-3.5-flash` on Vertex AI, current limits are 50 MB for PDF input through the API or Cloud Storage, 7 MB for `text/plain`, and 30 MB for Cloud Storage image input. See [Gemini 3.5 Flash model limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash). The pinned source's blanket 2 GB limit and additional MIME-type claims are stale.",
    },
    "observability/langtrace_op.py": {
        "env_add": {"LANGTRACE_API_KEY"},
        "env_title": "Export your Langtrace and OpenAI API keys",
        "pre_code_warning": "The pinned source initializes Langtrace after importing Agno model modules, so automatic instrumentation may not attach. Create a Langtrace project and generate an API key before running the example. See [Langtrace Python SDK setup](https://github.com/Scale3-Labs/langtrace-python-sdk#quick-start).",
        "pre_run_steps": [
            (
                "Save and fix the initialization order",
                "Save the code above as `langtrace_op.py`, then move the `langtrace_python_sdk` import and `langtrace.init()` before every Agno and OpenAI import.",
                None,
            )
        ],
        "run_title": "Run the example",
        "run_replacement": "Run the corrected file:\n    ```bash\n    python langtrace_op.py\n    ```",
    },
    "03_teams/02_modes/tasks_stream.py": {
        "suppress_intro": True,
    },
    "06_storage/firestore/firestore_for_agent.py": {
        "pre_run_steps": [
            (
                "Configure Firestore",
                "Enable Firestore in your Google Cloud project and replace `PROJECT_ID` in `firestore_for_agent.py` with your own project ID before running.",
                None,
            )
        ],
    },
    "05_agent_os/background_tasks/evals_demo.py": {
        "intro_override": "This AgentOS app registers a Postgres-backed AccuracyEval for a calculator agent and exposes saved runs through the eval endpoints.",
    },
    "05_agent_os/factories/agent/02_input_schema_factory.py": {
        "intro_override": "The client sends a `factory_input` JSON object in the run request. AgentOS validates it against a Pydantic model and exposes the typed value as `ctx.input`.",
    },
    "05_agent_os/rbac/asymmetric/workos_byot.py": {
        "env_add": {"WORKOS_API_KEY", "WORKOS_CLIENT_ID"},
        "pre_run_steps": [
            (
                "Configure WorkOS",
                "In the WorkOS dashboard, enable RBAC and Email + Password authentication. Use `WORKOS_API_KEY` and `WORKOS_CLIENT_ID` from the same WorkOS environment.",
                None,
            )
        ],
    },
    "05_agent_os/rbac/symmetric/with_cookie.py": {
        "intro_override": "Read the JWT from an HTTP-only `auth_token` cookie with `TokenSource.COOKIE` instead of the Authorization header.",
        "pre_run_steps": [
            (
                "Configure the optional JWT secret",
                "Set `JWT_VERIFICATION_KEY` to override the hardcoded demonstration secret used to sign and verify tokens.",
                None,
            )
        ],
    },
    "07_knowledge/04_advanced/03_graph_rag.py": {
        "package_add": {"lightrag-hku[api]"},
        "pre_run_steps": [
            (
                "Start LightRAG",
                "Configure LightRAG's LLM and embedding settings in `.env`, then start the API server on port 9621. See the [LightRAG API server guide](https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md). Keep the server running:",
                "lightrag-server --port 9621",
            )
        ],
    },
    "12_context/00_filesystem.py": {
        "intro_override": "FilesystemContextProvider wraps a local directory and gives the agent a single `query_<id>` tool. A read-only sub-agent uses FileTools scoped to the root to list, search, and read files.",
    },
    "90_models/cerebras/knowledge.py": {
        "package_remove": {"beautifulsoup4"},
    },
    "90_models/cerebras/retry.py": {
        "suppress_intro": True,
    },
    "90_models/cometapi/multi_model.py": {
        "suppress_intro": True,
    },
    "90_models/cometapi/retry.py": {
        "suppress_intro": True,
    },
    "90_models/deepinfra/retry.py": {
        "suppress_intro": True,
    },
    "90_models/ibm/watsonx/image_agent_bytes.py": {
        "pre_run_steps": [
            (
                "Add a sample image",
                "Place a JPEG named `sample.jpg` in the same directory as `image_agent_bytes.py`.",
                None,
            )
        ],
    },
    "90_models/nebius/retry.py": {
        "suppress_intro": True,
    },
    "90_models/vllm/code_generation.py": {
        "intro_override": "Generate Python code with DeepSeek Coder served by vLLM.",
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM on a [supported platform](https://docs.vllm.ai/en/latest/getting_started/installation/) with a compatible accelerator:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "In a separate terminal with the virtual environment active, serve the model used by this example:",
                "vllm serve deepseek-ai/deepseek-coder-6.7b-instruct --dtype float32 --tool-call-parser pythonic",
            ),
        ],
    },
    "observability/logfire_via_openinference.py": {
        "pre_run_steps": [
            (
                "Choose the Logfire region",
                "Set `OTEL_EXPORTER_OTLP_ENDPOINT` in the code to the endpoint for your Logfire project's US or EU region. The source enables the EU endpoint by default.",
                None,
            )
        ],
    },
    "90_models/vllm/structured_output.py": {
        "pre_run_steps": [
            (
                "Install vLLM",
                "Install vLLM in the environment that will serve the model:",
                "uv pip install -U vllm",
            ),
            (
                "Start vLLM",
                "Serve the model used by this example:",
                "vllm serve Qwen/Qwen2.5-7B-Instruct",
            ),
        ],
    },
    "91_tools/docling_tools/basic_examples.py": {
        "package_add": {"openai-whisper"},
        "pre_run_steps": [
            (
                "Install FFmpeg",
                "Install the FFmpeg system package required for the MP4-to-VTT example and verify it is available:",
                "ffmpeg -version",
            )
        ],
        "run_after": "This entry point runs both the basic and OCR examples.",
        "run_command": "python cookbook/91_tools/docling_tools/run.py",
    },
    "91_tools/docling_tools/ocr_example.py": {
        "package_add": {"openai-whisper"},
        "pre_run_steps": [
            (
                "Install FFmpeg",
                "Install the FFmpeg system package required for the MP4-to-VTT example and verify it is available:",
                "ffmpeg -version",
            )
        ],
        "run_after": "This entry point runs both the basic and OCR examples.",
        "run_command": "python cookbook/91_tools/docling_tools/run.py",
    },
    "91_tools/docling_tools/run.py": {
        "package_add": {"openai-whisper"},
        "pre_run_steps": [
            (
                "Install FFmpeg",
                "Install the FFmpeg system package required for the MP4-to-VTT example and verify it is available:",
                "ffmpeg -version",
            )
        ],
    },
    "91_tools/firecrawl_tools.py": {
        "package_remove": {"firecrawl"},
    },
    "91_tools/fal_tools.py": {
        # FalTools checks FAL_API_KEY, while fal-client authenticates with FAL_KEY.
        "env_add": {"FAL_KEY"},
        "env_values": {
            "FAL_API_KEY": "your_fal_key_here",
            "FAL_KEY": "your_fal_key_here",
        },
    },
    "91_tools/mcp/cli.py": {
        "env_add": {"GITHUB_PERSONAL_ACCESS_TOKEN"},
        "needs_npx": False,
        "pre_code_warning": "The pinned source starts the retired npm GitHub MCP server. The fence remains byte-matched to v2.7.4. Replace that command in the saved file with [GitHub's maintained MCP server](https://github.com/github/github-mcp-server) before running it.",
        "pre_run_steps": [
            (
                "Use GitHub's maintained MCP server",
                "Install and start Docker. Then replace `npx -y @modelcontextprotocol/server-github` in the saved file with `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN -e GITHUB_READ_ONLY=1 ghcr.io/github/github-mcp-server`.",
                "docker --version",
            )
        ],
    },
    "91_tools/mcp/github.py": {
        "env_add": {"GITHUB_PERSONAL_ACCESS_TOKEN"},
        "env_remove": {"GITHUB_TOKEN"},
    },
    "91_tools/mcp/pipedream_auth.py": {
        "intro_override": "Call an authenticated Pipedream MCP server over streamable HTTP, passing a bearer token plus project and environment headers on behalf of an end user.",
    },
    "91_tools/mcp/sequential_thinking.py": {
        "intro_override": "Combine the sequential-thinking MCP server with YFinanceTools to reason step by step over stock data.",
    },
    "91_tools/redshift_tools.py": {
        "env_add": {"REDSHIFT_DATABASE", "REDSHIFT_HOST"},
    },
    "91_tools/scheduler_tools.py": {
        "intro_override": "Use a standalone agent to create and manage schedule records in PostgreSQL. This page covers record operations only.",
        "pre_code_warning": "This standalone example creates schedule records but does not run an AgentOS scheduler. Its `scheduler-demo` endpoint is absent from the linked AgentOS example, which serves `scheduler-agent`. Use [Scheduler Tools Agent](/examples/agent-os/scheduler/scheduler-tools-agent) as a separate end-to-end setup instead of mixing the two examples.",
    },
    "91_tools/models/gemini_video_generation.py": {
        "intro_override": "Use Veo 3.1 through GeminiTools on Vertex AI and decode the returned base64 content before saving the MP4.",
        "pre_code_warning": "Google discontinued the example's default `veo-2.0-generate-001` endpoint after June 30, 2026 and recommends `veo-3.1-generate-001`. The source also converts `video.content` to the string representation of a bytes object, which corrupts the saved MP4. Apply both corrections below. See [Vertex AI release notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes#March_24_2026).",
        "pre_run_steps": [
            (
                "Use Veo 3.1",
                "Replace `GeminiTools(vertexai=True)` with `GeminiTools(vertexai=True, video_generation_model=\"veo-3.1-generate-001\", enable_generate_image=False)` in the saved file.",
                None,
            ),
            (
                "Decode the returned content",
                "Replace `base64_data=str(video.content)` with `base64_data=video.content.decode(\"utf-8\")` so `save_base64_data()` receives the base64 string instead of a bytes representation.",
                None,
            ),
        ],
    },
    "04_workflows/06_advanced_concepts/history/continuous_execution.py": {
        "intro_override": "Give the tutoring step access to the three most recent workflow runs for a continuing conversation.",
        "pre_code_warning": "This example supplies the three most recent workflow runs, not the full conversation history claimed in the agent instructions. Set `num_history_runs` on `Step` to choose a larger bounded window; the step's default of 3 takes precedence over the workflow setting.",
    },
    "12_context/24_multi_context_streaming.py": {
        "pre_code_warning": "This example deletes and recreates `demo-arch-wiki` and `demo-ops-wiki` beside the saved file when the module is imported. Keep both directories disposable and do not import the module into another application. The docstring's `docs wiki` prompt is stale; the configured providers are Architecture Wiki and Operations Wiki.",
    },
    "91_tools/trafilatura_tools.py": {
        "intro_override": "Configure TrafilaturaTools for txt, markdown, JSON, and XML extraction, precision or recall tuning, metadata-only mode, crawling, and HTML-to-text conversion.",
    },
    "91_tools/docling_tools/paths.py": {
        "run_note": "This module defines shared paths for the Docling examples and is not run directly.",
    },
    # Randomized convergence sample 24. Preserve the v2.7.4 source fences and
    # put current migrations plus runnable prerequisites around them.
    "90_models/google/gemini/parallel_grounding.py": {
        "intro_override": "Ground Gemini 3.5 Flash responses with Parallel web search on Vertex AI after configuring a Marketplace subscription or Parallel API key.",
        "pre_code_warning": "Google retired the pinned `gemini-2.0-flash` model on Vertex AI. Replace it with a model that currently supports Parallel grounding, such as `gemini-3.5-flash`, before running. Parallel access also requires either a Google Cloud Marketplace subscription or `PARALLEL_API_KEY`. See [Grounding with Parallel](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/grounding/grounding-with-parallel).",
        "pre_run_steps": [
            (
                "Configure Parallel access",
                "Subscribe to Parallel through Google Cloud Marketplace, or create a Parallel API key and export it as `PARALLEL_API_KEY` in the shell that runs the example.",
                None,
            ),
            (
                "Use a supported Gemini model",
                "Replace `id=\"gemini-2.0-flash\"` with `id=\"gemini-3.5-flash\"` in the saved file.",
                None,
            ),
        ],
    },
    "90_models/deepinfra/basic.py": {
        "intro_override": "Run DeepSeek V3 through DeepInfra with synchronous, asynchronous, and streaming agent responses.",
        "pre_code_warning": "DeepInfra marks the pinned `meta-llama/Llama-2-70b-chat-hf` model as deprecated, and its model page is unavailable. Replace it with the current `deepseek-ai/DeepSeek-V3` model before running.",
        "pre_run_steps": [
            (
                "Use a current DeepInfra model",
                "Replace `meta-llama/Llama-2-70b-chat-hf` with `deepseek-ai/DeepSeek-V3` in the saved file.",
                None,
            )
        ],
    },
    "90_models/deepinfra/tool_use.py": {
        "intro_override": "Give a DeepSeek V3 agent on DeepInfra web search tools, then stream synchronous and asynchronous responses.",
        "pre_code_warning": "DeepInfra marks the pinned `meta-llama/Llama-2-70b-chat-hf` model as deprecated, and its model page is unavailable. Replace it with `deepseek-ai/DeepSeek-V3`, which supports tool calling, before running. See [DeepInfra tool calling](https://docs.deepinfra.com/chat/tool-calling).",
        "pre_run_steps": [
            (
                "Use a tool-capable DeepInfra model",
                "Replace `meta-llama/Llama-2-70b-chat-hf` with `deepseek-ai/DeepSeek-V3` in the saved file.",
                None,
            )
        ],
    },
    "05_agent_os/mcp_demo/mcp_tools_advanced_example.py": {
        "pre_code_warning": "The pinned source uses the deprecated `@modelcontextprotocol/server-brave-search` package in its active and commented MCP configurations. Replace both occurrences with Brave's maintained MCP server before running. See [Brave Search MCP Server](https://github.com/brave/brave-search-mcp-server).",
        "node_prepare_text": "The maintained Brave MCP server requires Node.js 22 or later. Install it, then confirm `node --version` reports v22 or later and `npx` is available:",
        "pre_run_steps": [
            (
                "Update both Brave MCP commands",
                "Replace both occurrences of `npx -y @modelcontextprotocol/server-brave-search` with `npx -y @brave/brave-search-mcp-server --transport stdio` in the saved file.",
                None,
            )
        ],
    },
    "10_reasoning/tools/azure_openai_reasoning_tools.py": {
        "pre_code_warning": "Microsoft schedules the pinned `gpt-4o-mini` model for retirement on October 1, 2026 and lists `gpt-4.1-mini` as its replacement. Azure OpenAI's `id` identifies your deployment, so deploy the replacement and use that deployment name before running. See the [Azure model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/concepts/model-retirement-schedule?view=foundry-classic).",
        "pre_run_steps": [
            (
                "Configure the Azure deployment",
                "Deploy `gpt-4.1-mini`. Name the deployment `gpt-4.1-mini`, or replace `AzureOpenAI(id=\"gpt-4o-mini\")` with `AzureOpenAI(id=\"<your-deployment-name>\")` in the saved file.",
                None,
            )
        ],
    },
    "91_tools/google/workspace/service_account.py": {
        "intro_override": "Authenticate Gmail, Calendar, Drive, and Sheets toolkits with a delegated Google Workspace service account.",
        "pre_code_warning": "The pinned setup omits required API enablement and Workspace scope authorization. Its run path is stale, and its environment guard checks only the service-account file even though Gmail requires `GOOGLE_DELEGATED_USER`. Complete the generated setup and use the generated run command below.",
        "pre_run_steps": [
            (
                "Create the delegated service account",
                "Enable the Gmail, Google Calendar, Google Drive, and Google Sheets APIs in the Google Cloud project. Create a service account, enable domain-wide delegation, and download its JSON key. See [Delegating domain-wide authority](https://developers.google.com/identity/protocols/oauth2/service-account#delegatingauthority).",
                None,
            ),
            (
                "Authorize the Workspace scopes",
                "As a Workspace super admin, add the service account's numeric client ID under Security > Access and data control > API Controls > Manage Domain Wide Delegation. Authorize `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.modify`, `https://www.googleapis.com/auth/gmail.compose`, `https://www.googleapis.com/auth/calendar.readonly`, `https://www.googleapis.com/auth/calendar`, `https://www.googleapis.com/auth/drive.readonly`, and `https://www.googleapis.com/auth/spreadsheets.readonly`.",
                None,
            ),
            (
                "Require the delegated user",
                "Replace `if not getenv(\"GOOGLE_SERVICE_ACCOUNT_FILE\"):` with `if not getenv(\"GOOGLE_SERVICE_ACCOUNT_FILE\") or not getenv(\"GOOGLE_DELEGATED_USER\"):` in the saved file.",
                None,
            ),
        ],
    },
    "05_agent_os/interfaces/slack/agent_with_user_memory.py": {
        "pre_code_warning": "Anthropic retired the pinned `claude-sonnet-4-20250514` model on June 15, 2026. Replace it with `claude-sonnet-4-6` before running. See [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations).",
        "pre_run_steps": [
            (
                "Update the Claude model",
                "Replace `Claude(id=\"claude-sonnet-4-20250514\")` with `Claude(id=\"claude-sonnet-4-6\")` in the saved file.",
                None,
            )
        ],
    },
    "90_models/fireworks/basic.py": {
        "intro_override": "Run Fireworks' current GPT OSS 120B model with synchronous, asynchronous, and streaming agent responses.",
        "pre_code_warning": "The pinned source uses a Llama 3.1 405B model that requires an on-demand deployment. Replace it with the serverless `accounts/fireworks/models/gpt-oss-120b` model before running. See [Fireworks GPT OSS 120B](https://fireworks.ai/models/fireworks/gpt-oss-120b).",
        "pre_run_steps": [
            (
                "Use the current Fireworks model",
                "Replace `accounts/fireworks/models/llama-v3p1-405b-instruct` with `accounts/fireworks/models/gpt-oss-120b` in the saved file.",
                None,
            )
        ],
    },
    "90_models/fireworks/structured_output.py": {
        "pre_code_warning": "The pinned source uses a Llama 3.1 405B model that requires an on-demand deployment. Replace it with the serverless `accounts/fireworks/models/gpt-oss-120b` model before running. See [Fireworks GPT OSS 120B](https://fireworks.ai/models/fireworks/gpt-oss-120b).",
        "pre_run_steps": [
            (
                "Use the current Fireworks model",
                "Replace `accounts/fireworks/models/llama-v3p1-405b-instruct` with `accounts/fireworks/models/gpt-oss-120b` in the saved file.",
                None,
            )
        ],
    },
    "90_models/fireworks/tool_use.py": {
        "pre_code_warning": "The pinned source uses a Llama 3.1 405B model that requires an on-demand deployment. Replace it with the serverless `accounts/fireworks/models/gpt-oss-120b` model before running. See [Fireworks GPT OSS 120B](https://fireworks.ai/models/fireworks/gpt-oss-120b).",
        "pre_run_steps": [
            (
                "Use the current Fireworks model",
                "Replace `accounts/fireworks/models/llama-v3p1-405b-instruct` with `accounts/fireworks/models/gpt-oss-120b` in the saved file.",
                None,
            )
        ],
    },
    "90_models/xai/reasoning_agent.py": {
        "intro_override": "Use ReasoningTools and YFinance with an explicit Grok 4.3 model to produce a TSLA report.",
        "pre_code_warning": "xAI now resolves the pinned `grok-3-beta` alias to `grok-4.3`, so its pricing and behavior follow Grok 4.3 rather than the original beta. Use the explicit current model ID before running. See [Grok 4.3](https://docs.x.ai/developers/models/grok-4.3).",
        "pre_run_steps": [
            (
                "Use the explicit Grok model",
                "Replace `xAI(id=\"grok-3-beta\")` with `xAI(id=\"grok-4.3\")` in the saved file.",
                None,
            )
        ],
    },
    "90_models/azure/ai_foundry/structured_output.py": {
        "intro_override": "Use Azure OpenAI for the supported Pydantic structured-output pattern. The v2.7.4 Azure AI Foundry source below fails before sending a request.",
        "pre_code_warning": "Agno v2.7.4's `AzureAIFoundry.get_request_params()` constructs `response_format` as a tuple, so both agents fail before sending a request. The adapter also depends on Microsoft's retired `azure-ai-inference` SDK. Do not run this source as written.",
        "replacement_only": True,
        "replacement_heading": "Current Alternative",
        "run_replacement": "Use [Azure OpenAI Structured Output](/models/providers/cloud/azure-openai/usage/structured-output) for a supported Pydantic output-schema example.",
    },
    "90_models/deepseek/thinking_mode.py": {
        "intro_override": "DeepSeek V4 returns `reasoning_content` with thinking mode enabled by default. Set `use_thinking=False` for a faster response.",
    },
    # Randomized convergence sample 29. Preserve the source fences while
    # correcting metadata, runtime semantics, and setup around them.
    "02_agents/09_hooks/pre_hook_input.py": {
        "intro_override": "A pre-hook checks relevance, detail, and safety before model execution. Blocked calls return a run output with `RunStatus.error`.",
        "pre_code_warning": "The source catches `InputCheckError` around blocked `Agent.run()` calls. Agno v2.7.4 converts the pre-hook exception into a run output with `RunStatus.error`, so those `except` blocks are bypassed. Check each blocked response's status instead.",
        "pre_run_steps": [
            (
                "Check blocked run statuses",
                "Add `from agno.run import RunStatus`. For tests 2 through 4, replace each complete `try`/`except InputCheckError` block with `response = agent.run(...)` followed by a branch that handles `response.status == RunStatus.error` as a blocked call.",
                None,
            )
        ],
    },
    "02_agents/12_multimodal/audio_to_text.py": {
        "intro_override": "Download an MP3, transcribe it with Gemini, and label each speaker in the streamed response.",
    },
    "02_agents/14_advanced/custom_logging.py": {
        "intro_override": "Configure the default `agno.utils.log` logger with a custom Python logger by calling `configure_agno_logging()`.",
        "pre_code_warning": "The source passes only `custom_default_logger`, which configures the default `agno.utils.log` logger. Agent, team, and workflow operations use separate loggers. Pass the custom logger to all four parameters to route those operation logs through it too.",
        "pre_run_steps": [
            (
                "Configure every Agno logger",
                "Replace `configure_agno_logging(custom_default_logger=custom_logger)` with `configure_agno_logging(custom_default_logger=custom_logger, custom_agent_logger=custom_logger, custom_team_logger=custom_logger, custom_workflow_logger=custom_logger)` in the saved file.",
                None,
            )
        ],
    },
    "12_context/10_custom_provider.py": {
        "pre_code_warning": "The source omits the keyword-only `run_context` parameter accepted by `ContextProvider.query()` and `ContextProvider.aquery()`. The generated `query_faq` tool calls `aquery(..., run_context=...)`, so it returns a serialized `TypeError` instead of the FAQ answer. Update both signatures before running.",
        "pre_run_steps": [
            (
                "Accept the run context",
                "Add `from agno.run import RunContext`. Change `query` to `def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:` and `aquery` to `async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:`. In `aquery`, return `self.query(question, run_context=run_context)`.",
                None,
            )
        ],
    },
    "90_models/langdb/agent.py": {
        "env_add": {"LANGDB_API_BASE_URL"},
        "env_values": {"LANGDB_API_BASE_URL": "https://api.langdb.ai"},
        "pre_code_warning": "Agno v2.7.4 defaults LangDB requests to the legacy regional host `https://api.us-east-1.langdb.ai`. Export `LANGDB_API_BASE_URL=https://api.langdb.ai` to use LangDB's current API host.",
    },
    "91_tools/tool_hooks/tool_hook_in_toolkit_with_state.py": {
        "intro_override": "Resolve a customer profile from `session_state`, rewrite the tool argument, and then invoke the toolkit function.",
    },
    "91_tools/websearch_tools_advanced.py": {
        "suppress_intro": True,
        "pre_code_warning": "`WebSearchTools` forwards `backend` and `timelimit` to separate DDGS text and news methods, whose supported values differ. The source leaves news enabled on its text-search toolkits, although some configured backends and `timelimit=\"y\"` are text-only. Its regional comparison also executes only the US agent. Apply the corrections below before running.",
        "pre_run_steps": [
            (
                "Keep text-search settings on the text tool",
                "Add `enable_news=False` to every `WebSearchTools(...)` configuration except the one used by `news_agent`. That keeps each configured text backend and time limit away from DDGS news search.",
                None,
            ),
            (
                "Run every regional comparison",
                "After the existing `us_regional.print_response(...)` call, add matching `uk_regional.print_response(...)` and `de_regional.print_response(...)` calls with the same prompt and `markdown=True`.",
                None,
            ),
        ],
    },
    # Randomized convergence sample 28. Preserve the v2.7.4 source fences and
    # put current migrations plus runnable prerequisites around them.
    "09_evals/performance/response_with_storage.py": {
        "description_override": "PerformanceEval invokes the benchmark function separately for runtime and memory measurement, producing four model requests total.",
        "intro_override": "`run_agent()` sends two model requests. `PerformanceEval` invokes it once for runtime and once for memory, so the evaluation sends four requests total.",
        "package_remove": {"memory-profiler"},
    },
    "05_agent_os/interfaces/agui/agent_with_tools.py": {
        "post_run_steps": [
            (
                "Run Dojo",
                "Follow the [AG-UI frontend setup](/agent-os/interfaces/ag-ui/introduction) to clone, build, and start Dojo. Configure its Agno endpoint for port `9001`, then use Dojo to execute the `generate_haiku` frontend tool.",
                None,
            )
        ],
    },
    "04_workflows/06_advanced_concepts/structured_io/input_schema.py": {
        "pre_code_warning": "The source uses deprecated `gpt-4o` for the content planner. Replace that model ID before running.",
        "pre_run_steps": [
            (
                "Update the content planner model",
                "Replace `OpenAIChat(id=\"gpt-4o\")` with `OpenAIChat(id=\"gpt-5.4-mini\")` in the saved file.",
                None,
            )
        ],
    },
    "91_tools/crawl4ai_tools.py": {
        "description_override": "Define three Crawl4aiTools configurations and execute the two pruning configurations.",
        "intro_override": "The source defines three Crawl4aiTools agents. It runs the default pruning agent and the explicit `enable_crawl` agent; the raw no-pruning agent is configured but not executed.",
        "pre_code_warning": "The source uses deprecated `gpt-4o` in all three agent configurations and defines `agent_raw` without executing it. Update the model IDs before running.",
        "pre_run_steps": [
            (
                "Set up Crawl4AI",
                "Install the browser dependencies required by Crawl4AI:",
                "crawl4ai-setup",
            ),
            (
                "Update the models",
                "Replace all three `OpenAIChat(id=\"gpt-4o\")` constructors with `OpenAIChat(id=\"gpt-5.4-mini\")` in the saved file.",
                None,
            ),
        ],
    },
}

for _client_example in (
    "01_basic_client.py",
    "03_memory_operations.py",
    "04_session_management.py",
    "05_knowledge_search.py",
    "08_run_evals.py",
    "10_sse_reconnect.py",
    "11_team_sse_reconnect.py",
    "13_workflow_sse_reconnect.py",
):
    SOURCE_RENDER_OVERRIDES[f"05_agent_os/client/{_client_example}"] = {
        "repo_layout": True,
        "needs_agno": True,
        "extra_add": {"os"},
        "package_add": {"chromadb", "ddgs", "openai"},
        "package_remove": {"fastapi"},
        "env_add": {"OPENAI_API_KEY"},
        "pre_run_steps": [CLIENT_SERVER_STEP],
    }

for _agui_helper in (
    "agentic_chat.py",
    "backend_tool_rendering.py",
    "human_in_the_loop.py",
    "shared_state.py",
    "tool_based_generative_ui.py",
):
    SOURCE_RENDER_OVERRIDES[f"05_agent_os/interfaces/agui/{_agui_helper}"] = {
        "repo_layout": True,
        "extra_add": {"agui", "os"},
        "package_add": {"ddgs", "google-genai", "requests"},
        "env_add": {"GOOGLE_API_KEY", "OPENAI_API_KEY"},
        "run_command": "python cookbook/05_agent_os/interfaces/agui/showcase.py",
    }
    if _agui_helper == "agentic_chat.py":
        SOURCE_RENDER_OVERRIDES[f"05_agent_os/interfaces/agui/{_agui_helper}"]["suppress_intro"] = True

SOURCE_RENDER_OVERRIDES["05_agent_os/interfaces/a2a/basic_agent/basic_agent.py"] = {
    "repo_layout": True,
    "package_add": {"uvicorn"},
    "run_command": "python cookbook/05_agent_os/interfaces/a2a/basic_agent/__main__.py",
}

SUPPRESS_INTRO_SLUGS = {
    "examples/agent-os/factories/workflow/tiered-workflow-factory",
    "examples/agent-os/knowledge/agentos-docling-markdown-analyst",
    "examples/agents/state-and-session/dynamic-session-state",
    "examples/evals/performance/simple-response",
    "examples/evals/reliability/team/ai-news",
    "examples/reasoning/tools/capture-reasoning-content-reasoning-tools",
    "examples/teams/basics/broadcast-mode",
    "examples/tools/tool-hooks/tool-hook",
    "examples/workflows/advanced-concepts/nested-workflows/deeply-nested-workflow",
    "examples/workflows/human-in-the-loop/dual-level-hitl/loop-confirmation-and-tool-confirmation",
    "examples/workflows/human-in-the-loop/dual-level-hitl/multi-step-mixed-hitl",
    "examples/workflows/human-in-the-loop/dual-level-hitl/output-review-and-tool-confirmation",
    "examples/workflows/human-in-the-loop/dual-level-hitl/router-confirmation-and-tool-confirmation",
}

# Keep dependency inference stable across Python versions. Agno still probes
# this removed stdlib module before falling back to `filetype`.
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"imghdr"}


# ---------------------------------------------------------------------------
# Docstring-derived fields
# ---------------------------------------------------------------------------

def smart_title(stem: str) -> str:
    """Turn a file stem like `01_callable_tools` into `Callable Tools`."""
    stem = re.sub(r"^\d+[a-z]?_", "", stem)
    words = [w for w in stem.split("_") if w]
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in ACRONYMS:
            out.append(ACRONYMS[lw])
        elif i > 0 and lw in SMALL_WORDS:
            out.append(lw)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def fix_title_casing(title: str) -> str:
    """Apply the acronym map to docstring-derived titles (Openai -> OpenAI)."""
    return re.sub(
        r"[A-Za-z0-9]+",
        lambda m: ACRONYMS.get(m.group(0).lower(), m.group(0)),
        title,
    )


def bad_docstring_title(candidate: str) -> bool:
    """Reject docstring first lines that read as commands, paths, or
    upstream machine-generated file-order prefixes."""
    if re.search(r"[`/]|\.py\b", candidate):
        return True
    if re.search(r"\bpip install\b|\buv run\b", candidate, re.IGNORECASE):
        return True
    return bool(re.match(r"\d|(?i:run|install)\b", candidate))


# A line that starts a list item ("- foo", "* foo", "1. foo", "1) foo", "1.").
LIST_LINE_RE = re.compile(r"^(?:[-*•]\s|\d+[.)]\s|\d+\.$)")


def body_paragraphs(docstring: str) -> list[str]:
    """Docstring prose paragraphs after the title line (and optional
    underline). List items and their continuation lines are dropped; they
    are never usable as description or intro."""
    lines = [ln.rstrip() for ln in docstring.strip().splitlines()]
    # Drop the title line and its underline, if the docstring has a title.
    body = lines[1:] if has_title_line(docstring) else lines
    while body and re.fullmatch(r"[=\-~]{3,}", body[0].strip()):
        body = body[1:]
    paras: list[list[str]] = [[]]
    is_list: list[bool] = [False]
    fenced = False
    for ln in body:
        stripped = ln.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            if paras[-1]:
                paras.append([])
                is_list.append(False)
            continue
        if fenced:
            continue  # fenced content is never prose
        if not stripped or re.fullmatch(r"[=\-~]{3,}", stripped):
            if paras[-1]:
                paras.append([])
                is_list.append(False)
            continue
        if LIST_LINE_RE.match(stripped):
            if paras[-1]:
                paras.append([])
                is_list.append(False)
            is_list[-1] = True
        paras[-1].append(stripped)
    # A line-wrapped word such as ``brand-\nnew`` must render as
    # ``brand-new``, not ``brand- new``. Keep the hyphen and remove only the
    # whitespace introduced by joining docstring lines.
    return [
        re.sub(r"(?<=\w)- (?=[a-z])", "-", " ".join(p))
        for p, lst in zip(paras, is_list)
        if p and not lst
    ]


def is_prose(paragraph: str) -> bool:
    """A paragraph usable as description/intro: text, not a command intro."""
    if "```" in paragraph or paragraph.startswith(("$", "#", ">>>", "-", "*")):
        return False
    if paragraph.endswith(":"):
        return False
    if re.search(r"\b(uv run|pip install|docker run|export [A-Z_]+=)", paragraph):
        return False
    if re.match(r"(?i)run\b", paragraph):
        return False  # setup instruction ("Run SurrealDB in a container ...")
    if re.match(r"[A-Za-z][\w-]*:\s", paragraph):
        return False  # label line ("Usage: ...", "Setup: ...", "Requires: ...")
    if paragraph.startswith("Cookbook example for"):
        return False  # upstream machine-generated placeholder docstring
    if re.match(r"(?i)demonstrates \d", paragraph):
        return False  # machine-generated filename echo ("Demonstrates 02 basic ...")
    if re.fullmatch(r"(?i)demonstrates this .{0,40}cookbook example\.?", paragraph):
        return False  # machine-generated stub
    return len(paragraph.split()) >= 3


def has_title_line(docstring: str) -> bool:
    """True when the docstring's first line reads as a standalone title."""
    lines = docstring.strip().splitlines()
    first = lines[0].strip()
    second = lines[1].strip() if len(lines) > 1 else ""
    if re.fullmatch(r"[=\-~]{3,}", second):
        return True
    # A short first line followed by a blank line (or nothing) is a title.
    return not second and bool(first) and len(first) <= 60 and len(first.split()) <= 8


# File stems too generic to stand alone as a page title.
GENERIC_STEMS = {"app", "demo", "main", "run", "seed", "test"}


def derive_title(docstring: str | None, stem: str, parent: str = "") -> str:
    if docstring and has_title_line(docstring):
        candidate = docstring.strip().splitlines()[0].strip().rstrip(".:").strip()
        candidate = re.sub(r"\s*[—–]\s*", ": ", candidate)  # em dashes are banned
        if candidate and not bad_docstring_title(candidate):
            return fix_title_casing(candidate)
    title = smart_title(stem)
    if parent and re.sub(r"^\d+[a-z]?_", "", stem).lower() in GENERIC_STEMS:
        parent_title = smart_title(re.sub(r"^\d+[a-z]?_", "", parent))
        title = f"{parent_title} {title}"
    return title


# "This example shows/demonstrates ..." openers are banned phrasing (docs
# style guide). Matched case-insensitively at the start of a sentence; the
# replacement is capitalized afterwards. Ordered most-specific first.
_OPENER_PATTERNS: tuple[tuple[str, str], ...] = (
    # "... shows how to use X" / "... how you can use X" -> imperative "Use X"
    (
        r"(?:learn how to"
        r"|this (?:example|recipe|cookbook) (?:shows|demonstrates) how (?:to|you can)"
        r"|(?:shows|demonstrates) how to)\s+",
        "",
    ),
    # "... demonstrates using X" -> "Use X"
    (r"this (?:example|recipe|cookbook) (?:shows|demonstrates) using\s+", "use "),
    # "... demonstrates how the team handles X" -> "The team handles X"
    (r"this (?:example|recipe|cookbook) (?:shows|demonstrates) how\s+", ""),
    # "... demonstrates <noun phrase>" -> "<Noun phrase>"
    (r"this (?:example|recipe|cookbook) (?:shows|demonstrates)\s+", ""),
)


def strip_example_opener(sentence: str) -> str:
    """Rewrite a 'This example shows/demonstrates ...' opener in docs voice."""
    for pattern, repl in _OPENER_PATTERNS:
        m = re.match(pattern, sentence, re.IGNORECASE)
        if m:
            sentence = repl + sentence[m.end():]
            sentence = sentence[:1].upper() + sentence[1:]
            break
    return sentence


def mdx_escape(text: str) -> str:
    """Escape MDX-hazard characters in docstring-derived prose.

    Docstring prose never contains real JSX, so every raw `<` (tag start),
    bare `&` (entity start), and `{`/`}` (acorn expression) outside inline
    code spans is escaped. Code-span contents are left alone; MDX already
    treats them literally.
    """
    out: list[str] = []
    for i, seg in enumerate(re.split(r"(`+[^`]*`+)", text)):
        if i % 2:  # inline code span
            out.append(seg)
            continue
        seg = re.sub(r"&(?![A-Za-z][A-Za-z0-9]*;|#\d+;|#[xX][0-9A-Fa-f]+;)", "&amp;", seg)
        seg = seg.replace("<", "&lt;")
        seg = seg.replace("{", "&#123;").replace("}", "&#125;")
        out.append(seg)
    return "".join(out)


def derive_description(docstring: str | None, title: str) -> str | None:
    """First prose sentence after the title. None means: needs a human."""
    if not docstring:
        return None
    for para in body_paragraphs(docstring):
        # Validate the first sentence, not the paragraph: a paragraph that
        # introduces a list ("Builds on basic.py ... With config X:") can
        # still open with a usable sentence.
        sentence = re.split(r"(?<=[.!?])\s+", para)[0].strip()
        if not is_prose(sentence):
            continue
        if re.search(r"\d+\.$", sentence):
            continue  # collapsed numbered-list artifact ("... tests that: 1.")
        if sentence.lower().rstrip(".") == f"demonstrates {title.lower()}":
            continue  # machine-generated filename echo
        # Em dashes are banned by the style guide; keep the clause before one.
        sentence = sentence.split("—")[0].rstrip(" ,;:")
        sentence = strip_example_opener(sentence)
        if len(sentence) < 15 or len(sentence.split()) < 3:
            continue  # truncation artifact; try the next paragraph
        if not sentence.endswith((".", "!", "?")):
            sentence += "."
        return sentence
    return None


def derive_intro(docstring: str | None, title: str) -> str | None:
    """Full first prose paragraph after the title, used as the page intro."""
    if not docstring:
        return None
    for para in body_paragraphs(docstring):
        if not is_prose(para) or "—" in para:
            continue
        if para.lower().rstrip(".") == f"demonstrates {title.lower()}":
            continue  # machine-generated filename echo
        # Same opener transform as descriptions, on the first sentence only.
        pieces = re.split(r"(?<=[.!?])\s+", para, maxsplit=1)
        pieces[0] = strip_example_opener(pieces[0])
        return " ".join(pieces)
    return None


# ---------------------------------------------------------------------------
# Imports -> dependencies and env keys
# ---------------------------------------------------------------------------

def imported_modules(src: str) -> dict[str, set[str]]:
    """Map of imported module -> names imported from it ({} for `import x`)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    mods: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.setdefault(alias.name, set())
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.setdefault(node.module, set()).update(a.name for a in node.names)
    return mods


def map_third_party(module: str, names: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """pip packages for a third-party import (dotted module + imported names)."""
    parts = module.split(".")
    top = parts[0]
    if top == "google":
        keys = []
        if len(parts) >= 2:
            keys.append(".".join(parts[1:3]))
            keys.append(parts[1])
        for name in sorted(names):
            keys.append(".".join((parts + [name])[1:3]))
        out: list[str] = []
        for key in keys:
            out.extend(GOOGLE_SUBPACKAGES.get(key, []))
        return sorted(set(out))
    mapped = THIRD_PARTY_PACKAGES.get(top, top.replace("_", "-"))
    return [mapped] if isinstance(mapped, str) else list(mapped)


def _module_packages(text: str) -> list[str]:
    """Third-party packages imported by a module's source. AST-based so lazy
    imports inside try blocks are caught without matching docstring prose
    (`from scratch.` is not an import)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    packages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            entries = [(alias.name, frozenset()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            entries = [(node.module, frozenset(a.name for a in node.names))]
        else:
            continue
        for module, names in entries:
            top = module.split(".")[0]
            if top in STDLIB or top in ("agno", "agno_infra"):
                continue
            packages.extend(map_third_party(module, names))
    return packages


def _probe_text(text: str) -> tuple[list[str], list[str]]:
    packages: list[str] = []
    for hit in re.findall(r"pip install ['\"`]?([A-Za-z0-9_.\[\]<>=,~ -]+?)['\"`\\)\n]", text):
        for pkg in hit.replace("-U", " ").split():
            if pkg and pkg != "agno":
                packages.extend(PIP_HINT_FIXES.get(pkg, [pkg]))
    packages.extend(_module_packages(text))
    # Probe executable reads only. Raw regex matching also captures optional
    # keys from docstring examples and alternative authentication modes.
    envs = required_env_keys_in_source(text)
    if "OpenAILike" in text and not packages:
        packages.append("openai")
    return packages, envs


def probe_agno_module(agno_pkg_root: Path, module: str, names: set[str]) -> tuple[list[str], list[str]]:
    """Extract pip-install hints and getenv() keys from an agno module's source.

    Modules that resolve to a package are probed via __init__.py plus any
    package file that defines one of the imported names.
    """
    rel = Path(*module.split(".")[1:])
    packages: list[str] = []
    envs: list[str] = []
    file_mod = agno_pkg_root / f"{rel}.py"
    pkg_dir = agno_pkg_root / rel
    targets: list[Path] = []
    if file_mod.is_file():
        targets.append(file_mod)
    elif pkg_dir.is_dir():
        init = pkg_dir / "__init__.py"
        if init.is_file():
            targets.append(init)
        if names:
            defines = [re.compile(rf"^(?:class|def) {re.escape(n)}\b|^{re.escape(n)}\s*[=:]", re.M) for n in sorted(names)]
            for sub in sorted(pkg_dir.glob("*.py")):
                if sub.name == "__init__.py":
                    continue
                text = sub.read_text(encoding="utf-8", errors="replace")
                if any(rx.search(text) for rx in defines):
                    targets.append(sub)
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        pkgs, env = _probe_text(text)
        packages.extend(pkgs)
        envs.extend(env)
    return packages, envs


def required_env_keys_in_source(src: str) -> list[str]:
    """Environment variables read without a non-None default by cookbook code."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            owner = node.value
            is_environ = (
                isinstance(owner, ast.Name) and owner.id == "environ"
            ) or (
                isinstance(owner, ast.Attribute)
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "os"
                and owner.attr == "environ"
            )
            if (
                is_environ
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                keys.add(node.slice.value)
            continue
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        is_getenv = isinstance(func, ast.Name) and func.id == "getenv"
        is_get = (
            isinstance(func, ast.Attribute)
            and func.attr in {"getenv", "get"}
            and (
                (isinstance(func.value, ast.Name) and func.value.id in {"os", "environ"})
                or (
                    isinstance(func.value, ast.Attribute)
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "os"
                    and func.value.attr == "environ"
                )
            )
        )
        if not (is_getenv or is_get):
            continue
        key = node.args[0]
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        if len(node.args) >= 2 and not (
            isinstance(node.args[1], ast.Constant) and node.args[1].value is None
        ):
            continue
        keys.add(key.value)
    return sorted(key for key in keys if re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", key))


def declared_env_keys(src: str) -> list[str]:
    """Environment variables declared as named prerequisites in a docstring."""
    try:
        docstring = ast.get_docstring(ast.parse(src), clean=False) or ""
    except SyntaxError:
        return []
    keys = set(re.findall(r"\bexport\s+([A-Z][A-Z0-9_]{3,})\s*:", docstring))
    in_prerequisites = False
    for line in docstring.splitlines():
        stripped = line.strip()
        if re.fullmatch(
            r"(?i)(?:requires|environment|environment variables|prerequisites)\s*:?",
            stripped,
        ):
            in_prerequisites = True
            continue
        if in_prerequisites and re.fullmatch(r"[A-Za-z][A-Za-z ]{2,}:?", stripped):
            in_prerequisites = False
        if in_prerequisites:
            # Only the leading declaration is an environment variable. Text
            # in a parenthetical annotation, such as "(UUID from the URL)",
            # is explanatory prose.
            match = re.match(
                r"^(?:[-*]\s+|\d+[.)]\s+)?`?([A-Z][A-Z0-9_]{3,})`?(?:\s|:|=|$)",
                stripped,
            )
            if match:
                keys.add(match.group(1))
    return sorted(keys)


def filter_env(keys: list[str]) -> list[str]:
    out = []
    for k in keys:
        if k in ENV_ALLOWLIST:
            out.append(k)
            continue
        if k in ENV_DENYLIST or ENV_DENYLIST_RE.search(k):
            continue
        if not re.search(r"(KEY|TOKEN|SECRET|PASSWORD|_ID)$", k):
            continue
        out.append(k)
    return sorted(set(out))


def model_provider_infos(
    module: str, names: set[str]
) -> list[tuple[str, list[str], list[str]]]:
    """Provider requirements for one agno.models import."""
    parts = module.split(".")
    if len(parts) < 3 or parts[1] != "models":
        return []
    segment = parts[2]
    class_map = MODEL_CLASS_PROVIDERS.get(segment, {})
    selected = sorted(names & class_map.keys())
    if not selected and len(parts) > 3:
        leaf = parts[3]
        if segment == "azure":
            selected = (
                ["AzureOpenAI"]
                if leaf == "openai_chat"
                else ["AzureAIFoundry"]
                if leaf == "ai_foundry"
                else ["Claude"]
                if leaf == "claude"
                else []
            )
        elif segment == "meta":
            selected = ["LlamaOpenAI"] if leaf == "llama_openai" else ["Llama"] if leaf == "llama" else []
    if selected:
        infos = []
        for name in selected:
            display, packages, envs = class_map[name]
            if segment == "meta" and len(parts) == 3 and name == "LlamaOpenAI":
                # agno.models.meta imports Llama before its guarded
                # LlamaOpenAI import, so the package-level import needs both.
                packages = packages + ["llama-api-client"]
            infos.append((display, packages, envs))
        return infos
    fallback = MODEL_PROVIDERS.get(segment)
    return [fallback] if fallback else []


def db_class_packages(module: str, names: set[str]) -> list[str] | None:
    """Resolve sync and async DB drivers from imported class names."""
    for family, class_map in DB_CLASS_PACKAGES.items():
        prefixes = (f"agno.db.{family}", f"agno.db.async_{family}")
        if not any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes):
            continue
        selected = sorted(names & class_map.keys())
        if not selected and (
            module == f"agno.db.async_{family}"
            or module.startswith(f"agno.db.async_{family}.")
            or f".async_{family}" in module
        ):
            selected = [next(name for name in class_map if name.startswith("Async"))]
        if not selected:
            return None
        packages = ["sqlalchemy"]
        for name in selected:
            packages.extend(class_map[name])
        return packages
    return None


def has_modelless_agent_or_team(src: str) -> bool:
    """True when an imported Agent or Team constructor uses its default model."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    constructors: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module == "agno.agent" or node.module.startswith("agno.agent."):
            wanted = "Agent"
        elif node.module == "agno.team" or node.module.startswith("agno.team."):
            wanted = "Team"
        else:
            continue
        for alias in node.names:
            if alias.name == wanted:
                constructors[alias.asname or alias.name] = wanted
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        kind = constructors.get(node.func.id)
        if not kind:
            continue
        model_kw = next((kw.value for kw in node.keywords if kw.arg == "model"), None)
        if model_kw is not None:
            if isinstance(model_kw, ast.Constant) and model_kw.value is None:
                return True
            continue
        if kind == "Agent" or len(node.args) < 3:
            return True
        if isinstance(node.args[2], ast.Constant) and node.args[2].value is None:
            return True
    return False


def has_pdf_string(src: str) -> bool:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False

    class RuntimeStringVisitor(ast.NodeVisitor):
        found = False

        def visit_Expr(self, node: ast.Expr) -> None:
            # Module/function docstrings and standalone illustrative strings
            # are not executable data flow.
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and ".pdf" in node.value.lower():
                self.found = True

    visitor = RuntimeStringVisitor()
    visitor.visit(tree)
    return visitor.found or any(
        isinstance(node, ast.Attribute)
        and node.attr == "PDF"
        and isinstance(node.value, ast.Name)
        and node.value.id == "SampleDataFileExtension"
        for node in ast.walk(tree)
    )


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def has_literal_true_keyword(src: str, call_name: str, keyword: str) -> bool:
    """Return whether a constructor explicitly enables an optional feature."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) != call_name:
            continue
        for item in node.keywords:
            if item.arg == keyword and isinstance(item.value, ast.Constant) and item.value.value is True:
                return True
    return False


def has_nonfalse_keyword(src: str, call_name: str, keyword: str) -> bool:
    """Return whether a constructor enables a keyword with a non-false value."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != call_name:
            continue
        for item in node.keywords:
            if item.arg != keyword:
                continue
            if isinstance(item.value, ast.Constant) and item.value.value in (False, None):
                continue
            return True
    return False


def call_uses_default_keyword(
    src: str, call_name: str, keyword: str, positional_index: int
) -> bool:
    """Return whether a call omits a keyword or explicitly passes None."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != call_name:
            continue
        value = next((item.value for item in node.keywords if item.arg == keyword), None)
        if value is not None:
            if isinstance(value, ast.Constant) and value.value is None:
                return True
            continue
        if len(node.args) <= positional_index:
            return True
        if isinstance(node.args[positional_index], ast.Constant) and node.args[positional_index].value is None:
            return True
    return False


def all_calls_supply_keywords(srcs: list[str], call_name: str, keywords: set[str]) -> bool:
    """Return whether every matching call explicitly supplies each keyword."""
    found = False
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != call_name:
                continue
            found = True
            supplied = {
                item.arg
                for item in node.keywords
                if item.arg is not None
                and not (isinstance(item.value, ast.Constant) and item.value.value is None)
            }
            if not keywords <= supplied:
                return False
    return found


def any_call_has_string_keyword(
    srcs: list[str], call_names: set[str], keywords: set[str]
) -> bool:
    """Return whether a matching constructor receives a string expression."""
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in call_names:
                continue
            for item in node.keywords:
                if (
                    item.arg in keywords
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)
                ):
                    return True
    return False


def any_call_uses_search_type(srcs: list[str], values: set[str]) -> bool:
    """Return whether Qdrant enables a named search mode.

    Also handle examples that pass a loop variable into Qdrant and enumerate
    the concrete SearchType values elsewhere in the same source.
    """
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        declared_modes = {
            node.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "SearchType"
        }
        has_dynamic_mode = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "Qdrant":
                continue
            for item in node.keywords:
                if item.arg not in {"search_type", "search_mode"}:
                    continue
                value = item.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    candidate = value.value.lower()
                elif isinstance(value, ast.Attribute):
                    candidate = value.attr.lower()
                else:
                    has_dynamic_mode = True
                    continue
                if candidate in values:
                    return True
        if has_dynamic_mode and declared_modes & values:
            return True
    return False


def all_lancedb_calls_are_local(srcs: list[str]) -> bool:
    """Return whether every LanceDb call has an explicit local filesystem URI."""
    found = False
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "LanceDb":
                continue
            found = True
            uri = next((item.value for item in node.keywords if item.arg == "uri"), None)
            if not isinstance(uri, ast.Constant) or not isinstance(uri.value, str):
                return False
            if re.match(r"(?i)(?:db|https?)://", uri.value):
                return False
    return found


def qdrant_uses_embedded_storage(srcs: list[str]) -> bool:
    """Return whether all Qdrant constructors use path or in-memory storage."""
    found = False
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            call_name = _call_name(node) if isinstance(node, ast.Call) else None
            if call_name not in {"Qdrant", "QdrantClient"}:
                continue
            found = True
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            if call_name == "Qdrant" and "client" in keywords:
                continue
            path = keywords.get("path")
            location = keywords.get("location")
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                continue
            if (
                isinstance(location, ast.Constant)
                and isinstance(location.value, str)
                and location.value == ":memory:"
            ):
                continue
            return False
    return found


def source_uses_string_model(srcs: list[str], provider: str) -> bool:
    """Return whether Agent or Team uses a literal provider:model shorthand."""
    prefix = provider + ":"
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in {"Agent", "Team"}:
                continue
            value = next((item.value for item in node.keywords if item.arg == "model"), None)
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.lower().startswith(prefix)
            ):
                return True
    return False


def has_true_keyword(srcs: list[str], call_name: str, keyword: str) -> bool:
    return any(has_literal_true_keyword(src, call_name, keyword) for src in srcs)


def has_any_call(srcs: list[str], call_names: set[str]) -> bool:
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if any(
            isinstance(node, ast.Call) and _call_name(node) in call_names
            for node in ast.walk(tree)
        ):
            return True
    return False


def any_call_has_string_keyword_value(
    srcs: list[str], call_name: str, keyword: str, value: str
) -> bool:
    """Return whether a constructor receives an exact string keyword value."""
    for src in srcs:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != call_name:
                continue
            if any(
                item.arg == keyword
                and isinstance(item.value, ast.Constant)
                and item.value.value == value
                for item in node.keywords
            ):
                return True
    return False


def ollama_model_ids(src: str) -> set[str]:
    """Literal model IDs used by Ollama constructors."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    model_ids: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in {"Ollama", "OllamaResponses"}:
            continue
        value = next((item.value for item in node.keywords if item.arg == "id"), None)
        if value is None and node.args:
            value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            model_ids.add(value.value)
    return model_ids


def uses_npx_command(src: str) -> bool:
    """Return whether executable code invokes an npx command."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False

    class NpxVisitor(ast.NodeVisitor):
        found = False

        def visit_Expr(self, node: ast.Expr) -> None:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and re.search(r"\bnpx\b", node.value, re.I):
                self.found = True

    visitor = NpxVisitor()
    visitor.visit(tree)
    return visitor.found


def uses_uvx_command(src: str) -> bool:
    """Return whether executable code invokes an uvx command."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False

    class UvxVisitor(ast.NodeVisitor):
        found = False

        def visit_Expr(self, node: ast.Expr) -> None:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and re.search(r"\buvx\b", node.value, re.I):
                self.found = True

    visitor = UvxVisitor()
    visitor.visit(tree)
    return visitor.found


def requirement_key(requirement: str) -> str:
    """Canonical distribution name for a pip requirement token."""
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    name = match.group(1) if match else requirement
    return re.sub(r"[-_.]+", "-", name).lower()


def shell_requirement(requirement: str) -> str:
    """Quote requirement extras so zsh does not expand bracket expressions."""
    return f'"{requirement}"' if "[" in requirement or "]" in requirement else requirement


def uses_repo_relative_layout(slug: str | None) -> bool:
    """True for reviewed examples that consume committed repository assets."""
    return slug in REPO_LAYOUT_SLUGS


class Requirements:
    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.extras: set[str] = set()
        self.env_keys: set[str] = set()
        self.providers: list[str] = []  # display names, for the step title
        self.needs_agno = False
        self.needs_pgvector = False
        self.needs_google_adc = False
        self.services: set[str] = set()  # keys into SERVICE_STEPS
        self.ollama_models: set[str] = set()
        self.needs_npx = False
        self.needs_uvx = False


def derive_requirements(
    srcs: list[str], agno_root: Path, skip_modules: frozenset[str] = frozenset()
) -> Requirements:
    """Requirements across the example file and any sibling cookbook modules
    it imports (`skip_modules`: sibling module names, never pip packages)."""
    req = Requirements()
    agno_pkg_root = agno_root / "libs" / "agno" / "agno"
    modules: dict[str, set[str]] = {}
    for src in srcs:
        for module, names in imported_modules(src).items():
            modules.setdefault(module, set()).update(names)
    req.needs_agno = any(module.split(".")[0] == "agno" for module in modules)
    for module, names in sorted(modules.items()):
        top = module.split(".")[0]
        for service, triggers in SERVICE_TRIGGERS.items():
            if any(module == t or module.startswith(t + ".") for t in triggers):
                req.services.add(service)
        if top == "agno":
            for prefix, envs in REQUIRED_ENV_OVERRIDES.items():
                if module == prefix or module.startswith(prefix + "."):
                    req.env_keys.update(envs)
            # agno extras (mcp, slack, os, ...)
            for prefix, extra in sorted(EXTRA_MODULES.items(), key=lambda kv: -len(kv[0])):
                if module == prefix or module.startswith(prefix + "."):
                    req.extras.add(extra)
                    break
            # model providers
            provider_infos = model_provider_infos(module, names)
            if provider_infos:
                for display, pkgs, envs in provider_infos:
                    req.packages.update(pkgs)
                    req.env_keys.update(envs)
                    if display not in req.providers:
                        req.providers.append(display)
                continue
            # curated overrides, longest prefix first
            db_packages = db_class_packages(module, names)
            matched = db_packages is not None
            if db_packages is not None:
                req.packages.update(db_packages)
            else:
                for prefix in sorted(PACKAGE_OVERRIDES, key=len, reverse=True):
                    if module == prefix or module.startswith(prefix + "."):
                        req.packages.update(PACKAGE_OVERRIDES[prefix])
                        matched = True
                        break
            # probe the agno source for pip hints and env keys
            pkgs, envs = probe_agno_module(agno_pkg_root, module, names)
            if module in {"agno.os", "agno.os.app"}:
                # AgentOS only imports fastmcp for optional MCP features. A
                # direct fastmcp import in the cookbook remains discoverable.
                pkgs = [package for package in pkgs if requirement_key(package) != "fastmcp"]
            if not matched:
                req.packages.update(pkgs)
            req.env_keys.update(k for k in filter_env(envs) if k not in PROBED_ENV_DENYLIST)
        elif top in STDLIB or top in ("agno_infra",) or top in skip_modules:
            continue
        else:
            req.packages.update(map_third_party(module, names))
    for src in srcs:
        req.env_keys.update(required_env_keys_in_source(src))
        req.env_keys.update(declared_env_keys(src))
        if uses_npx_command(src):
            req.needs_npx = True
        if uses_uvx_command(src):
            req.needs_uvx = True
    source_text = "\n".join(srcs)
    imports_postgres = any(
        module == "agno.db.postgres"
        or module.startswith("agno.db.postgres.")
        or module == "agno.db.async_postgres"
        or module.startswith("agno.db.async_postgres.")
        for module in modules
    )
    imports_pgvector = any(
        module == "agno.vectordb.pgvector" or module.startswith("agno.vectordb.pgvector.")
        for module in modules
    )
    uses_default_pgvector_url = imports_pgvector and any(
        call_uses_default_keyword(src, "PgVector", "db_url", positional_index=0)
        for src in srcs
    )
    req.needs_pgvector = (
        "localhost:5532" in source_text
        or "127.0.0.1:5532" in source_text
        or uses_default_pgvector_url
    )

    has_plain_postgres = bool(re.search(r"postgresql://", source_text))
    has_psycopg_postgres = bool(re.search(r"postgresql\+psycopg(?:_async)?://", source_text))
    if imports_postgres and has_plain_postgres:
        req.packages.add("psycopg2-binary")
        if not has_psycopg_postgres:
            req.packages = {
                package
                for package in req.packages
                if requirement_key(package) != "psycopg"
            }

    uses_explicit_gemini_vertex = any(
        has_nonfalse_keyword(src, call_name, "vertexai")
        for src in srcs
        for call_name in ("Gemini", "GeminiTools")
    )
    uses_env_gemini_vertex = (
        not uses_explicit_gemini_vertex and "GOOGLE_GENAI_USE_VERTEXAI" in source_text
    )
    uses_gemini_vertex = uses_explicit_gemini_vertex or uses_env_gemini_vertex
    uses_explicit_vertex_credentials = any(
        has_nonfalse_keyword(src, "Gemini", "credentials") for src in srcs
    )
    uses_vertex_claude = any(
        module == "agno.models.vertexai" or module.startswith("agno.models.vertexai.")
        for module in modules
    )
    uses_google_cloud_storage = any(
        module.startswith(("agno.db.firestore", "agno.db.gcs", "google.cloud"))
        for module in modules
    )
    if uses_gemini_vertex:
        req.env_keys.difference_update({"GOOGLE_API_KEY"})
        req.env_keys.update({"GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"})
        if any(has_nonfalse_keyword(src, "Gemini", "project_id") for src in srcs):
            req.env_keys.discard("GOOGLE_CLOUD_PROJECT")
        if any(has_nonfalse_keyword(src, "Gemini", "location") for src in srcs):
            req.env_keys.discard("GOOGLE_CLOUD_LOCATION")
        if uses_env_gemini_vertex:
            req.env_keys.add("GOOGLE_GENAI_USE_VERTEXAI")
    if (
        (uses_gemini_vertex and not uses_explicit_vertex_credentials)
        or uses_vertex_claude
        or uses_google_cloud_storage
    ):
        req.needs_google_adc = True
    imports_async_postgres = any(
        "AsyncPostgresDb" in names
        and (
            module == "agno.db.postgres"
            or module.startswith("agno.db.postgres.")
            or module == "agno.db.async_postgres"
            or module.startswith("agno.db.async_postgres.")
        )
        for module, names in modules.items()
    )
    if imports_async_postgres:
        found_driver = False
        if "postgresql+asyncpg" in source_text:
            req.packages.add("asyncpg")
            found_driver = True
        if "postgresql+psycopg" in source_text:
            req.packages.add("psycopg[binary]")
            found_driver = True
        if not found_driver:
            # Match the async-postgres extra when the source supplies its URL
            # or engine dynamically and no driver can be derived.
            req.packages.add("asyncpg")
    if any(
        has_nonfalse_keyword(src, "AgentOS", keyword)
        for src in srcs
        for keyword in ("mcp_server", "mcp_auth")
    ):
        req.extras.add("mcp")
    if any(has_nonfalse_keyword(src, "AgentOS", "a2a_interface") for src in srcs):
        req.extras.add("a2a")
    if any(has_nonfalse_keyword(src, "AgentOS", "agui_interface") for src in srcs):
        req.extras.add("agui")
    if any(
        module == "agno.context.web"
        and names & {"ExaMCPBackend", "ParallelMCPBackend"}
        for module, names in modules.items()
    ):
        req.extras.add("mcp")
    if any(
        "DynamoDb" in names
        and (module == "agno.db" or module.startswith("agno.db.dynamo"))
        for module, names in modules.items()
    ):
        req.packages.add("boto3")
        req.env_keys.update({"AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"})
    remote_content_names = set().union(
        *(
            names
            for module, names in modules.items()
            if module == "agno.knowledge.remote_content"
            or module.startswith("agno.knowledge.remote_content.")
        )
    )
    if "AzureBlobConfig" in remote_content_names:
        req.packages.add("azure-storage-blob")
        if any(
            has_nonfalse_keyword(src, "AzureBlobConfig", keyword)
            for src in srcs
            for keyword in ("tenant_id", "client_id", "client_secret")
        ):
            req.packages.add("azure-identity")
    if "GcsConfig" in remote_content_names:
        req.packages.add("google-cloud-storage")
    if source_uses_string_model(srcs, "xiaomi"):
        req.packages.add("openai")
        req.env_keys.add("MIMO_API_KEY")
        if "Xiaomi MiMo" not in req.providers:
            req.providers.append("Xiaomi MiMo")
    if any(has_modelless_agent_or_team(src) for src in srcs):
        req.packages.add("openai")
        req.env_keys.add("OPENAI_API_KEY")
        if "OpenAI" not in req.providers:
            req.providers.append("OpenAI")
    if (
        any(module == "agno.knowledge" or module.startswith("agno.knowledge.") for module in modules)
        and any(has_pdf_string(src) for src in srcs)
        and not any("DoclingReader" in names for names in modules.values())
    ):
        req.packages.add("pypdf")
    if (
        any(
            module == "agno.tools.llms_txt"
            or module.startswith("agno.tools.llms_txt.")
            or module == "agno.tools.website"
            or module.startswith("agno.tools.website.")
            for module in modules
        )
        or any_call_has_string_keyword(srcs, {"insert", "ainsert"}, {"url"})
    ):
        # These paths select WebsiteReader at runtime, where BeautifulSoup is
        # imported lazily and is invisible to direct import probing.
        req.packages.add("beautifulsoup4")
    if any_call_has_string_keyword(
        srcs,
        {"Condition", "Router", "Loop"},
        {"evaluator", "selector", "end_condition"},
    ):
        req.packages.add("cel-python")
    else:
        req.packages = {
            package for package in req.packages if requirement_key(package) != "cel-python"
        }
    if any_call_uses_search_type(srcs, {"keyword", "hybrid"}):
        req.packages.add("fastembed")
    elif not any(module.split(".")[0] == "fastembed" for module in modules):
        req.packages = {
            package for package in req.packages if requirement_key(package) != "fastembed"
        }
    if any(
        module == "agno.context.wiki" and "NotionDatabaseBackend" not in names
        for module, names in modules.items()
    ):
        req.packages = {
            package for package in req.packages if requirement_key(package) != "notion-client"
        }
        req.env_keys.discard("NOTION_API_KEY")
    if "GOOGLE_CLOUD_QUOTA_PROJECT_ID" not in source_text:
        # Google Drive accepts a quota project override, but does not require
        # it for OAuth or service-account authentication.
        req.env_keys.discard("GOOGLE_CLOUD_QUOTA_PROJECT_ID")
    if all_lancedb_calls_are_local(srcs):
        req.env_keys.discard("LANCEDB_API_KEY")
    if has_any_call(srcs, {"CohereEmbedder", "CohereReranker"}):
        req.env_keys.add("CO_API_KEY")
    if has_true_keyword(srcs, "Agent", "add_location_to_context") or has_true_keyword(
        srcs, "Team", "add_location_to_context"
    ):
        req.packages.add("requests")
    if has_true_keyword(srcs, "register", "auto_instrument"):
        req.packages.add("openinference-instrumentation-agno")
    if qdrant_uses_embedded_storage(srcs):
        req.services.discard("qdrant")
    if any(
        call_uses_default_keyword(src, "PgVector", "embedder", positional_index=7)
        for src in srcs
    ):
        req.packages.add("openai")
        req.env_keys.add("OPENAI_API_KEY")
        if "OpenAI" not in req.providers:
            req.providers.append("OpenAI")
    if any(
        call_uses_default_keyword(src, vector_db, "embedder", positional_index=4)
        for src in srcs
        for vector_db in ("Qdrant", "ChromaDb")
    ) or has_any_call(srcs, {"OpenAIEmbedder"}):
        req.packages.add("openai")
        req.env_keys.add("OPENAI_API_KEY")
        if "OpenAI" not in req.providers:
            req.providers.append("OpenAI")
    if any(module == "agno.vectordb.pineconedb" or module.startswith("agno.vectordb.pineconedb.") for module in modules) and any(
        has_literal_true_keyword(src, "PineconeDb", "use_hybrid_search") for src in srcs
    ):
        req.packages.add("pinecone-text")
    if all_calls_supply_keywords(srcs, "Slack", {"token", "signing_secret"}):
        req.env_keys.difference_update({"SLACK_TOKEN", "SLACK_SIGNING_SECRET"})
    if all_calls_supply_keywords(
        srcs,
        "Whatsapp",
        {"access_token", "phone_number_id", "verify_token"},
    ):
        req.env_keys.difference_update(
            {
                "WHATSAPP_ACCESS_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_VERIFY_TOKEN",
            }
        )
    if all_calls_supply_keywords(srcs, "TelegramTools", {"token", "chat_id"}):
        req.env_keys.difference_update({"TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"})
    if any(
        has_nonfalse_keyword(src, "AuthConfig", "service_account_path")
        for src in srcs
    ):
        req.env_keys.difference_update(
            {
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_PROJECT_ID",
                "GOOGLE_CLOUD_QUOTA_PROJECT_ID",
                "GOOGLE_TOKEN_ENCRYPTION_KEY",
            }
        )
        req.env_keys.add("GOOGLE_SERVICE_ACCOUNT_FILE")
    for src in srcs:
        for model_id in ollama_model_ids(src):
            if model_id.endswith("-cloud"):
                req.env_keys.add("OLLAMA_API_KEY")
            else:
                req.ollama_models.add(model_id)
    # A cookbook pip hint can contain agno extras. Merge those extras into the
    # single quoted agno token rendered below.
    for package in list(req.packages):
        match = re.match(r"^agno\[([^]]+)\]", package.replace("_", "-"), re.I)
        if not match:
            continue
        req.extras.update(item.strip() for item in match.group(1).split(",") if item.strip())
        req.packages.remove(package)
    # PEP 503: underscores and hyphens are interchangeable; normalize so the
    # same distribution never appears twice in one install line. Prefer a
    # versioned requirement over the bare name reported by an import.
    normalized: dict[str, str] = {}
    for package in sorted(p.replace("_", "-") for p in req.packages):
        match = re.match(r"^([A-Za-z0-9.-]+)", package)
        key = requirement_key(package)
        current = normalized.get(key)
        if current is None:
            normalized[key] = package
            continue
        current_name = re.match(r"^([A-Za-z0-9.-]+)", current)
        current_suffix = current[current_name.end() :] if current_name else ""
        candidate_suffix = package[match.end() :] if match else ""
        if candidate_suffix and not current_suffix:
            normalized[key] = package
    req.packages = set(normalized.values())
    if req.needs_agno:
        req.packages -= CORE_DEPS
    req.providers.sort()
    return req


def collect_siblings(source_path: Path, src: str) -> list[Path]:
    """Cookbook modules imported from the example's own directory (transitive).

    These are part of the example, not pip packages; the page must embed them
    so the run instructions work.
    """
    seen: dict[str, Path] = {}
    queue: list[tuple[Path, str]] = [(source_path, src)]
    while queue:
        path, text = queue.pop(0)
        for module in sorted(imported_modules(text)):
            top = module.split(".")[0]
            if top in seen or top == source_path.stem:
                continue
            sibling = source_path.parent / f"{top}.py"
            if not sibling.is_file():
                continue
            seen[top] = sibling
            queue.append((sibling, sibling.read_text(encoding="utf-8")))
    return [seen[k] for k in sorted(seen)]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def fence_for(code: str) -> str:
    """A backtick fence longer than any backtick run inside the code."""
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_env_step(
    env_keys: list[str],
    providers: list[str],
    value_overrides: dict[str, str] | None = None,
    title_override: str | None = None,
) -> str:
    value_overrides = value_overrides or {}
    unknown_keys = set(value_overrides).difference(env_keys)
    assert not unknown_keys, f"environment value overrides are not rendered: {sorted(unknown_keys)}"
    assert all(
        isinstance(value, str) and value and "\n" not in value
        for value in value_overrides.values()
    ), "environment value overrides must be non-empty, one-line strings"
    assert title_override is None or (
        isinstance(title_override, str)
        and title_override
        and "\n" not in title_override
        and '"' not in title_override
    ), "environment step title overrides must be non-empty, one-line strings"
    if title_override:
        title = title_override
    elif len(env_keys) == 1 and len(providers) == 1 and env_keys[0].endswith("_API_KEY"):
        provider = re.sub(r"\s+API$", "", providers[0])
        title = f"Export your {provider} API key"
    elif all(key.endswith("_API_KEY") for key in env_keys):
        title = "Export your API keys"
    else:
        title = "Export environment variables"
    values = {
        key: value_overrides.get(
            key,
            "true" if key == "GOOGLE_GENAI_USE_VERTEXAI" else f"your_{key.lower()}_here",
        )
        for key in env_keys
    }
    mac = "\n    ".join(f'export {key}="{values[key]}"' for key in env_keys)
    win = "\n    ".join(f'$Env:{key}="{values[key]}"' for key in env_keys)
    return f"""  <Step title="{title}">
    <CodeGroup>
    ```bash Mac/Linux
    {mac}
    ```

    ```bash Windows
    {win}
    ```
    </CodeGroup>
  </Step>"""


def apply_source_render_override(
    req: Requirements, cookbook_rel: str, srcs: list[str]
) -> dict[str, object]:
    """Apply reviewed source-specific metadata and return rendering controls."""
    rel = cookbook_rel.removeprefix("cookbook/")
    override = dict(SOURCE_RENDER_OVERRIDES.get(rel, {}))
    if rel.startswith("05_agent_os/interfaces/slack/"):
        pre_run_steps = list(override.get("pre_run_steps", []))
        if not any(step[0] == "Configure Slack" for step in pre_run_steps):
            pre_run_steps.append(SLACK_INTERFACE_STEP)
        override["pre_run_steps"] = pre_run_steps
    if has_any_call(srcs, {"DalleTools"}):
        override.setdefault(
            "intro_override",
            "The source-fidelity code uses `DalleTools`, whose supported DALL-E models are deprecated. Migrate the image path to GPT Image 2 before use.",
        )
        override["pre_code_warning"] = (
            "DALL-E models are deprecated. This source-fidelity example is preserved "
            "for reference and should not be run as written. Use "
            "[Image Generation Agent](/models/providers/native/openai/responses/usage/image-generation-agent) "
            "with GPT Image 2."
        )
        override["replacement_only"] = True
        override["replacement_heading"] = "Current Alternative"
        override["run_replacement"] = (
            "Follow [Image Generation Agent](/models/providers/native/openai/responses/usage/image-generation-agent) "
            "to generate images with GPT Image 2."
        )
    cerebras_retired_model_ids = sorted(
        model_id
        for model_id in CEREBRAS_RETIRED_MODEL_IDS
        if any(
            any_call_has_string_keyword_value(srcs, call_name, "id", model_id)
            for call_name in {"Cerebras", "CerebrasOpenAI"}
        )
    )
    if cerebras_retired_model_ids:
        override.setdefault("pre_code_warning", CEREBRAS_RETIRED_MODEL_WARNING)
        pre_run_steps = list(override.get("pre_run_steps", []))
        retired_ids = " or ".join(f"`{model_id}`" for model_id in cerebras_retired_model_ids)
        migration_step = (
            "Use a current Cerebras model",
            f"Replace {retired_ids} with `gpt-oss-120b` in the saved Python file before running.",
            None,
        )
        if migration_step not in pre_run_steps:
            pre_run_steps.append(migration_step)
        override["pre_run_steps"] = pre_run_steps
    groq_migrations = [
        (model_id, migration)
        for model_id, migration in GROQ_MODEL_MIGRATIONS.items()
        if any_call_has_string_keyword_value(srcs, "Groq", "id", model_id)
    ]
    if groq_migrations:
        groq_warning = " ".join(migration[0] for _, migration in groq_migrations)
        groq_warning += " See [Groq deprecations](https://console.groq.com/docs/deprecations)."
        existing_warning = override.get("pre_code_warning")
        if existing_warning:
            assert isinstance(existing_warning, str)
            groq_warning = f"{existing_warning} {groq_warning}"
        override["pre_code_warning"] = groq_warning
        pre_run_steps = list(override.get("pre_run_steps", []))
        for _, (_, step_title, step_text) in groq_migrations:
            step = (step_title, step_text, None)
            if step not in pre_run_steps:
                pre_run_steps.append(step)
        override["pre_run_steps"] = pre_run_steps
    if any_call_has_string_keyword_value(
        srcs, "AzureAIFoundry", "id", "Llama-3.2-11B-Vision-Instruct"
    ):
        override.setdefault("pre_code_warning", AZURE_FOUNDRY_RETIRED_VISION_WARNING)
        override.setdefault(
            "intro_override",
            "The source-fidelity code uses a retired Azure AI Foundry model. Replace it with Llama 4 Scout before running the example.",
        )
        pre_run_steps = list(override.get("pre_run_steps", []))
        if AZURE_FOUNDRY_VISION_MIGRATION_STEP not in pre_run_steps:
            pre_run_steps.append(AZURE_FOUNDRY_VISION_MIGRATION_STEP)
        override["pre_run_steps"] = pre_run_steps
    if any_call_has_string_keyword_value(
        srcs, "OpenAITools", "image_model", "gpt-image-1"
    ):
        pre_run_steps = list(override.get("pre_run_steps", []))
        step = (
            "Update the image model",
            "When saving the code, replace `gpt-image-1` with `gpt-image-2`.",
            None,
        )
        if step not in pre_run_steps:
            pre_run_steps.append(step)
        override["pre_run_steps"] = pre_run_steps
        override.setdefault(
            "intro_override",
            "The source-fidelity code uses `gpt-image-1`. Replace it with `gpt-image-2` before running the example.",
        )
    if any_call_has_string_keyword_value(
        srcs, "MistralChat", "id", "pixtral-12b-2409"
    ):
        pre_run_steps = list(override.get("pre_run_steps", []))
        step = (
            "Update the model",
            "When saving the code, replace `pixtral-12b-2409` with `ministral-14b-2512`.",
            None,
        )
        if step not in pre_run_steps:
            pre_run_steps.append(step)
        override["pre_run_steps"] = pre_run_steps
        override.setdefault(
            "intro_override",
            "The source-fidelity code uses deprecated `pixtral-12b-2409`. Replace it with `ministral-14b-2512` before running the example.",
        )
    if any_call_has_string_keyword_value(
        srcs, "xAI", "id", "grok-2-vision-latest"
    ):
        pre_run_steps = list(override.get("pre_run_steps", []))
        step = (
            "Update the model",
            "When saving the code, replace `grok-2-vision-latest` with `grok-4.5`.",
            None,
        )
        if step not in pre_run_steps:
            pre_run_steps.append(step)
        override["pre_run_steps"] = pre_run_steps
        override.setdefault(
            "intro_override",
            "The source-fidelity code uses the older `grok-2-vision-latest` model. Replace it with `grok-4.5` before running the example.",
        )
    source = srcs[0]
    invalid_model_retry_example = (
        rel.startswith("90_models/")
        and (rel.endswith("/retry.py") or rel.endswith("/with_retries.py"))
        and (
            "wrong_model_id" in source
            or re.search(r'id\s*=\s*["\'][^"\']*(?:wrong|invalid)[^"\']*["\']', source, re.I)
        )
    )
    if invalid_model_retry_example:
        override["description_override"] = INVALID_MODEL_RETRY_DESCRIPTION
        override["intro_override"] = INVALID_MODEL_RETRY_DESCRIPTION
        override["pre_code_warning"] = INVALID_MODEL_RETRY_WARNING
        override["replacement_only"] = True
        override["replacement_heading"] = "Current Alternative"
        override["run_replacement"] = INVALID_MODEL_RETRY_REPLACEMENT
    package_remove = {
        requirement_key(str(package)) for package in override.get("package_remove", set())
    }
    if package_remove:
        req.packages = {
            package
            for package in req.packages
            if requirement_key(package) not in package_remove
        }
    req.packages.update(override.get("package_add", set()))
    req.env_keys.update(override.get("env_add", set()))
    req.env_keys.difference_update(override.get("env_remove", set()))
    provider_remove = set(override.get("provider_remove", set()))
    if provider_remove:
        req.providers = [provider for provider in req.providers if provider not in provider_remove]
    req.extras.update(override.get("extra_add", set()))
    req.services.difference_update(override.get("service_remove", set()))
    req.ollama_models.difference_update(override.get("ollama_model_remove", set()))
    if "needs_agno" in override:
        req.needs_agno = bool(override["needs_agno"])
    if "needs_pgvector" in override:
        req.needs_pgvector = bool(override["needs_pgvector"])
    if "needs_npx" in override:
        req.needs_npx = bool(override["needs_npx"])
    for key in ("description_override", "intro_override", "pre_code_warning", "run_replacement"):
        value = override.get(key)
        if isinstance(value, str):
            override[key] = (
                value.replace("The pinned source's", "This example's")
                .replace("The pinned source", "This example")
                .replace("the pinned source's", "the example's")
                .replace("the pinned source", "the example")
            )
    return override


def source_link(cookbook_rel: str, render_override: dict[str, object], agno_root: Path) -> str:
    """Build a source link, optionally pinned to the exact Agno source tag."""
    ref = render_override.get("source_link_ref", "pinned-tag")
    assert isinstance(ref, str), f"{cookbook_rel}: source_link_ref must be a string"
    if ref == "pinned-tag":
        result = subprocess.run(
            ["git", "-C", str(agno_root), "describe", "--tags", "--exact-match", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{cookbook_rel}: source_link_ref requires the Agno source HEAD to have an exact tag"
        )
        ref = result.stdout.strip()
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref), (
        f"{cookbook_rel}: invalid source link ref {ref!r}"
    )
    return f"https://github.com/agno-agi/agno/blob/{ref}/{cookbook_rel}"


def missing_docstring_cookbook_paths(docstring: str, agno_root: Path) -> list[str]:
    """Return cookbook run paths named by the docstring that no longer exist."""
    paths = sorted(
        set(
            re.findall(
                r"\bpython\s+`?(cookbook/[A-Za-z0-9_./-]+\.py)`?",
                docstring,
            )
        )
    )
    return [path for path in paths if not (agno_root / path).is_file()]


def render(
    source_path: Path, cookbook_rel: str, src: str, agno_root: Path, slug: str | None = None
) -> str:
    try:
        docstring = ast.get_docstring(ast.parse(src))
    except SyntaxError:
        docstring = None

    stem = source_path.stem
    run_name = re.sub(r"^\d+[a-z]?_", "", stem) + ".py"
    if re.search(rf"app\s*=\s*['\"]{re.escape(stem)}:app['\"]", src):
        run_name = source_path.name
    title = derive_title(docstring, stem, source_path.parent.name)
    if slug and slug in TITLE_OVERRIDES:
        title = TITLE_OVERRIDES[slug]
    description = derive_description(docstring, title)
    intro = derive_intro(docstring, title)
    siblings = collect_siblings(source_path, src)
    sibling_srcs = [(p, p.read_text(encoding="utf-8")) for p in siblings]
    skip_modules = frozenset(p.stem for p in siblings)
    all_srcs = [src] + [s for _, s in sibling_srcs]
    req = derive_requirements(all_srcs, agno_root, skip_modules)
    render_override = apply_source_render_override(req, cookbook_rel, all_srcs)
    missing_run_paths = missing_docstring_cookbook_paths(docstring or "", agno_root)
    if missing_run_paths and not render_override.get("pre_code_warning"):
        formatted_paths = [f"`{path}`" for path in missing_run_paths]
        if len(formatted_paths) == 1:
            path_text = formatted_paths[0]
            warning = f"This example's source docstring names a removed cookbook path: {path_text}."
        else:
            path_text = ", ".join(formatted_paths[:-1]) + f", and {formatted_paths[-1]}"
            warning = f"This example's source docstring names removed cookbook paths: {path_text}."
        render_override["pre_code_warning"] = (
            f"{warning} Follow the generated Run step below."
        )
    full_source_url = source_link(cookbook_rel, render_override, agno_root)
    if "intro_override" in render_override:
        intro_override = render_override["intro_override"]
        assert isinstance(intro_override, str) and intro_override.strip(), (
            f"{cookbook_rel}: intro_override must be a non-empty string"
        )
        assert "\n" not in intro_override and "—" not in intro_override, (
            f"{cookbook_rel}: intro_override must be one docs-style line"
        )
        intro = intro_override
    elif render_override.get("suppress_intro"):
        intro = None
    needs_repo_layout = bool(
        render_override.get("repo_layout", uses_repo_relative_layout(slug))
    )

    override = DESC_OVERRIDES.get(slug) if slug else None
    if override is not None:
        description = override
        if slug in SUPPRESS_INTRO_SLUGS:
            intro = None
    elif description is None:
        print(
            f"WARNING: no usable docstring description in {cookbook_rel}; "
            "wrote a placeholder, edit it by hand.",
            file=sys.stderr,
        )
        description = f"Runnable cookbook example: {title}."
    description_override = render_override.get("description_override")
    if description_override is not None:
        assert isinstance(description_override, str) and description_override.strip(), (
            f"{cookbook_rel}: description_override must be a non-empty string"
        )
        assert "\n" not in description_override and "—" not in description_override, (
            f"{cookbook_rel}: description_override must be one docs-style line"
        )
        description = description_override

    if req.needs_agno and req.extras:
        # Brackets are shell glob characters (zsh errors on unquoted agno[mcp]);
        # quote only the bracketed spec. Packages the extra already installs
        # are dropped from the trailing list.
        agno_token = '"agno[' + ",".join(sorted(req.extras)) + ']"'
        provided = set().union(*(EXTRA_PROVIDES.get(e, set()) for e in req.extras))
    elif req.needs_agno:
        agno_token = "agno"
        provided = set()
    else:
        agno_token = None
        provided = set()
    install_tokens = ([agno_token] if agno_token else []) + sorted(
        shell_requirement(p)
        for p in req.packages
        if p != "agno" and requirement_key(p) not in provided
    )
    install = " ".join(install_tokens)

    code = src.strip("\n")
    fence = fence_for(code)

    parts: list[str] = []
    parts.append("---")
    parts.append(f"title: {yaml_str(title)}")
    parts.append(f"description: {yaml_str(description)}")
    parts.append(f"source: {cookbook_rel}")
    parts.append("---")
    parts.append("")
    if intro and intro.rstrip(".") != description.rstrip("."):
        parts.append(mdx_escape(intro))
        parts.append("")
    pre_code_warning = render_override.get("pre_code_warning")
    if pre_code_warning:
        assert isinstance(pre_code_warning, str), (
            f"{cookbook_rel}: pre_code_warning must be a string"
        )
        parts.append("<Warning>")
        parts.append(f"  {pre_code_warning}")
        parts.append("</Warning>")
        parts.append("")
    parts.append(f"{fence}python {run_name}")
    parts.append(code)
    parts.append(fence)
    parts.append("")
    if sibling_srcs:
        helper_label = "this helper module" if len(sibling_srcs) == 1 else "these helper modules"
        parts.append(f"The example imports {helper_label} from the same directory:")
        parts.append("")
        for sib_path, sib_src in sibling_srcs:
            sib_code = sib_src.strip("\n")
            sib_fence = fence_for(sib_code)
            parts.append(f"{sib_fence}python {sib_path.name}")
            parts.append(sib_code)
            parts.append(sib_fence)
            parts.append("")
    run_replacement = render_override.get("run_replacement")
    replacement_only = render_override.get("replacement_only", False)
    assert isinstance(replacement_only, bool), (
        f"{cookbook_rel}: replacement_only must be a boolean"
    )
    if replacement_only:
        assert isinstance(run_replacement, str) and run_replacement.strip(), (
            f"{cookbook_rel}: replacement_only requires run_replacement"
        )
        replacement_heading = render_override.get(
            "replacement_heading", "Current Alternative"
        )
        assert isinstance(replacement_heading, str) and replacement_heading.strip(), (
            f"{cookbook_rel}: replacement_heading must be a non-empty string"
        )
        parts.append(f"## {replacement_heading}")
        parts.append("")
        parts.append(run_replacement)
        parts.append("")
        parts.append(f"Full source: [{cookbook_rel}]({full_source_url})")
        parts.append("")
        return "\n".join(parts)

    parts.append("## Run the Example")
    parts.append("")
    run_warning = render_override.get("run_warning")
    if run_warning:
        assert isinstance(run_warning, str), f"{cookbook_rel}: run_warning must be a string"
        parts.append("<Warning>")
        parts.append(f"  {run_warning}")
        parts.append("</Warning>")
        parts.append("")
    parts.append("<Steps>")
    parts.append('  <Snippet file="create-venv-step.mdx" />')
    if install:
        parts.append("")
        parts.append('  <Step title="Install dependencies">')
        parts.append("    ```bash")
        parts.append(f"    uv pip install -U {install}")
        parts.append("    ```")
        parts.append("  </Step>")
    if req.needs_npx:
        node_prepare_text = render_override.get(
            "node_prepare_text",
            "The MCP server runs with `npx`. Install Node.js, then verify the commands:",
        )
        assert isinstance(node_prepare_text, str) and node_prepare_text.strip(), (
            f"{cookbook_rel}: node_prepare_text must be a non-empty string"
        )
        parts.append("")
        parts.append('  <Step title="Prepare Node.js">')
        parts.append(f"    {node_prepare_text}")
        parts.append("    ```bash")
        parts.append("    node --version")
        parts.append("    npx --version")
        parts.append("    ```")
        parts.append("  </Step>")
    if req.needs_uvx:
        parts.append("")
        parts.append('  <Step title="Prepare uvx">')
        parts.append("    Install uv, then verify `uvx` is available:")
        parts.append("    ```bash")
        parts.append("    uvx --version")
        parts.append("    ```")
        parts.append("  </Step>")
    env_keys = sorted(req.env_keys)
    if env_keys:
        env_values = render_override.get("env_values", {})
        assert isinstance(env_values, dict), f"{cookbook_rel}: env_values must be a dict"
        env_title = render_override.get("env_title")
        assert env_title is None or isinstance(env_title, str), (
            f"{cookbook_rel}: env_title must be a string"
        )
        parts.append("")
        parts.append(render_env_step(env_keys, req.providers, env_values, env_title))
    if req.needs_google_adc:
        parts.append("")
        parts.append('  <Step title="Authenticate with Google Cloud">')
        parts.append("    Sign in with Application Default Credentials:")
        parts.append("    ```bash")
        parts.append("    gcloud auth application-default login")
        parts.append("    ```")
        parts.append("  </Step>")
    if req.needs_pgvector:
        parts.append("")
        parts.append('  <Snippet file="run-pgvector-step.mdx" />')
    if req.ollama_models:
        parts.append("")
        parts.append('  <Step title="Prepare Ollama">')
        model_label = "model" if len(req.ollama_models) == 1 else "models"
        parts.append(f"    Install and start Ollama, then pull the {model_label} used by this example:")
        parts.append("    ```bash")
        for model_id in sorted(req.ollama_models):
            parts.append(f"    ollama pull {model_id}")
        parts.append("    ```")
        parts.append("  </Step>")
    for service in sorted(req.services):
        step_title, command = SERVICE_STEPS[service]
        parts.append("")
        parts.append(f'  <Step title="{step_title}">')
        parts.append("    ```bash")
        parts.append(f"    {command}")
        parts.append("    ```")
        parts.append("  </Step>")
    if needs_repo_layout:
        parts.append("")
        parts.append('  <Step title="Clone Agno">')
        parts.append("    Clone the repository and run the remaining commands from its root:")
        parts.append("    ```bash")
        parts.append("    git clone https://github.com/agno-agi/agno.git")
        parts.append("    cd agno")
        parts.append("    ```")
        parts.append("  </Step>")
    for step_title, step_text, command in render_override.get("pre_run_steps", []):
        parts.append("")
        parts.append(f'  <Step title="{step_title}">')
        if step_text:
            parts.append(f"    {step_text}")
        if command:
            parts.append("    ```bash")
            for command_line in str(command).splitlines():
                parts.append(f"    {command_line}")
            parts.append("    ```")
        parts.append("  </Step>")
    parts.append("")
    run_note = render_override.get("run_note")
    if run_replacement:
        assert isinstance(run_replacement, str), (
            f"{cookbook_rel}: run_replacement must be a string"
        )
        run_title = render_override.get("run_title", "Use the current example")
        parts.append(f'  <Step title="{run_title}">')
        parts.append(f"    {run_replacement}")
    elif run_note:
        parts.append('  <Step title="Use the helper">')
        parts.append(f"    {run_note}")
    else:
        run_title = render_override.get("run_title", "Run the example")
        parts.append(f'  <Step title="{run_title}">')
        if needs_repo_layout:
            parts.append("    Run the example from the repository root:")
        elif sibling_srcs:
            file_names = [f"`{n}`" for n in [run_name] + [p.name for p, _ in sibling_srcs]]
            joiner = " and " if len(file_names) == 2 else ", "
            parts.append(
                f"    Save the code blocks above as {joiner.join(file_names)} "
                "in the same directory, then run:"
            )
        else:
            parts.append(f"    Save the code above as `{run_name}`, then run:")
        parts.append("    ```bash")
        command = render_override.get("run_command")
        if command:
            for command_line in str(command).splitlines():
                parts.append(f"    {command_line}")
        elif needs_repo_layout:
            parts.append(f"    python {cookbook_rel}")
        else:
            parts.append(f"    python {run_name}")
        parts.append("    ```")
        run_after = render_override.get("run_after")
        if run_after:
            parts.append(f"    {run_after}")
    parts.append("  </Step>")
    for step_title, step_text, command in render_override.get("post_run_steps", []):
        parts.append("")
        parts.append(f'  <Step title="{step_title}">')
        if step_text:
            parts.append(f"    {step_text}")
        if command:
            parts.append("    ```bash")
            for command_line in str(command).splitlines():
                parts.append(f"    {command_line}")
            parts.append("    ```")
        parts.append("  </Step>")
    parts.append("</Steps>")
    parts.append("")
    parts.append(f"Full source: [{cookbook_rel}]({full_source_url})")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cookbook_relative(path: Path) -> str:
    parts = path.resolve().parts
    if "cookbook" not in parts:
        raise SystemExit(f"error: {path} is not under a cookbook/ directory")
    idx = len(parts) - 1 - parts[::-1].index("cookbook")
    return "/".join(parts[idx:])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="cookbook .py file")
    ap.add_argument("--slug", required=True, help="docs slug, e.g. examples/agents/tools/callable-tools")
    ap.add_argument("--docs-root", type=Path, default=REPO_ROOT, help="docs repo root (default: repo root above scripts/)")
    ap.add_argument("--agno-root", type=Path, default=None, help="agno repo root (default: AGNO_REPO env var, then <docs-root>/agno symlink)")
    ap.add_argument("--stdout", action="store_true", help="print the page instead of writing it")
    args = ap.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"error: {args.source} not found")
    agno_root = args.agno_root or Path(
        os.environ.get("AGNO_REPO") or args.docs_root / "agno"
    )
    src = args.source.read_text(encoding="utf-8")
    rel = cookbook_relative(args.source)
    page = render(args.source, rel, src, agno_root, slug=args.slug)

    if args.stdout:
        sys.stdout.write(page)
        return
    out = args.docs_root / f"{args.slug}.mdx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
