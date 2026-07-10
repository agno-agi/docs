#!/usr/bin/env python3
"""check_install_coverage.py - Find nav-reachable docs pages whose Python code
examples cannot run as documented because the page never tells the reader to
install a required non-core dependency.

For every page reachable from docs.json navigation (excluding examples/**,
reference-api/**, and deploy/**), extract the python code fences (from the
page and its transitively included _snippets/), derive the third-party
distributions the code needs, and check that the page or its snippets mention
each distribution in a shell/bash fence, an inline code span, or an install
comment inside a python fence. Mentioning an agno extra that provides the
distribution (e.g. `agno[os]`) also counts; extras are parsed from the agno
repo's libs/agno/pyproject.toml.

Requirements are derived from a curated mapping built by reading the agno
source at tag v2.7.2:
  - agno.db.* / agno.vectordb.*   the module's ImportError-guard package(s),
                                  plus sqlalchemy and a SQL driver (taken from
                                  the db_url dialect in the page's fences, or
                                  psycopg/pymysql by default) for SQL backends
  - agno.models.*                 the provider SDK package; OpenAILike
                                  subclasses need openai
  - agno.tools.*                  the toolkit's guard package(s)
  - agno.knowledge.embedder.*     the embedder's guard package(s)
  - agno.os / AgentOS / .serve()  fastapi + uvicorn
  - implicit defaults             Agent() with no model= needs openai
                                  (OpenAIResponses); a vector db constructed
                                  without embedder= needs openai
                                  (OpenAIEmbedder)

Heuristic uncertainty (unknown agno modules, Agent() without model= on a page
that imports another provider, unparseable fences containing the patterns) is
reported in a separate "review" list, not counted as an offense.

Usage:
    python scripts/check_install_coverage.py [--json] [--limit N]

Stdlib only. The agno repo defaults to the ./agno symlink at the repo root;
override with the AGNO_REPO env var (only pyproject.toml is read at runtime).
Writes scripts/out/install-coverage.json with --json. Exits 1 if any offender
pages are found, 0 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPTS_DIR.parent
OUT_DIR = SCRIPTS_DIR / "out"

sys.path.insert(0, str(SCRIPTS_DIR / "inventory"))
import _lib  # noqa: E402

AGNO_PYPROJECT = Path(
    os.environ.get("AGNO_REPO") or (DOCS_ROOT / "agno")
) / "libs" / "agno" / "pyproject.toml"

SKIP_PREFIXES = ("examples/", "reference-api/", "deploy/")

# Distributions bundled with core agno (pyproject [project] dependencies at
# v2.7.2); never reported as missing.
CORE_DISTS = {
    "agno", "agnoctl", "docstring-parser", "h11", "httpx", "packaging",
    "pydantic", "pydantic-settings", "pyyaml", "rich", "typing-extensions",
}

# ---------------------------------------------------------------------------
# Curated requirement mapping, built from the agno source at tag v2.7.2
# (libs/agno). Keys are dotted module paths; lookup takes the longest matching
# prefix. BY_NAME means the imported class name decides (see NAME_DISTS);
# a plain module import of a BY_NAME key goes to the review list.
# ---------------------------------------------------------------------------

BY_NAME = "BY_NAME"

GOOGLE_API_TRIO = ("google-api-python-client", "google-auth-httplib2",
                   "google-auth-oauthlib")

MODULE_DISTS: dict[str, tuple | str] = {
    # ---- databases (agno/db/*; guard packages; sqlalchemy for SQL backends,
    # driver added separately from the page's db_url dialect or the default)
    "agno.db": (),
    "agno.db.base": (),
    "agno.db.clickhouse": ("clickhouse-connect",),
    "agno.db.dynamo": ("boto3",),
    "agno.db.firestore": ("google-cloud-firestore",),
    "agno.db.gcs_json": ("google-cloud-storage",),
    "agno.db.in_memory": (),
    "agno.db.json": (),
    "agno.db.migrations": (),
    "agno.db.mongo": ("pymongo",),
    "agno.db.mysql": ("sqlalchemy",),
    "agno.db.postgres": ("sqlalchemy",),
    "agno.db.async_postgres": ("sqlalchemy",),
    "agno.db.redis": ("redis",),
    "agno.db.schemas": (),
    "agno.db.singlestore": ("sqlalchemy",),
    "agno.db.sqlite": ("sqlalchemy",),
    "agno.db.surrealdb": ("surrealdb",),
    "agno.db.utils": (),
    # ---- vector databases (agno/vectordb/*)
    "agno.vectordb": (),
    "agno.vectordb.base": (),
    "agno.vectordb.cassandra": ("cassio",),
    "agno.vectordb.chroma": ("chromadb",),
    "agno.vectordb.clickhouse": ("clickhouse-connect",),
    "agno.vectordb.couchbase": ("couchbase",),
    "agno.vectordb.distance": (),
    "agno.vectordb.lancedb": ("lancedb",),
    "agno.vectordb.langchaindb": ("langchain",),
    "agno.vectordb.lightrag": (),
    "agno.vectordb.llamaindex": ("llama-index-core",),
    "agno.vectordb.milvus": ("pymilvus",),
    "agno.vectordb.mongodb": ("pymongo",),
    "agno.vectordb.pgvector": ("sqlalchemy", "pgvector"),
    "agno.vectordb.pineconedb": ("pinecone",),
    "agno.vectordb.qdrant": ("qdrant-client",),
    "agno.vectordb.redis": ("redis", "redisvl"),
    "agno.vectordb.search": (),
    "agno.vectordb.score": (),
    "agno.vectordb.singlestore": ("sqlalchemy",),
    "agno.vectordb.surrealdb": ("surrealdb",),
    "agno.vectordb.upstashdb": ("upstash-vector",),
    "agno.vectordb.weaviate": ("weaviate-client",),
    # ---- models (agno/models/*; provider SDK, or openai for OpenAILike)
    "agno.models": (),
    "agno.models.base": (),
    "agno.models.defaults": (),
    "agno.models.fallback": (),
    "agno.models.message": (),
    "agno.models.metrics": (),
    "agno.models.response": (),
    "agno.models.utils": (),
    "agno.models.aimlapi": ("openai",),
    "agno.models.anthropic": ("anthropic",),
    "agno.models.aws": BY_NAME,
    "agno.models.aws.bedrock": ("boto3",),
    "agno.models.aws.claude": ("anthropic",),
    "agno.models.azure": BY_NAME,
    "agno.models.azure.ai_foundry": ("azure-ai-inference",),
    "agno.models.azure.claude": ("anthropic",),
    "agno.models.azure.openai_chat": ("openai",),
    "agno.models.cerebras": BY_NAME,
    "agno.models.cloudflare": ("openai",),
    "agno.models.cohere": ("cohere",),
    "agno.models.cometapi": ("openai",),
    "agno.models.dashscope": ("openai",),
    "agno.models.deepinfra": ("openai",),
    "agno.models.deepseek": ("openai",),
    "agno.models.fireworks": ("openai",),
    "agno.models.google": ("google-genai",),
    "agno.models.groq": ("groq",),
    "agno.models.huggingface": ("huggingface-hub",),
    "agno.models.ibm": ("ibm-watsonx-ai",),
    "agno.models.inception": ("openai",),
    "agno.models.internlm": ("openai",),
    "agno.models.langdb": ("openai",),
    "agno.models.litellm": BY_NAME,
    "agno.models.llama_cpp": ("openai",),
    "agno.models.lmstudio": ("openai",),
    "agno.models.meta": BY_NAME,
    "agno.models.minimax": ("openai",),
    "agno.models.mistral": ("mistralai",),
    "agno.models.moonshot": ("openai",),
    "agno.models.n1n": ("openai",),
    "agno.models.nebius": ("openai",),
    "agno.models.neosantara": ("openai",),
    "agno.models.nexus": ("openai",),
    "agno.models.nvidia": ("openai",),
    "agno.models.ollama": ("ollama",),
    "agno.models.openai": ("openai",),
    "agno.models.openrouter": ("openai",),
    "agno.models.perplexity": ("openai",),
    "agno.models.portkey": ("portkey-ai",),
    "agno.models.requesty": ("openai",),
    "agno.models.sambanova": ("openai",),
    "agno.models.siliconflow": ("openai",),
    "agno.models.together": ("openai",),
    "agno.models.tuning_engines": ("openai",),
    "agno.models.vercel": ("openai",),
    "agno.models.vertexai": ("anthropic",),
    "agno.models.vllm": ("openai",),
    "agno.models.xai": ("openai",),
    "agno.models.xiaomi": ("openai",),
    # ---- tools (agno/tools/*; ImportError-guard packages; requests where a
    # module imports it unguarded, since requests is not a core dependency)
    "agno.tools": (),
    "agno.tools.agentql": ("agentql", "playwright"),
    "agno.tools.airflow": (),
    "agno.tools.antigravity": (),
    "agno.tools.api": ("requests",),
    "agno.tools.apify": ("apify-client",),
    "agno.tools.arxiv": ("arxiv", "pypdf"),
    "agno.tools.aws_lambda": ("boto3",),
    "agno.tools.aws_ses": ("boto3",),
    "agno.tools.baidusearch": ("baidusearch", "pycountry"),
    "agno.tools.bitbucket": ("requests",),
    "agno.tools.brandfetch": (),
    "agno.tools.bravesearch": ("brave-search",),
    "agno.tools.brightdata": ("requests",),
    "agno.tools.browserbase": ("browserbase", "playwright"),
    "agno.tools.calcom": ("requests", "pytz"),
    "agno.tools.calculator": (),
    "agno.tools.cartesia": ("cartesia",),
    "agno.tools.clickup": ("requests",),
    "agno.tools.coding": (),
    "agno.tools.confluence": ("atlassian-python-api",),
    "agno.tools.crawl4ai": ("crawl4ai",),
    "agno.tools.csv_toolkit": (),  # duckdb optional; degrades gracefully
    "agno.tools.dalle": ("openai",),
    "agno.tools.daytona": ("daytona",),
    "agno.tools.desi_vocal": ("requests",),
    "agno.tools.discord": ("requests",),
    "agno.tools.docker": ("docker",),
    "agno.tools.docling": ("docling",),
    "agno.tools.duckdb": ("duckdb",),
    "agno.tools.duckduckgo": ("ddgs",),  # shim over websearch
    "agno.tools.e2b": ("e2b-code-interpreter",),
    "agno.tools.eleven_labs": ("elevenlabs",),
    "agno.tools.email": (),
    "agno.tools.evm": ("web3",),
    "agno.tools.exa": ("exa-py",),
    "agno.tools.fal": ("fal-client",),
    "agno.tools.file": (),
    "agno.tools.file_generation": (),  # reportlab/python-docx per format
    "agno.tools.financial_datasets": ("requests",),
    "agno.tools.firecrawl": ("firecrawl-py",),
    "agno.tools.giphy": (),
    "agno.tools.github": ("pygithub",),
    "agno.tools.gitlab": ("python-gitlab",),
    "agno.tools.google": BY_NAME,
    "agno.tools.google.auth": GOOGLE_API_TRIO,
    "agno.tools.google.base": GOOGLE_API_TRIO,
    "agno.tools.google.bigquery": ("google-cloud-bigquery",),
    "agno.tools.google.calendar": GOOGLE_API_TRIO,
    "agno.tools.google.drive": GOOGLE_API_TRIO,
    "agno.tools.google.gmail": GOOGLE_API_TRIO,
    "agno.tools.google.maps": ("googlemaps", "google-maps-places"),
    "agno.tools.google.sheets": GOOGLE_API_TRIO,
    "agno.tools.google.slides": GOOGLE_API_TRIO,
    # deprecated flat shims for the google package
    "agno.tools.gmail": GOOGLE_API_TRIO,
    "agno.tools.google_bigquery": ("google-cloud-bigquery",),
    "agno.tools.google_drive": GOOGLE_API_TRIO,
    "agno.tools.google_maps": ("googlemaps", "google-maps-places"),
    "agno.tools.googlecalendar": GOOGLE_API_TRIO,
    "agno.tools.googlesheets": GOOGLE_API_TRIO,
    "agno.tools.hackernews": (),
    "agno.tools.jina": (),
    "agno.tools.jira": ("jira",),
    "agno.tools.knowledge": (),
    "agno.tools.linear": ("requests",),
    "agno.tools.linkup": ("linkup-sdk",),
    "agno.tools.llms_txt": (),
    "agno.tools.local_file_system": (),
    "agno.tools.lumalab": ("lumaai",),
    "agno.tools.mcp": ("mcp",),
    "agno.tools.mcp_toolbox": ("toolbox-core",),
    "agno.tools.mem0": ("mem0ai",),
    "agno.tools.memory": (),
    "agno.tools.mlx_transcribe": ("mlx-whisper",),
    "agno.tools.models": BY_NAME,
    "agno.tools.models.azure_openai": ("openai",),
    "agno.tools.models.gemini": ("google-genai",),
    "agno.tools.models.groq": ("groq",),
    "agno.tools.models.morph": ("openai",),
    "agno.tools.models.nebius": ("openai",),
    "agno.tools.models_labs": ("requests",),
    "agno.tools.moviepy_video": ("moviepy",),
    "agno.tools.nano_banana": ("google-genai", "pillow"),
    "agno.tools.neo4j": ("neo4j",),
    "agno.tools.newspaper": ("newspaper3k", "lxml-html-clean"),
    "agno.tools.newspaper4k": ("newspaper4k", "lxml-html-clean"),
    "agno.tools.notion": ("notion-client",),
    "agno.tools.openai": ("openai",),
    "agno.tools.openbb": ("openbb",),
    "agno.tools.opencv": ("opencv-python",),
    "agno.tools.openweather": ("requests",),
    "agno.tools.oxylabs": ("oxylabs",),
    "agno.tools.pandas": ("pandas",),
    "agno.tools.parallel": ("parallel-web",),
    "agno.tools.perplexity": (),
    "agno.tools.postgres": ("psycopg",),
    "agno.tools.pubmed": (),
    "agno.tools.python": (),
    "agno.tools.reasoning": (),
    "agno.tools.reddit": ("praw",),
    "agno.tools.redshift": ("redshift-connector",),
    "agno.tools.replicate": ("replicate",),
    "agno.tools.resend": ("resend",),
    "agno.tools.salesforce": ("simple-salesforce",),
    "agno.tools.scavio": ("scavio",),
    "agno.tools.scheduler": (),
    "agno.tools.scrapegraph": ("scrapegraph-py",),
    "agno.tools.searchapi": ("requests",),
    "agno.tools.searxng": (),
    "agno.tools.seltz": ("seltz",),
    "agno.tools.serpapi": ("google-search-results",),
    "agno.tools.serper": ("requests",),
    "agno.tools.shell": (),
    "agno.tools.shopify": (),
    "agno.tools.slack": ("slack-sdk",),
    "agno.tools.sleep": (),
    "agno.tools.sofya": ("requests",),
    "agno.tools.spider": ("spider-client",),
    "agno.tools.spotify": (),
    "agno.tools.sql": ("sqlalchemy",),
    "agno.tools.streamlit": ("streamlit",),
    "agno.tools.studio": (),
    "agno.tools.tavily": ("tavily-python",),
    "agno.tools.telegram": ("pytelegrambotapi",),
    "agno.tools.todoist": ("todoist-api-python",),
    "agno.tools.trafilatura": ("trafilatura",),
    "agno.tools.trello": ("py-trello",),
    "agno.tools.twelvelabs": ("twelvelabs",),
    "agno.tools.twilio": ("twilio",),
    "agno.tools.unsplash": (),
    "agno.tools.user_control_flow": (),
    "agno.tools.user_feedback": (),
    "agno.tools.valyu": ("valyu",),
    "agno.tools.visualization": ("matplotlib",),
    "agno.tools.webbrowser": (),
    "agno.tools.webex": ("webexpythonsdk",),
    "agno.tools.websearch": ("ddgs",),
    "agno.tools.website": (),
    "agno.tools.webtools": (),
    "agno.tools.whatsapp": (),
    "agno.tools.wikipedia": ("wikipedia",),
    "agno.tools.workflow": (),
    "agno.tools.workspace": (),
    "agno.tools.x": ("tweepy",),
    "agno.tools.yfinance": ("yfinance",),
    "agno.tools.youcom": (),
    "agno.tools.youtube": ("youtube-transcript-api",),
    "agno.tools.zendesk": ("requests",),
    "agno.tools.zep": ("zep-cloud",),
    "agno.tools.zoom": ("requests",),
    # ---- embedders (agno/knowledge/embedder/*)
    "agno.knowledge.embedder": (),
    "agno.knowledge.embedder.base": (),
    "agno.knowledge.embedder.aws_bedrock": ("boto3",),
    "agno.knowledge.embedder.azure_openai": ("openai",),
    "agno.knowledge.embedder.cohere": ("cohere",),
    "agno.knowledge.embedder.fastembed": ("fastembed",),
    "agno.knowledge.embedder.fireworks": ("openai",),
    "agno.knowledge.embedder.google": ("google-genai",),
    "agno.knowledge.embedder.huggingface": ("huggingface-hub",),
    "agno.knowledge.embedder.jina": ("requests", "aiohttp"),
    "agno.knowledge.embedder.langdb": ("openai",),
    "agno.knowledge.embedder.mistral": ("mistralai",),
    "agno.knowledge.embedder.nebius": ("openai",),
    "agno.knowledge.embedder.ollama": ("ollama",),
    "agno.knowledge.embedder.openai": ("openai",),
    "agno.knowledge.embedder.openai_like": ("openai",),
    "agno.knowledge.embedder.sentence_transformer": ("sentence-transformers",),
    "agno.knowledge.embedder.together": ("openai",),
    "agno.knowledge.embedder.vllm": BY_NAME,  # local: vllm, remote: openai
    "agno.knowledge.embedder.voyageai": ("voyageai",),
    # ---- AgentOS (agno/os/*)
    "agno.os": ("fastapi", "uvicorn"),
    "agno.os.interfaces.a2a": ("fastapi", "uvicorn", "a2a-sdk"),
    "agno.os.interfaces.agui": ("fastapi", "uvicorn", "ag-ui-protocol"),
    "agno.os.interfaces.slack": ("fastapi", "uvicorn", "slack-sdk"),
}

# Imported-name overrides: (module as written in the import, class name).
NAME_DISTS: dict[tuple[str, str], tuple] = {
    ("agno.db", "ClickhouseDb"): ("clickhouse-connect",),
    ("agno.db", "DynamoDb"): ("boto3",),
    ("agno.db", "MongoDb"): ("pymongo",),
    ("agno.db", "PostgresDb"): ("sqlalchemy",),
    ("agno.db.mongo", "AsyncMongoDb"): ("pymongo", "motor"),
    ("agno.db.sqlite", "AsyncSqliteDb"): ("sqlalchemy", "aiosqlite"),
    ("agno.models.aws", "AwsBedrock"): ("boto3",),
    ("agno.models.aws", "Claude"): ("anthropic",),
    ("agno.models.azure", "AzureAIFoundry"): ("azure-ai-inference",),
    ("agno.models.azure", "AzureOpenAI"): ("openai",),
    ("agno.models.azure", "Claude"): ("anthropic",),
    ("agno.models.cerebras", "Cerebras"): ("cerebras-cloud-sdk",),
    ("agno.models.cerebras", "CerebrasOpenAI"): ("openai",),
    ("agno.models.litellm", "LiteLLM"): ("litellm",),
    ("agno.models.litellm", "LiteLLMOpenAI"): ("openai",),
    ("agno.models.meta", "Llama"): ("llama-api-client",),
    ("agno.models.meta", "LlamaOpenAI"): ("openai",),
    ("agno.tools.google", "BigQueryTools"): ("google-cloud-bigquery",),
    ("agno.tools.google", "GmailTools"): GOOGLE_API_TRIO,
    ("agno.tools.google", "GoogleCalendarTools"): GOOGLE_API_TRIO,
    ("agno.tools.google", "GoogleDriveTools"): GOOGLE_API_TRIO,
    ("agno.tools.google", "GoogleMapsTools"): ("googlemaps", "google-maps-places"),
    ("agno.tools.google", "GoogleSheetsTools"): GOOGLE_API_TRIO,
    ("agno.tools.google", "GoogleSlidesTools"): GOOGLE_API_TRIO,
    ("agno.tools.models", "AzureOpenAITools"): ("openai",),
    ("agno.tools.models", "GeminiTools"): ("google-genai",),
    ("agno.tools.models", "GroqTools"): ("groq",),
    ("agno.tools.models", "MorphTools"): ("openai",),
    ("agno.tools.models", "NebiusTools"): ("openai",),
    ("agno.knowledge.embedder.vllm", "VLLMEmbedder"): ("openai",),
}

# Module families the mapping claims to cover; imports under these that miss
# the mapping go to the review list.
FAMILY_PREFIXES = (
    "agno.db", "agno.vectordb", "agno.models", "agno.tools",
    "agno.knowledge.embedder", "agno.os",
)

# Vector db classes whose constructor defaults embedder to OpenAIEmbedder
# (checked in the v2.7.2 source; Upstash, LangChain, LlamaIndex, and LightRag
# wrappers do not).
EMBEDDER_DEFAULT_CLASSES = {
    "Cassandra", "ChromaDb", "Clickhouse", "CouchbaseSearch", "LanceDb",
    "Milvus", "MongoDb", "PgVector", "PineconeDb", "Qdrant", "RedisDB",
    "SingleStore", "SurrealDb", "Weaviate",
}

# SQL backends: which imports imply which default driver when the page shows
# no explicit db_url dialect.
POSTGRES_MODULES = ("agno.db.postgres", "agno.db.async_postgres",
                    "agno.vectordb.pgvector")
MYSQL_MODULES = ("agno.db.mysql", "agno.db.singlestore",
                 "agno.vectordb.singlestore")
POSTGRES_NAMES = {"PostgresDb", "AsyncPostgresDb", "PgVector"}
MYSQL_NAMES = {"MySQLDb", "AsyncMySQLDb", "SingleStoreDb", "SingleStore"}

DIALECT_RE = re.compile(r"\b(?:postgresql|mysql|mariadb|sqlite)\+([a-z0-9_]+)")
DIALECT_DISTS = {
    "psycopg": "psycopg",
    "psycopg_async": "psycopg",
    "psycopg2": "psycopg2",
    "asyncpg": "asyncpg",
    "pg8000": "pg8000",
    "pymysql": "pymysql",
    "asyncmy": "asyncmy",
    "mysqldb": "mysqlclient",
    "mysqlconnector": "mysql-connector-python",
    "aiosqlite": "aiosqlite",
}

SHELL_LANGS = {"", "bash", "shell", "sh", "zsh", "console", "terminal"}
PYTHON_LANGS = {"python", "py"}

FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
ENVVAR_RE = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")
AGNO_EXTRA_RE = re.compile(r"\bagno\[([a-zA-Z0-9_,\- ]+)\]")
# .serve( alone is ambiguous: DiscordClient.serve() runs on the Gateway API with no
# fastapi/uvicorn. Require an AgentOS construction or an agno.os import in the same fence.
OS_PATTERN_RE = re.compile(r"\bAgentOS\s*\(|\bagent_os\.serve\s*\(|from agno\.os\b")


ALLOWLIST_PATH = Path(__file__).resolve().parent / "install-coverage-allowlist.txt"


def load_allowlist() -> set:
    """Nav slugs exempted by editorial policy (illustrative fragment pages)."""
    if not ALLOWLIST_PATH.exists():
        return set()
    out = set()
    for line in ALLOWLIST_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out
INSTALL_LINE_RE = re.compile(r"\b(pip install|uv add|poetry add|conda install)\b")


# ---------------------------------------------------------------------------
# agno extras (parsed from libs/agno/pyproject.toml)
# ---------------------------------------------------------------------------

def parse_extras(pyproject_text: str) -> dict[str, frozenset[str]]:
    """extra name -> set of distributions it provides (agno[x] refs resolved
    transitively). Regex/bracket parse; stdlib tomllib needs 3.11+."""
    lines = pyproject_text.split("\n")
    raw: dict[str, list[str]] = {}
    in_section = False
    name, buf, depth = None, "", 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped == "[project.optional-dependencies]"
            continue
        if not in_section:
            continue
        line = line.split("#", 1)[0]
        if name is None:
            m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*=\s*(\[.*)$", line)
            if not m:
                continue
            name, buf, depth = m.group(1), "", 0
            line = m.group(2)
        buf += line + "\n"
        depth += line.count("[") - line.count("]")
        if depth <= 0:
            raw[name] = re.findall(r'"([^"]+)"|\'([^\']+)\'', buf)
            raw[name] = [a or b for a, b in raw[name]]
            name = None

    def expand(extra: str, seen: frozenset[str]) -> set[str]:
        dists: set[str] = set()
        for dep in raw.get(extra, []):
            m = re.match(r"\s*([A-Za-z0-9._-]+)\s*(\[([^\]]*)\])?", dep)
            if not m:
                continue
            dist = m.group(1)
            if dist.lower() == "agno" and m.group(3):
                for sub in m.group(3).split(","):
                    sub = sub.strip()
                    if sub and sub not in seen:
                        dists |= expand(sub, seen | {sub})
            else:
                dists.add(dist)
        return dists

    return {extra: frozenset(expand(extra, frozenset([extra])))
            for extra in raw}


# ---------------------------------------------------------------------------
# Page scanning
# ---------------------------------------------------------------------------

def extract_fences(text: str) -> list[tuple[str, str]]:
    """(language, body) for every fenced code block, in order."""
    out = []
    fence, lang, buf = None, "", []
    for line in text.split("\n"):
        m = FENCE_LINE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                info = m.group(2).strip()
                lang = info.split()[0].lower() if info else ""
                buf = []
        elif (m and not m.group(2).strip()
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)):
            out.append((lang, "\n".join(buf)))
            fence = None
        else:
            buf.append(line)
    return out


IMPORT_FALLBACK_RE = re.compile(
    r"^\s*(from\s+(agno[.\w]*)\s+import\s+(.+)|import\s+(agno[.\w]*))\s*$")


class PageScan:
    """Everything extracted from one page's python fences (page + snippets)."""

    def __init__(self):
        self.imports: list[tuple[str, str | None, str]] = []  # (mod, name, evidence)
        self.agent_calls_no_model: list[str] = []
        self.agent_calls_with_model = 0
        self.vect_calls_no_embedder: list[str] = []
        self.vect_calls_with_embedder = 0
        self.dialect_drivers: dict[str, str] = {}  # dist -> evidence
        self.os_usage: list[str] = []
        self.unparseable: list[str] = []  # fences with patterns ast could not parse
        self.python_fences = 0


