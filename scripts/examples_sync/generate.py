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
    "aws": ("AWS Bedrock", ["boto3", "aioboto3"], ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]),
    "azure": (
        "Azure AI Foundry",
        ["azure-ai-inference", "aiohttp"],
        ["AZURE_API_KEY", "AZURE_ENDPOINT"],
    ),
    "cerebras": ("Cerebras", ["cerebras-cloud-sdk"], ["CEREBRAS_API_KEY"]),
    "cloudflare": ("Cloudflare Workers AI", ["openai"], ["CLOUDFLARE_API_TOKEN"]),
    "cohere": ("Cohere", ["cohere"], ["CO_API_KEY"]),
    "cometapi": ("CometAPI", ["openai"], ["COMETAPI_KEY"]),
    "dashscope": ("DashScope", ["openai"], ["DASHSCOPE_API_KEY"]),
    "deepinfra": ("DeepInfra", ["openai"], ["DEEPINFRA_API_KEY"]),
    "deepseek": ("DeepSeek", ["openai"], ["DEEPSEEK_API_KEY"]),
    "fireworks": ("Fireworks", ["openai"], ["FIREWORKS_API_KEY"]),
    "google": ("Google", ["google-genai"], ["GOOGLE_API_KEY"]),
    "groq": ("Groq", ["groq"], ["GROQ_API_KEY"]),
    "huggingface": ("Hugging Face", ["huggingface-hub"], ["HF_TOKEN"]),
    "ibm": ("IBM watsonx", ["ibm-watsonx-ai"], ["IBM_WATSONX_API_KEY"]),
    "inception": ("Inception", ["openai"], ["INCEPTION_API_KEY"]),
    "internlm": ("InternLM", ["openai"], ["INTERNLM_API_KEY"]),
    "langdb": ("LangDB", ["openai"], ["LANGDB_API_KEY"]),
    "litellm": ("LiteLLM", ["litellm"], ["LITELLM_API_KEY"]),
    "llama_cpp": ("llama.cpp", ["openai"], []),
    "lmstudio": ("LM Studio", ["lmstudio"], []),
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
    "portkey": ("Portkey", ["portkey-ai"], ["PORTKEY_API_KEY"]),
    "requesty": ("Requesty", ["openai"], ["REQUESTY_API_KEY"]),
    "sambanova": ("SambaNova", ["openai"], ["SAMBANOVA_API_KEY"]),
    "siliconflow": ("SiliconFlow", ["openai"], ["SILICONFLOW_API_KEY"]),
    "together": ("Together", ["openai"], ["TOGETHER_API_KEY"]),
    "vercel": ("Vercel v0", ["openai"], ["V0_API_KEY"]),
    "vertexai": ("Vertex AI", ["google-genai"], []),
    "vllm": ("vLLM", ["openai"], []),
    "xai": ("xAI", ["openai"], ["XAI_API_KEY"]),
    "xiaomi": ("Xiaomi MiMo", ["openai"], ["MIMO_API_KEY"]),
}

# Some provider packages export classes backed by different SDKs. Resolve
# these before falling back to the module-segment mapping above.
MODEL_CLASS_PROVIDERS = {
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
    "agno.tools.mcp": "mcp",
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
    "agno.db.postgres": ["sqlalchemy", "psycopg-binary"],
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
    "agno.vectordb.pineconedb": ["pinecone==5.4.2"],
    "agno.vectordb.pgvector": ["sqlalchemy", "psycopg-binary", "pgvector"],
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
        "PostgresDb": ["psycopg-binary"],
        "AsyncPostgresDb": [],
    },
    "sqlite": {"SqliteDb": [], "AsyncSqliteDb": ["aiosqlite"]},
}

# Third-party (non-agno) import name -> pip package(s). Stdlib is filtered
# out separately; anything not listed here installs under its import name
# (underscores hyphenated). Values verified against libs/agno/pyproject.toml.
THIRD_PARTY_PACKAGES: dict[str, str | list[str]] = {
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
# that explicitly reads this key still adds it through env_keys_in_source().
PROBED_ENV_DENYLIST = {"JWT_VERIFICATION_KEY", "WHATSAPP_ENCRYPTION_KEY"}

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
}

# Words kept lowercase in filename-derived titles (unless first).
SMALL_WORDS = {"a", "an", "and", "as", "at", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}

