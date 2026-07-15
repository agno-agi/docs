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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Curated tables
# ---------------------------------------------------------------------------

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
        "docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root",
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
    "ibm": "IBM", "id": "ID", "io": "I/O", "json": "JSON", "jwt": "JWT",
    "lancedb": "LanceDB", "litellm": "LiteLLM", "llm": "LLM", "mcp": "MCP",
    "mongodb": "MongoDB", "mysql": "MySQL", "nvidia": "NVIDIA",
    "ocr": "OCR", "openai": "OpenAI", "openrouter": "OpenRouter",
    "os": "OS", "oss": "OSS", "pdf": "PDF", "pgvector": "PgVector",
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
    "examples/models/azure/ai-foundry/basic": "Azure AI Foundry Basic",
    "examples/models/azure/openai/basic": "Azure OpenAI Basic",
    "examples/models/anthropic/betas": "Betas",
    "examples/models/google/gemini/external-url-input": "External URL Input",
    "examples/models/groq/reasoning/demo-qwen-2-5-32b": "Demo Qwen 2.5 32B",
    "examples/models/vertexai/claude/betas": "Betas",
    "examples/storage/postgres/async-postgres/async-postgres-for-agent": "Async Postgres for Agent",
    "examples/models/openrouter/responses/basic": "Basic Usage",
    "examples/models/openrouter/responses/fallback": "Fallback Routing",
    "examples/models/openrouter/responses/stream": "Streaming",
    "examples/models/openrouter/responses/tool-use": "Tools",
    "examples/models/openrouter/chat/tool-use": "Tools",
    "examples/reasoning/models/groq/deepseek-plus-claude": "Qwen3 Plus Claude",
    "examples/tools/mcp/cli": "MCP CLI",
    "examples/tools/mcp/gibsonai": "GibsonAI MCP Server",
    "examples/tools/mcp/supabase": "Supabase MCP Agent",
    "examples/tools/mcp/local-server/server": "FastMCP Local Server",
    "examples/tools/mcp/notion-mcp-agent": "Notion MCP Agent",
    "examples/tools/models/gemini-image-generation": "Gemini Image Generation",
    "examples/tools/models/gemini-video-generation": "Gemini Video Generation",
    "examples/tools/other/human-in-the-loop": "Human in the Loop",
    "examples/tools/clickup-tools": "ClickUp Tools",
    "examples/tools/spotify-tools": "Spotify Tools",
    "examples/tools/exceptions/retry-tool-call-from-post-hook": "Post-Hook Retry",
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