def scan_python_fences(sources: list[tuple[str, str]]) -> PageScan:
    """sources: (origin label, mdx text) for the page and its snippets."""
    scan = PageScan()
    parsed: list[tuple[str, ast.AST]] = []
    bodies: list[tuple[str, str]] = []

    for origin, text in sources:
        for lang, body in extract_fences(text):
            if lang not in PYTHON_LANGS:
                continue
            scan.python_fences += 1
            body = textwrap.dedent(body)
            bodies.append((origin, body))
            try:
                parsed.append((origin, ast.parse(body)))
            except SyntaxError:
                parsed.append((origin, None))

    # Pass 1: imports (ast where possible, line regex otherwise).
    vect_bindings: dict[str, str] = {}  # local name -> vectordb class
    for (origin, tree), (_, body) in zip(parsed, bodies):
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name == "agno" or a.name.startswith("agno."):
                            scan.imports.append(
                                (a.name, None, f"{origin}: import {a.name}"))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mod = node.module or ""
                    if mod != "agno" and not mod.startswith("agno."):
                        continue
                    for a in node.names:
                        scan.imports.append(
                            (mod, a.name,
                             f"{origin}: from {mod} import {a.name}"))
                        if (mod.startswith("agno.vectordb")
                                and a.name in EMBEDDER_DEFAULT_CLASSES):
                            vect_bindings[a.asname or a.name] = a.name
        else:
            for line in body.split("\n"):
                m = IMPORT_FALLBACK_RE.match(line)
                if not m:
                    continue
                if m.group(4):
                    scan.imports.append(
                        (m.group(4), None, f"{origin}: import {m.group(4)}"))
                    continue
                mod = m.group(2)
                for piece in m.group(3).split(","):
                    name = piece.strip().split(" as ")[0].strip("() ")
                    if not name:
                        continue
                    scan.imports.append(
                        (mod, name, f"{origin}: from {mod} import {name}"))
                    if (mod.startswith("agno.vectordb")
                            and name in EMBEDDER_DEFAULT_CLASSES):
                        vect_bindings[name] = name

    # Pass 2: call patterns, dialects, AgentOS usage.
    for (origin, tree), (_, body) in zip(parsed, bodies):
        for m in DIALECT_RE.finditer(body):
            dist = DIALECT_DISTS.get(m.group(1))
            if dist:
                scan.dialect_drivers.setdefault(
                    dist, f"{origin}: db_url dialect '{m.group(0)}'")
        if OS_PATTERN_RE.search(body):
            scan.os_usage.append(
                f"{origin}: AgentOS(...)/.serve(...) in python fence")
        if tree is None:
            if "Agent(" in body or any(
                    f"{n}(" in body for n in vect_bindings):
                scan.unparseable.append(origin)
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            splat = None in kwargs
            if node.func.id == "Agent":
                if "model" in kwargs or splat:
                    scan.agent_calls_with_model += 1
                else:
                    scan.agent_calls_no_model.append(
                        f"{origin}: Agent(...) call without model=")
            elif node.func.id in vect_bindings:
                cls = vect_bindings[node.func.id]
                if "embedder" in kwargs or splat:
                    scan.vect_calls_with_embedder += 1
                else:
                    scan.vect_calls_no_embedder.append(
                        f"{origin}: {cls}(...) call without embedder=")
    return scan


