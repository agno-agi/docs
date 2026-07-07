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
    "azure": ("Azure", ["azure-ai-inference", "aiohttp"], ["AZURE_API_KEY"]),
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

# agno module prefix -> agno pip extra (installed as agno[extra]).
# Matches how the rest of the docs install these features.
EXTRA_MODULES = {
    "agno.os.interfaces.a2a": "a2a",
    "agno.os.interfaces.agui": "agui",
    "agno.os.interfaces.slack": "slack",
    "agno.os.interfaces.whatsapp": "whatsapp",
    "agno.os": "os",
    "agno.tools.mcp": "mcp",
    "agno.tracing": "os",  # tracing ships with the AgentOS/opentelemetry bundle
}

# Packages each agno extra installs (libs/agno/pyproject.toml on feat/v2.7,
# nested agno[...] references resolved, names PEP 503-normalized). Used to
# drop packages from the install line that the extra already provides.
EXTRA_PROVIDES: dict[str, set[str]] = {
    "a2a": {"a2a-sdk"},
    "agui": {"ag-ui-protocol", "jsonpatch"},
    "mcp": {"mcp", "fastmcp"},
    "os": {
        "fastapi", "python-multipart", "uvicorn", "websockets", "sqlalchemy",
        "pyjwt", "opentelemetry-sdk", "openinference-instrumentation-agno",
        # via agno[scheduler]
        "croniter", "pytz",
    },
    "slack": {"slack-sdk", "aiohttp"},
    "whatsapp": set(),  # no whatsapp extra in pyproject; nothing extra installed
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
    "agno.vectordb.pgvector": ["sqlalchemy", "psycopg-binary", "pgvector"],
    "agno.knowledge.embedder.openai": ["openai"],
    "agno.knowledge.embedder.google": ["google-genai"],
    "agno.tools.duckduckgo": ["ddgs"],
    "agno.eval.performance": ["memory_profiler"],
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

# Local services an example depends on -> docker step. Triggered by module
# prefix (agno modules) or import name (third-party clients). PgVector is
# handled separately via the run-pgvector-step.mdx snippet.
SERVICE_TRIGGERS = {
    "mongodb": ("agno.db.mongo", "agno.vectordb.mongodb", "pymongo", "motor"),
    "qdrant": ("agno.vectordb.qdrant", "qdrant_client"),
    "redis": ("agno.db.redis", "agno.vectordb.redis", "redis"),
    "surrealdb": ("agno.db.surrealdb", "agno.vectordb.surrealdb", "surrealdb"),
}
SERVICE_STEPS = {
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
    "examples/agent-os/scheduler/team-workflow-schedules": "Scheduling Teams and Workflows",
}

GITHUB_BLOB = "https://github.com/agno-agi/agno/blob/main"

STDLIB = set(getattr(sys, "stdlib_module_names", ()))


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


class Requirements:
    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.extras: set[str] = set()
        self.env_keys: set[str] = set()
        self.providers: list[str] = []  # display names, for the step title
        self.needs_pgvector = False
        self.services: set[str] = set()  # keys into SERVICE_STEPS


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
            parts = module.split(".")
            # agno extras (mcp, slack, os, ...)
            for prefix, extra in sorted(EXTRA_MODULES.items(), key=lambda kv: -len(kv[0])):
                if module == prefix or module.startswith(prefix + "."):
                    req.extras.add(extra)
                    break
            # model providers
            if len(parts) >= 3 and parts[1] == "models":
                info = MODEL_PROVIDERS.get(parts[2])
                if info:
                    display, pkgs, envs = info
                    req.packages.update(pkgs)
                    req.env_keys.update(envs)
                    if display not in req.providers:
                        req.providers.append(display)
                    continue
            # curated overrides, longest prefix first
            matched = False
            for prefix in sorted(PACKAGE_OVERRIDES, key=len, reverse=True):
                if module == prefix or module.startswith(prefix + "."):
                    req.packages.update(PACKAGE_OVERRIDES[prefix])
                    matched = True
                    break
            # probe the agno source for pip hints and env keys
            pkgs, envs = probe_agno_module(agno_pkg_root, module, names)
            if not matched:
                req.packages.update(pkgs)
            req.env_keys.update(filter_env(envs))
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
    # PEP 503: underscores and hyphens are interchangeable; normalize so the
    # same package never appears twice in one install line.
    req.packages = {p.replace("_", "-") for p in req.packages}
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


def pep503(name: str) -> str:
    """Canonical PyPI package name (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def render_env_step(env_keys: list[str], providers: list[str]) -> str:
    if len(env_keys) == 1 and len(providers) == 1:
        title = f"Export your {providers[0]} API key"
    else:
        title = "Export your API keys"
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
    title = derive_title(docstring, stem, source_path.parent.name)
    if slug and slug in TITLE_OVERRIDES:
        title = TITLE_OVERRIDES[slug]
    description = derive_description(docstring, title)
    intro = derive_intro(docstring, title)
    siblings = collect_siblings(source_path, src)
    sibling_srcs = [(p, p.read_text(encoding="utf-8")) for p in siblings]
    skip_modules = frozenset(p.stem for p in siblings)
    req = derive_requirements([src] + [s for _, s in sibling_srcs], agno_root, skip_modules)

    override = DESC_OVERRIDES.get(slug) if slug else None
    if override is not None:
        description = override
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
        + sorted(p for p in req.packages if p != "agno" and pep503(p) not in provided)
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
        plural = "s" if len(sibling_srcs) > 1 else ""
        parts.append(f"The example imports this helper module{plural} from the same directory:")
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
    env_keys = sorted(req.env_keys)
    if env_keys:
        parts.append("")
        parts.append(render_env_step(env_keys, req.providers))
    if req.needs_pgvector:
        parts.append("")
        parts.append('  <Snippet file="run-pgvector-step.mdx" />')
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
    if sibling_srcs:
        file_names = [f"`{n}`" for n in [run_name] + [p.name for p, _ in sibling_srcs]]
        joiner = " and " if len(file_names) == 2 else ", "
        parts.append(
            f"    Save the code blocks above as {joiner.join(file_names)} "
            "in the same directory, then run:"
        )
    else:
        parts.append(f"    Save the code above as `{run_name}`, then run:")
    parts.append("    ```bash")
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