# Titles the docstring cannot yield in docs voice, keyed by docs slug.
# Consulted at render time, before description/intro derivation.
TITLE_OVERRIDES = {
    "examples/agent-os/rbac/symmetric/basic": "Symmetric RBAC Basic",
    "examples/agent-os/scheduler/team-workflow-schedules": "Scheduling Teams and Workflows",
    "examples/models/azure/ai-foundry/basic": "Azure AI Foundry Basic",
    "examples/models/azure/openai/basic": "Azure OpenAI Basic",
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
    return [" ".join(p) for p, lst in zip(paras, is_list) if p and not lst]


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
    envs = re.findall(r"getenv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]", text)
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


def env_keys_in_source(src: str) -> list[str]:
    hits = re.findall(
        r"(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]{3,})['\"]"
        r"|environ\[\s*['\"]([A-Z][A-Z0-9_]{3,})['\"]",
        src,
    )
    return [a or b for a, b in hits]


def declared_env_keys(src: str) -> list[str]:
    """Environment variables declared as named prerequisites in a docstring."""
    try:
        docstring = ast.get_docstring(ast.parse(src), clean=False) or ""
    except SyntaxError:
        return []
    return sorted(
        set(re.findall(r"\bexport\s+([A-Z][A-Z0-9_]{3,})\s*:", docstring))
    )


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
    return visitor.found


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


def requirement_key(requirement: str) -> str:
    """Canonical distribution name for a pip requirement token."""
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    name = match.group(1) if match else requirement
    return re.sub(r"[-_.]+", "-", name).lower()


def uses_repo_relative_layout(slug: str | None) -> bool:
    """True for reviewed examples that consume committed repository assets."""
    return slug in REPO_LAYOUT_SLUGS


class Requirements:
    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.extras: set[str] = set()
        self.env_keys: set[str] = set()
        self.providers: list[str] = []  # display names, for the step title
        self.needs_pgvector = False
        self.services: set[str] = set()  # keys into SERVICE_STEPS
        self.ollama_models: set[str] = set()
        self.needs_npx = False


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
            if module.startswith(
                ("agno.vectordb.pgvector", "agno.db.postgres", "agno.db.async_postgres")
            ):
                req.needs_pgvector = True
        elif top in STDLIB or top in ("agno_infra",) or top in skip_modules:
            continue
        else:
            req.packages.update(map_third_party(module, names))
    for src in srcs:
        req.env_keys.update(filter_env(env_keys_in_source(src)))
        req.env_keys.update(declared_env_keys(src))
        if uses_npx_command(src):
            req.needs_npx = True
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
        source_text = "\n".join(srcs)
        found_driver = False
        if "postgresql+asyncpg" in source_text:
            req.packages.add("asyncpg")
            found_driver = True
        if "postgresql+psycopg" in source_text:
            req.packages.add("psycopg-binary")
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
    if any(
        call_uses_default_keyword(src, "PgVector", "embedder", positional_index=7)
        for src in srcs
    ):
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
        req.env_keys.update({"GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_DELEGATED_USER"})
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


def render_env_step(env_keys: list[str], providers: list[str]) -> str:
    if len(env_keys) == 1 and len(providers) == 1 and env_keys[0].endswith("_API_KEY"):
        title = f"Export your {providers[0]} API key"
    elif all(key.endswith("_API_KEY") for key in env_keys):
        title = "Export your API keys"
    else:
        title = "Export environment variables"
    mac = "\n    ".join(f'export {k}="your_{k.lower()}_here"' for k in env_keys)
    win = "\n    ".join(f'$Env:{k}="your_{k.lower()}_here"' for k in env_keys)
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
    needs_repo_layout = uses_repo_relative_layout(slug)

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

    if req.extras:
        # Brackets are shell glob characters (zsh errors on unquoted agno[mcp]);
        # quote only the bracketed spec. Packages the extra already installs
        # are dropped from the trailing list.
        agno_token = '"agno[' + ",".join(sorted(req.extras)) + ']"'
        provided = set().union(*(EXTRA_PROVIDES.get(e, set()) for e in req.extras))
    else:
        agno_token = "agno"
        provided = set()
    install = " ".join(
        [agno_token]
        + sorted(
            p
            for p in req.packages
            if p != "agno" and requirement_key(p) not in provided
        )
    )

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
    env_keys = sorted(req.env_keys)
    if env_keys:
        parts.append("")
        parts.append(render_env_step(env_keys, req.providers))
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
    parts.append("")
    parts.append('  <Step title="Run the example">')
    if needs_repo_layout:
        parts.append("    Clone Agno and run the example from the repository root:")
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
    if needs_repo_layout:
        parts.append("    git clone https://github.com/agno-agi/agno.git")
        parts.append("    cd agno")
        parts.append(f"    python {cookbook_rel}")
    else:
        parts.append(f"    python {run_name}")
    parts.append("    ```")
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