def in_family(module: str) -> bool:
    return any(module == p or module.startswith(p + ".")
               for p in FAMILY_PREFIXES)


def resolve_import(module: str, name: str | None):
    """-> (dists tuple or None, review reason or None)."""
    if name and (module, name) in NAME_DISTS:
        return NAME_DISTS[(module, name)], None
    parts = module.split(".")
    for i in range(len(parts), 1, -1):
        key = ".".join(parts[:i])
        val = MODULE_DISTS.get(key)
        if val is None:
            continue
        if val == BY_NAME:
            what = f"from {module} import {name}" if name else f"import {module}"
            return None, f"'{what}' needs a known class name to resolve ({key} is provider-per-class)"
        return val, None
    if in_family(module):
        what = f"from {module} import {name}" if name else f"import {module}"
        return None, f"'{what}': module not in the v2.7.2 mapping"
    return (), None


def page_requirements(scan: PageScan):
    """-> (requirements {dist: [evidence]}, review [detail strings],
           provider_imported, embedder_imported)."""
    reqs: dict[str, list[str]] = {}
    review: list[str] = []
    provider_imported = False
    embedder_imported = False
    postgres_backend: list[str] = []
    mysql_backend: list[str] = []

    def add(dist: str, evidence: str):
        if dist in CORE_DISTS:
            return
        reqs.setdefault(dist, [])
        if evidence not in reqs[dist]:
            reqs[dist].append(evidence)

    seen = set()
    for module, name, evidence in scan.imports:
        key = (module, name)
        if key in seen:
            continue
        seen.add(key)
        dists, reason = resolve_import(module, name)
        if reason:
            review.append(reason)
            continue
        for dist in dists:
            add(dist, evidence)
        if module.startswith("agno.models.") and dists:
            provider_imported = True
        if module.startswith("agno.knowledge.embedder.") and dists:
            embedder_imported = True
        if (any(module == p or module.startswith(p + ".") for p in POSTGRES_MODULES)
                or (name in POSTGRES_NAMES and module.startswith("agno."))):
            postgres_backend.append(evidence)
        elif (any(module == p or module.startswith(p + ".") for p in MYSQL_MODULES)
                or (name in MYSQL_NAMES and module.startswith("agno."))):
            mysql_backend.append(evidence)

    # SQL driver: explicit db_url dialect wins, else backend default.
    if scan.dialect_drivers:
        for dist, evidence in scan.dialect_drivers.items():
            add(dist, evidence)
    elif postgres_backend:
        add("psycopg", postgres_backend[0] + " (default postgres driver)")
    elif mysql_backend:
        add("pymysql", mysql_backend[0] + " (default mysql driver)")

    for evidence in scan.os_usage[:1]:
        add("fastapi", evidence)
        add("uvicorn", evidence)

    for origin in scan.unparseable:
        review.append(
            f"{origin}: python fence with Agent(/vector db call did not parse; "
            "implicit-default heuristics skipped")

    return reqs, review, provider_imported, embedder_imported


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def norm(s: str) -> str:
    return s.lower().replace("_", "-").replace(".", "-")