SOURCE_RENDER_OVERRIDES: dict[str, dict[str, object]] = {
    "00_quickstart/agent_search_over_knowledge.py": {
        "package_add": {"beautifulsoup4"},
    },
    "00_quickstart/run.py": {
        # The documented prerequisite runs agent_search_over_knowledge.py,
        # whose URL insert selects WebsiteReader at runtime.
        "package_add": {"beautifulsoup4"},
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
    "90_models/lmstudio/basic.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/db.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/image_agent.py": {"pre_run_steps": [LMSTUDIO_VISION_STEP]},
    "90_models/lmstudio/knowledge.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/memory.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/retry.py": {"pre_run_steps": [LMSTUDIO_RETRY_STEP]},
    "90_models/lmstudio/structured_output.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/lmstudio/tool_use.py": {"pre_run_steps": [LMSTUDIO_STEP]},
    "90_models/llama_cpp/basic.py": {"pre_run_steps": [LLAMA_CPP_STEP]},
    "90_models/llama_cpp/structured_output.py": {"pre_run_steps": [LLAMA_CPP_STEP]},
    "90_models/llama_cpp/tool_use.py": {"pre_run_steps": [LLAMA_CPP_STEP]},
    "91_tools/moviepy_video_tools.py": {"pre_run_steps": [VIDEO_PATH_STEP]},
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
        "env_add": {"DAKERA_API_KEY"},
        "env_values": {"DAKERA_API_KEY": "demo"},
        "pre_run_steps": [
            (
                "Start Dakera",
                "Start the local memory server on port 3300:",
                "docker run -d -p 3300:3300 -e DAKERA_API_KEY=demo ghcr.io/dakera-ai/dakera:latest",
            )
        ],
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
        "intro_override": "Pass a local PDF to an OpenAI Chat agent as a file input.",
        "pre_run_steps": [
            (
                "Download the sample PDF",
                "Download `ThaiRecipes.pdf` next to the saved script:",
                "python -c \"from urllib.request import urlretrieve; urlretrieve('https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf', 'ThaiRecipes.pdf')\"",
            )
        ],
    },
    "90_models/openai/responses/image_generation_agent.py": {
        "intro_override": "The agent uses `OpenAITools` with `gpt-image-1` to generate an image.",
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
                'The pinned source does not pass `GOOGLE_MAPS_API_KEY` to the Google Maps MCP server, and `include_tools=["airbnb_search"]` filters out every Maps tool. Correct both settings before running the restaurant query.',
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
    "05_agent_os/interfaces/telegram/reasoning_agent.py": {
        "intro_override": "Run a Telegram bot with structured reasoning, DuckDuckGo web search, and SQLite session persistence.",
    },
    # Fresh-eyes batch F. These controls capture setup or framing that cannot
    # be inferred reliably from the primary source file alone.
    "05_agent_os/knowledge/agno_docs_agent.py": {
        "package_add": {"beautifulsoup4"},
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
        "pre_run_steps": [
            (
                "Start the Agno A2A server",
                "In another terminal, start the [Agno A2A server](/examples/agent-os/remote/agno-a2a-server) on port 7779:",
                "python cookbook/05_agent_os/remote/agno_a2a_server.py",
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
    "observability/langtrace_op.py": {
        "env_add": {"LANGTRACE_API_KEY"},
    },
    "observability/weave_op.py": {
        "env_add": {"WANDB_API_KEY"},
    },
    "integrations/parallel/05_web_plus_knowledge.py": {
        "intro_override": "Give one agent an Agno Knowledge base backed by local Chroma and Parallel Search for live web results. The agent selects the source for each question.",
    },
    # Postfix fresh-eyes fixes. These controls preserve pinned source fences
    # while correcting generated metadata and setup around them.
    "02_agents/18_checkpointing/02_tool_error_persistence.py": {
        "intro_override": "Run two failure scenarios to verify that tool exceptions and model errors preserve the conversation for `/continue` retries.",
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
        "package_add": {"lightrag-agno"},
        "pre_run_steps": [
            (
                "Start LightRAG",
                "Start a LightRAG server at `http://localhost:9621` before running the example.",
                None,
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
    "91_tools/mcp/cli.py": {
        "env_add": {"GITHUB_PERSONAL_ACCESS_TOKEN"},
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
    "91_tools/trafilatura_tools.py": {
        "intro_override": "Configure TrafilaturaTools for txt, markdown, JSON, and XML extraction, precision or recall tuning, metadata-only mode, crawling, and HTML-to-text conversion.",
    },
    "91_tools/docling_tools/paths.py": {
        "run_note": "This module defines shared paths for the Docling examples and is not run directly.",
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

GITHUB_BLOB = "https://github.com/agno-agi/agno/blob/main"

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


def apply_source_render_override(req: Requirements, cookbook_rel: str) -> dict[str, object]:
    """Apply reviewed source-specific metadata and return rendering controls."""
    rel = cookbook_rel.removeprefix("cookbook/")
    override = SOURCE_RENDER_OVERRIDES.get(rel, {})
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
    return override


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
    render_override = apply_source_render_override(req, cookbook_rel)
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
    parts.append("## Run the Example")
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
        parts.append("")
        parts.append('  <Step title="Prepare Node.js">')
        parts.append("    The MCP server runs with `npx`. Install Node.js, then verify the commands:")
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
    if run_note:
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
    parts.append("</Steps>")
    parts.append("")
    parts.append(f"Full source: [{cookbook_rel}]({GITHUB_BLOB}/{cookbook_rel})")
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