def coverage_corpus(sources: list[tuple[str, str]]):
    """-> (normalized corpus text, install lines, raw page+snippet text)."""
    parts: list[str] = []
    install_lines: list[str] = []
    raw_all: list[str] = []
    for _origin, text in sources:
        raw_all.append(text)
        for lang, body in extract_fences(text):
            if lang in SHELL_LANGS:
                parts.append(body)
                install_lines.extend(
                    ln for ln in body.split("\n") if INSTALL_LINE_RE.search(ln))
            elif lang in PYTHON_LANGS:
                for ln in body.split("\n"):
                    stripped = ln.strip()
                    if stripped.startswith("#") and INSTALL_LINE_RE.search(stripped):
                        parts.append(stripped)
                        install_lines.append(stripped)
        blanked = "\n".join(_lib.blank_noncontent_lines(text))
        for span in _lib.INLINE_CODE_RE.findall(blanked):
            span = span.strip("`")
            # skip bare CamelCase identifiers (class names like PgVector that
            # would otherwise shadow same-named distributions)
            if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", span):
                continue
            parts.append(span)
    corpus = ENVVAR_RE.sub(" ", "\n".join(parts))
    return norm(corpus), install_lines, "\n".join(raw_all)


def covered_dists(corpus: str, install_lines: list[str], raw_text: str,
                  extras: dict[str, frozenset[str]],
                  required: set[str]) -> set[str]:
    covered = set()
    extra_dists: set[str] = set()
    for m in AGNO_EXTRA_RE.finditer(corpus):
        for extra in m.group(1).split(","):
            extra_dists |= extras.get(extra.strip(), frozenset())
    # Extras coverage uses the same token matching as the corpus, so e.g.
    # agno[postgres] (-> psycopg-binary) covers a psycopg requirement.
    corpus = corpus + "\n" + norm(" ".join(sorted(extra_dists)))
    for dist in required:
        nd = norm(dist)
        if re.search(rf"(?<![a-z0-9]){re.escape(nd)}(?![a-z0-9])", corpus):
            covered.add(dist)
            continue
        if (dist == "openai" and "OPENAI_API_KEY" in raw_text
                and any("openai" in norm(ln) for ln in install_lines)):
            covered.add(dist)
    return covered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_report(ctx: _lib.Context, extras: dict[str, frozenset[str]]) -> dict:
    offenders: dict[str, dict[str, list[str]]] = {}
    allowlisted: dict[str, dict[str, list[str]]] = {}
    allowlist = load_allowlist()
    review: dict[str, list[str]] = {}
    skipped_generated = 0
    pages_no_python = 0
    pages_scanned = 0

    for slug in sorted(ctx.live_pages):
        if any(slug.startswith(p) for p in SKIP_PREFIXES):
            skipped_generated += 1
            continue
        rel = _lib.slug_file(slug)
        sources = [(rel, _lib.read_text(rel))]
        for snip in sorted(ctx.snippets_of(rel)):
            sources.append((snip, _lib.read_text(snip)))

        scan = scan_python_fences(sources)
        if scan.python_fences == 0:
            pages_no_python += 1
            continue
        pages_scanned += 1

        reqs, page_review, provider_imported, embedder_imported = \
            page_requirements(scan)
        corpus, install_lines, raw_text = coverage_corpus(sources)

        # Implicit default model: Agent() without model=.
        openai_known = "openai" in reqs
        if scan.agent_calls_no_model and not openai_known:
            if not provider_imported and scan.agent_calls_with_model == 0:
                reqs.setdefault("openai", []).append(
                    scan.agent_calls_no_model[0]
                    + " (defaults to OpenAIResponses)")
            elif not covered_dists(corpus, install_lines, raw_text, extras,
                                   {"openai"}):
                page_review.append(
                    scan.agent_calls_no_model[0]
                    + " (page also shows another provider or model=; may "
                    "need openai for the default model)")

        # Implicit default embedder: vector db constructed without embedder=.
        if scan.vect_calls_no_embedder and "openai" not in reqs:
            if not embedder_imported and scan.vect_calls_with_embedder == 0:
                reqs.setdefault("openai", []).append(
                    scan.vect_calls_no_embedder[0]
                    + " (defaults to OpenAIEmbedder)")
            elif not covered_dists(corpus, install_lines, raw_text, extras,
                                   {"openai"}):
                page_review.append(
                    scan.vect_calls_no_embedder[0]
                    + " (page also shows an embedder; may need openai for "
                    "the default embedder)")

        required = set(reqs)
        covered = covered_dists(corpus, install_lines, raw_text, extras,
                                required)
        missing = {d: sorted(reqs[d]) for d in sorted(required - covered)}
        if missing:
            if slug in allowlist:
                allowlisted[slug] = missing
            else:
                offenders[slug] = missing
        if page_review:
            review[slug] = sorted(set(page_review))

    return {
        "counts": {
            "nav_reachable_pages": len(ctx.live_pages),
            "skipped_generated_or_locked": skipped_generated,
            "pages_without_python": pages_no_python,
            "pages_scanned": pages_scanned,
            "offender_pages": len(offenders),
            "allowlisted_pages": len(allowlisted),
            "missing_requirements_total": sum(len(v) for v in offenders.values()),
            "review_pages": len(review),
        },
        "offenders": offenders,
        "allowlisted": allowlisted,
        "review": review,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0], )
    parser.add_argument("--json", action="store_true",
                        help="also write the full report to "
                             "scripts/out/install-coverage.json")
    parser.add_argument("--limit", type=int, default=25,
                        help="max items per list on stdout (0 = all; default 25)")
    args = parser.parse_args(argv)

    if not AGNO_PYPROJECT.is_file():
        sys.exit(f"error: agno pyproject not found at {AGNO_PYPROJECT}; "
                 "create the ./agno symlink at the repo root or set AGNO_REPO")
    extras = parse_extras(AGNO_PYPROJECT.read_text(encoding="utf-8"))

    report = build_report(_lib.Context(), extras)

    _lib.print_counts(report["counts"])
    offender_lines = [
        f"{page}  ->  {', '.join(missing)}"
        for page, missing in report["offenders"].items()
    ]
    _lib.print_list("Offenders (page -> missing installs)",
                    offender_lines, args.limit)
    review_lines = [f"{page}: {detail}"
                    for page, details in report["review"].items()
                    for detail in details]
    _lib.print_list("Review (heuristic uncertainty, not counted as offenses)",
                    review_lines, args.limit)

    if args.json:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / "install-coverage.json"
        out_path.write_text(json.dumps(report, indent=2) + "\n",
                            encoding="utf-8")
        print(f"\nReport written to {out_path}")

    return 1 if report["offenders"] else 0


if __name__ == "__main__":
    sys.exit(main())
