# Cookbook → Docs Examples Sync Prompt

Use this prompt to re-sync the `docs/examples/` directory from the `cookbook/` directory. This is a comprehensive, self-contained prompt that can be executed by Codex or any coding agent.

---

## The Prompt

````
# Sync Cookbook to Docs Examples

## Objective

Synchronize `docs/examples/` with `cookbook/` so every cookbook Python script has a corresponding MDX page. Then restructure the Examples tab sidebar in `docs/docs.json` for progressive disclosure.

This is an incremental sync — update existing pages, add new ones, remove pages for deleted cookbooks, and rebuild docs.json.

## Rules

1. DO NOT change Python code — copy it verbatim into the MDX code block
2. DO NOT add emojis
3. DO NOT delete any .mdx files unless the corresponding cookbook .py file no longer exists
4. Keep all other tabs in docs.json unchanged

---

## Step 1: Generate/Update MDX Files

For every `.py` file under `cookbook/` (recursively), generate a corresponding `.mdx` file under `docs/examples/`. Skip `__init__.py`, `conftest.py`, `scripts/` helper files (except skill scripts), and `__pycache__/`.

### Directory Mapping

The cookbook path maps to the docs path by:
1. Strip `cookbook/` prefix
2. Strip leading number prefixes from directory names: `00_quickstart` → `quickstart`, `02_agents` → `agents`, `14_advanced` → `advanced`
3. Convert underscores to hyphens in directory names: `input_output` → `input-output`
4. Convert underscores to hyphens in filenames (without `.py`), preserving a leading underscore when present:
   - `agent_with_tools.py` → `agent-with-tools.mdx`
   - `_agents.py` → `_agents.mdx`
5. Preserve nested directory structure

Examples:
- `cookbook/00_quickstart/agent_with_tools.py` → `docs/examples/quickstart/agent-with-tools.mdx`
- `cookbook/02_agents/14_advanced/debug.py` → `docs/examples/agents/advanced/debug.mdx`
- `cookbook/03_teams/modes/broadcast/basic.py` → `docs/examples/teams/modes/broadcast/basic.mdx`
- `cookbook/90_models/openai/chat/tool_use.py` → `docs/examples/models/openai/chat/tool-use.mdx`
- `cookbook/05_agent_os/advanced_demo/_agents.py` → `docs/examples/agent-os/advanced-demo/_agents.mdx`
- `cookbook/05_agent_os/advanced_demo/_teams.py` → `docs/examples/agent-os/advanced-demo/_teams.mdx`
- `cookbook/91_tools/yfinance_tools.py` → `docs/examples/tools/yfinance-tools.mdx`

### MDX Page Template

Each page follows this exact template:

```mdx
---
title: "<TITLE>"
sidebarTitle: "<SIDEBAR_TITLE>"
description: "<DESCRIPTION>"
---

<INTRO_PARAGRAPH>

```python
<FULL_PYTHON_SOURCE>
```

## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/<COOKBOOK_PATH>

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

# Run PgVector [if needed by example]
./cookbook/scripts/run_pgvector.sh

# Export relevant API keys, eg:
export OPENAI_API_KEY="sk-***"

python <FILENAME>.py
```
```

### Field Derivation Rules

#### title
Read the Python file's docstring (the `"""..."""` at the top of the file).
- If the docstring has a single-line title (first line), use it verbatim
- If the docstring has a `Title - Subtitle` format, use the full string
- If there's no docstring, derive from filename: `agent_with_tools.py` → `"Agent with Tools"`
- NEVER use a sentence as a title. If the docstring first line IS a sentence (starts with "Example demonstrating...", "This example...", "Shows how to..."), derive the title from the filename instead

#### sidebarTitle (context-aware)
The sidebarTitle depends on WHERE the page sits in the directory hierarchy. Pages nested under a section already have context from their parent group.

**Step 1**: Split the title on ` - ` and take the first part (strip subtitle):
- `"Agent with Structured Output - Finance Agent with Typed Responses"` → `"Agent with Structured Output"`

**Step 2**: Apply context-aware prefix stripping based on the page's directory:

- **Pages under `examples/quickstart/`**: Use the part before ` - ` as-is (keep "Agent with" prefix since there's no parent section context)
  - `"Agent with Structured Output - ..."` → sidebarTitle: `"Agent with Structured Output"`

- **Pages under `examples/agents/`**: Strip `"Agent with "` and `"Agent "` prefixes
  - `"Agent with Structured Output"` → sidebarTitle: `"Structured Output"`
  - `"Agent Serialization"` → sidebarTitle: `"Serialization"`
  - `"Basic Agent"` → keep as-is (stripping would leave nothing useful)

- **Pages under `examples/teams/`**: Strip `"Team "` and `"Team with "` prefixes similarly
  - `"Team with Knowledge"` → sidebarTitle: `"Knowledge"`
  - `"Team Streaming"` → sidebarTitle: `"Streaming"`

- **All other sections**: Use part before ` - ` as-is

**Step 3**: Validation:
- If the title does NOT contain ` - ` and no prefix stripping applies, do NOT add sidebarTitle
- If stripping would result in a sidebarTitle of 2 characters or fewer, keep the original
- NEVER use a sentence as sidebarTitle. If the result is a sentence, derive from filename instead

#### description
Read the first sentence after the `===` separator in the Python docstring.
- Must end with a period
- Max 150 characters
- If the docstring only has the title repeated (like `"Debug."` or `"Agent Serialization."`), try to derive a better description from the code content:
  - If the code uses `debug_mode`: "Enable debug mode for verbose agent output."
  - If the code uses `get_session_metrics`: "Access message, run, and session metrics from agent runs."
  - If the code uses `RunEvent` and `stream_events`: "Stream agent events including run lifecycle, tool calls, and content."
  - If the code uses `to_dict`/`from_dict`: "Serialize and deserialize agents using to_dict/from_dict and save/load."
  - If the code uses `asyncio.gather`: "Run multiple agents concurrently using asyncio.gather."
  - Otherwise, use the title + period as the description
- NEVER use install instructions, setup commands, or bash comments as descriptions

#### Intro paragraph
Derived from the Python docstring:
1. Read the docstring from the code
2. Extract the first paragraph after the `===` separator line (all lines until the first blank line)
3. Use that as the intro paragraph (placed between `---` and the code block)
4. If the extracted text is identical to the description field, REMOVE the intro paragraph entirely (avoid duplication)
5. If the docstring has no meaningful content beyond the title/separator, REMOVE the intro paragraph
6. The intro paragraph should add value beyond the description — it should be the expanded version

#### Run section
- `cd agno/cookbook/<PATH>` — use the actual cookbook directory path (with number prefixes intact): `cd agno/cookbook/00_quickstart`, `cd agno/cookbook/02_agents/14_advanced`
- IMPORTANT: Always include `cookbook/` in the path. Never write `cd agno/00_quickstart` (wrong)
- `python <filename>.py` — use the original Python filename (with underscores)

### Overview Pages

For every directory that contains `.py` files or subdirectories, generate an `overview.mdx`:

```mdx
---
title: "<DIRECTORY_DISPLAY_NAME>"
sidebarTitle: "Overview"
description: "<DESCRIPTION>"
---

| Example | Description |
|---------|-------------|
| [<LINK_TEXT>](<URL>) | <DESCRIPTION> |
...
```

Rules for overview tables:
- Link text: Use the page's sidebarTitle (if set) or the title part before ` - `. Max 40 characters.
- NEVER use a sentence as link text. If the title is a sentence, use the sidebarTitle or derive from filename.
- Description: Use the page's description field. Must end with period.
- NEVER use descriptions that just repeat the link text (like `"Debug."` for a link called `"Debug"`)
- Sort alphabetically, but numbered entries (01, 02, ...) come first in number order

---

## Step 2: Restructure docs.json Sidebar

Replace the ENTIRE Examples tab in `docs/docs.json` → `navigation.tabs[4]`. Keep all other tabs unchanged.

### Structure Rules
- Each sub-section is a collapsible group: `{"group": "Name", "pages": [...]}`
- Each group starts with `overview` page, then remaining pages alphabetically
- Page paths: relative to `docs/`, no `.mdx` extension, forward slashes
- Some directories are merged into a single sidebar group (see below)

### The Hierarchy

```json
{
  "tab": "Examples",
  "groups": [
    {
      "group": "Examples",
      "pages": [
        "examples/overview",
        {
          "group": "Quickstart",
          "pages": ["examples/quickstart/overview", << all other .mdx files in examples/quickstart/ alphabetically >>]
        }
      ]
    },
    {
      "group": "Primitives",
      "pages": [
        {
          "group": "Agents",
          "pages": [
            "examples/agents/overview",
            {"group": "Getting Started", "pages": ["examples/agents/quickstart/overview", "<< rest of agents/quickstart/ >>"]},
            {"group": "Input & Output", "pages": ["examples/agents/input-output/overview", "<< rest >>"]},
            {"group": "Tools", "pages": ["examples/agents/tools/overview", "<< rest of agents/tools/ >>", "<< agents/dependencies/ pages (excluding overview) >>"]},
            {"group": "State & Session", "pages": ["examples/agents/state-and-session/overview", "<< rest >>"]},
            {"group": "Knowledge", "pages": ["examples/agents/knowledge/overview", "<< rest >>"]},
            {"group": "Guardrails", "pages": ["examples/agents/guardrails/overview", "<< rest >>"]},
            {"group": "Human in the Loop", "pages": ["examples/agents/human-in-the-loop/overview", "<< rest >>", "<< agents/approvals/ pages (excluding overview) >>"]},
            {"group": "Multimodal", "pages": ["examples/agents/multimodal/overview", "<< rest >>"]},
            {"group": "Hooks & Context", "pages": ["examples/agents/hooks/overview", "<< rest of hooks/ >>", "<< agents/context-management/ pages (excluding overview) >>"]},
            {"group": "Advanced", "pages": ["examples/agents/advanced/overview", "<< rest of advanced/ >>", "<< agents/memory-and-learning/ pages (excluding overview) >>", "<< agents/reasoning/ pages (excluding overview) >>", "<< agents/skills/ pages (excluding overview, recurse subdirs) >>"]}
          ]
        },
        {
          "group": "Teams",
          "pages": [
            "examples/teams/overview",
            {"group": "Getting Started", "pages": ["examples/teams/quickstart/overview", "<< rest of quickstart/ >>", "<< caching/ pages (excluding overview) >>"]},
            {"group": "Modes", "pages": ["examples/teams/modes/overview (or first sub-overview)", "<< all pages from modes/ subdirs >>"]},
            {"group": "Structured I/O", "pages": ["examples/teams/structured-input-output/overview", "<< rest >>"]},
            {"group": "Guardrails", "pages": ["examples/teams/guardrails/overview", "<< rest >>"]},
            {"group": "Human in the Loop", "pages": ["examples/teams/human-in-the-loop/overview", "<< rest >>"]},
            {"group": "Knowledge & RAG", "pages": ["examples/teams/knowledge/overview", "<< rest of knowledge/ >>", "<< distributed-rag/ pages (excluding overview) >>", "<< search-coordination/ pages (excluding overview) >>"]},
            {"group": "Learning & Memory", "pages": ["examples/teams/learning/overview", "<< rest of learning/ >>", "<< memory/ pages (excluding overview) >>"]},
            {"group": "State & Session", "pages": ["examples/teams/state/overview", "<< rest of state/ >>", "<< session/ pages (excluding overview) >>"]},
            {"group": "Tools & Hooks", "pages": ["examples/teams/tools/overview", "<< rest of tools/ >>", "<< hooks/ pages (excluding overview) >>"]},
            {"group": "Advanced", "pages": ["examples/teams/task-mode/overview", "<< all pages from: streaming/, metrics/, run-control/, context-compression/, context-management/, dependencies/, other/, reasoning/, multimodal/, task-mode/ (excluding overviews) >>"]}
          ]
        },
        {
          "group": "Workflows",
          "pages": [
            "examples/workflows/overview",
            {"group": "Getting Started", "pages": ["examples/workflows/basic-workflows/overview (or first sub-overview)", "<< rest, recurse subdirs >>"]},
            {"group": "Execution Patterns", "pages": ["examples/workflows/conditional-execution/overview", "<< rest recurse >>", "<< loop-execution/ pages (excluding overview) recurse >>", "<< parallel-execution/ pages (excluding overview) recurse >>"]},
            {"group": "Branching & Routing", "pages": ["examples/workflows/conditional-branching/overview", "<< rest recurse >>", "<< cel-expressions/ pages (excluding overview) recurse >>"]},
            {"group": "Advanced", "pages": ["examples/workflows/advanced-concepts/overview (or first sub-overview)", "<< rest recurse >>"]}
          ]
        }
      ]
    },
    {
      "group": "Context",
      "pages": [
        {
          "group": "Storage",
          "pages": [
            "examples/storage/overview",
            "<< For each subdirectory (postgres, mongo, sqlite, mysql, redis, dynamodb, in-memory, json-db, surrealdb, singlestore, firestore, gcs, examples): create a collapsible sub-group named after the backend, containing overview + all pages >>"
          ]
        },
        {
          "group": "Knowledge",
          "pages": [
            "examples/knowledge/overview",
            "<< For each subdirectory (quickstart, vector-db, embedders, readers, chunking, filters, search-type, protocol, cloud, os, custom-retriever): create a sub-group >>"
          ]
        },
        {
          "group": "Memory",
          "pages": [
            "examples/memory/overview",
            "<< top-level .mdx files >>",
            "<< For each subdirectory: create a sub-group >>"
          ]
        },
        {
          "group": "Learning",
          "pages": [
            "examples/learning/overview",
            "<< For each subdirectory: create a sub-group >>"
          ]
        }
      ]
    },
    {
      "group": "Models",
      "pages": [
        "examples/models/overview",
        {"group": "OpenAI", "pages": ["<< sub-groups for openai/chat/ and openai/responses/ >>"]},
        {"group": "Anthropic", "pages": ["<< all anthropic pages, sub-group for skills/ >>"]},
        {"group": "Google", "pages": ["<< sub-group for gemini/ >>"]},
        {
          "group": "Open Source",
          "pages": [
            "<< sub-group per provider: groq, deepseek, mistral, together, fireworks, cohere, meta, huggingface >>"
          ]
        },
        {
          "group": "Enterprise",
          "pages": [
            "<< sub-group per provider: aws, azure, vertexai, ibm, nvidia, cerebras, xai >>"
          ]
        },
        {
          "group": "Local",
          "pages": [
            "<< sub-group per provider: ollama, vllm, lmstudio, llama-cpp >>"
          ]
        },
        {
          "group": "More Providers",
          "pages": [
            "<< sub-group per remaining provider directory: aimlapi, cerebras-openai, clients, cometapi, dashscope, deepinfra, internlm, langdb, litellm, litellm-openai, moonshot, n1n, nebius, neosantara, nexus, openrouter, perplexity, portkey, requesty, sambanova, siliconflow, vercel >>"
          ]
        }
      ]
    },
    {
      "group": "Tools",
      "pages": [
        "examples/tools/overview",
        {"group": "MCP", "pages": ["examples/tools/mcp/overview", "<< rest of mcp/ including subdirs >>"]},
        {"group": "Custom Tools", "pages": ["examples/tools/tool-decorator/overview", "<< rest of tool-decorator/ >>"]},
        {"group": "Tool Hooks", "pages": ["examples/tools/tool-hooks/overview", "<< rest of tool-hooks/ >>"]},
        {
          "group": "Search & Web",
          "pages": ["<< individual tool .mdx files matching: baidusearch, bravesearch, duckduckgo, exa, firecrawl, hackernews, jinareader, linkup, newspaper, newspaper4k, reddit, scrapegraph, searxng, serpapi, serper, spider, tavily, trafilatura, web, webbrowser, websearch >>"]
        },
        {
          "group": "Data & Analytics",
          "pages": ["<< arxiv, csv, custom-api, duckdb, file, file-generation, financial-datasets, google-bigquery, googlesheets, knowledge-tool, neo4j, openbb, pandas, postgres, pubmed, redshift, sql, wikipedia, yfinance, youtube >>"]
        },
        {
          "group": "Communication",
          "pages": ["<< calcom, discord, email, gmail, google-drive, googlecalendar, notion, resend, slack, telegram, todoist, trello, twilio, webex, whatsapp, zendesk, zoom >>"]
        },
        {
          "group": "AI & Media",
          "pages": ["<< brandfetch, calculator, cartesia, dalle, desi-vocal, elevenlabs, fal, giphy, lumalabs, mlx-transcribe, models-lab, moviepy-video, opencv, replicate, spotify, unsplash, visualization >>"]
        },
        {
          "group": "Dev & Infrastructure",
          "pages": ["<< agentql, airflow, apify, aws-lambda, aws-ses, bitbucket, brightdata, browserbase, clickup, composio, confluence, crawl4ai, custom-tool-events, custom-tools, daytona, docker, e2b, evm, github, jira, linear, mcp-tools, mem0, multiple, nano-banana, openweather, oxylabs, parallel, python, python-function-as-tool, seltz, shell, shopify, sleep, tool-calls-accesing-agent, valyu, x, zep >>"]
        },
        {
          "group": "Other Tools",
          "pages": ["<< exceptions/ pages, models/ pages, other/ pages >>"]
        }
      ]
    },
    {
      "group": "More",
      "pages": [
        {
          "group": "Agent OS",
          "pages": ["examples/agent-os/overview", "<< top-level pages >>", "<< sub-group per subdirectory: advanced-demo, background-tasks, client, client-a2a, customize, dbs, integrations, interfaces, knowledge, mcp-demo, middleware, os-config, rbac, remote, scheduler, schemas, skills, tracing, workflow >>"]
        },
        {
          "group": "Reasoning",
          "pages": ["examples/reasoning/overview", "<< sub-group per subdirectory: agents, models, teams, tools >>"]
        },
        {
          "group": "Evals",
          "pages": ["examples/evals/overview", "<< sub-group per subdirectory: accuracy, agent-as-judge, performance, reliability >>"]
        },
        {
          "group": "Integrations",
          "pages": ["examples/integrations/overview", "<< sub-group per subdirectory: a2a, discord, memory, observability, rag, surrealdb >>"]
        },
        {
          "group": "Components",
          "pages": ["examples/components/overview", "<< top-level pages >>", "<< sub-group for workflows/ >>"]
        }
      ]
    }
  ]
}
```

IMPORTANT: Resolve ALL `<< >>` placeholders by enumerating .mdx files from the filesystem. Each page path is relative to `docs/` with no `.mdx` extension.

### Merged Groups

When directories are merged into a single sidebar group, update the "primary" overview page to include entries from ALL merged directories. The primary overview is the first directory listed.

Merged groups:
- **Agents > Tools**: `agents/tools/` + `agents/dependencies/`
- **Agents > Human in the Loop**: `agents/human-in-the-loop/` + `agents/approvals/`
- **Agents > Hooks & Context**: `agents/hooks/` + `agents/context-management/`
- **Agents > Advanced**: `agents/advanced/` + `agents/memory-and-learning/` + `agents/reasoning/` + `agents/skills/`
- **Teams > Getting Started**: `teams/quickstart/` + `teams/quickstart/caching/`
- **Teams > Knowledge & RAG**: `teams/knowledge/` + `teams/distributed-rag/` + `teams/search-coordination/`
- **Teams > Learning & Memory**: `teams/learning/` + `teams/memory/`
- **Teams > State & Session**: `teams/state/` + `teams/session/`
- **Teams > Tools & Hooks**: `teams/tools/` + `teams/hooks/`
- **Teams > Advanced**: `teams/task-mode/` + `teams/streaming/` + `teams/metrics/` + `teams/run-control/` + `teams/context-compression/` + `teams/context-management/` + `teams/dependencies/` + `teams/other/` + `teams/reasoning/` + `teams/multimodal/`

---

## Step 3: Update examples/overview.mdx

Replace `docs/examples/overview.mdx` with:

```mdx
---
title: Examples
description: "2000+ runnable examples covering agents, teams, workflows, 40+ models, 100+ tools, and 18 vector databases."
---
Runnable examples with inline source code and setup instructions. Every example maps 1:1 to a cookbook script.

## Quickstart

| Section | Description |
|---------|-------------|
| [Quickstart](/examples/quickstart/overview) | Build your first agent with tools, structured output, memory, knowledge, guardrails, and more. |

## Primitives

| Section | Description |
|---------|-------------|
| [Agents](/examples/agents/overview) | Agent patterns: input/output, tools, state, knowledge, guardrails, multimodal, and more. |
| [Teams](/examples/teams/overview) | Multi-agent coordination: modes, structured I/O, human-in-the-loop, knowledge, and more. |
| [Workflows](/examples/workflows/overview) | Workflow orchestration: sequential, conditional, parallel, loops, branching, and CEL expressions. |

## Context

| Section | Description |
|---------|-------------|
| [Storage](/examples/storage/overview) | Database backends: PostgreSQL, MongoDB, SQLite, MySQL, Redis, DynamoDB, and more. |
| [Knowledge](/examples/knowledge/overview) | Knowledge bases: vector databases, embedders, readers, chunking, filters, and search. |
| [Memory](/examples/memory/overview) | User memory persistence across runs, sessions, and agents. |
| [Learning](/examples/learning/overview) | Agents that learn, adapt, and improve from interactions. |

## Models

| Section | Description |
|---------|-------------|
| [Models](/examples/models/overview) | 40+ LLM providers: OpenAI, Anthropic, Google, open source, enterprise, and local models. |

## Tools

| Section | Description |
|---------|-------------|
| [Tools](/examples/tools/overview) | 100+ built-in tools: MCP, custom tools, search, data, communication, AI/media, and dev tools. |

## More

| Section | Description |
|---------|-------------|
| [Agent OS](/examples/agent-os/overview) | AgentOS deployment: clients, interfaces, databases, middleware, scheduling, and tracing. |
| [Reasoning](/examples/reasoning/overview) | Chain-of-thought reasoning with agents, models, tools, and teams. |
| [Evals](/examples/evals/overview) | Evaluation patterns: accuracy, agent-as-judge, performance, and reliability. |
| [Integrations](/examples/integrations/overview) | External platforms: observability, RAG integrations, Discord, and more. |
| [Components](/examples/components/overview) | Save and load agents, teams, and workflows to/from databases. |
```

---

## Step 4: Quality Fixes

Apply these fixes across ALL generated .mdx files:

### 4a. Fix typo
Replace ALL occurrences of `virual` with `virtual`.

### 4b. Fix cd paths
In "Run the Example" bash blocks, the cd command must include `cookbook/`:
- Correct: `cd agno/cookbook/00_quickstart`
- Wrong: `cd agno/00_quickstart`

Pattern: if `cd agno/` is followed by a digit, insert `cookbook/` after `agno/`.

### 4c. No duplicate frontmatter keys
Each frontmatter key must appear exactly once. If `sidebarTitle` appears twice, keep the first.

### 4d. Frontmatter separator
There must be a blank line between the closing `---` of frontmatter and the content that follows. Never `---```python` or `---This example`.

### 4e. No trailing periods in link text
Overview table link text must not end with a period.

### 4f. No sentence-style link text
If link text starts with "Example", "Demonstrates", "Shows how", "This example", derive from the page's sidebarTitle or filename slug instead.

### 4g. No lazy descriptions in overview tables
If a description column just repeats the link text (like `"Debug."` for link `"Debug"`), read the target page's actual description and use that instead.

---

## Step 5: Cleanup

1. Delete any .mdx files under `docs/examples/` that don't have a corresponding cookbook .py file (except overview.mdx files)
2. Delete `docs/examples/demo/` entirely if it exists (demo directory is not synced)
3. Verify no broken internal links in docs.json (every page path must have a corresponding .mdx file)

---

## Reference: Example Pages

### Rich docstring page (quickstart/agent-with-structured-output.mdx):
```mdx
---
title: "Agent with Structured Output - Finance Agent with Typed Responses"
sidebarTitle: "Agent with Structured Output"
description: "This example shows how to get structured, typed responses from your agent."
---
This example shows how to get structured, typed responses from your agent. Instead of free-form text, you get a Pydantic model you can trust.

```python
"""
Agent with Structured Output - Finance Agent with Typed Responses
==================================================================
This example shows how to get structured, typed responses from your agent.
Instead of free-form text, you get a Pydantic model you can trust.
...
"""
from agno.agent import Agent
...
```

## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/00_quickstart

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python agent_with_structured_output.py
```
```

### Minimal docstring page (agents/advanced/agent-serialization.mdx):
```mdx
---
title: "Agent Serialization"
sidebarTitle: "Serialization"
description: "Serialize and deserialize agents using to_dict/from_dict and save/load with a database."
---
```python
"""
Agent Serialization
=============================

Agent Serialization.
"""
from agno.agent import Agent
...
```

## Run the Example
```bash
# Clone and setup repo
git clone https://github.com/agno-agi/agno.git
cd agno/cookbook/02_agents/14_advanced

# Create and activate virtual environment
./scripts/demo_setup.sh
source .venvs/demo/bin/activate

python agent_serialization.py
```
```

Note: The minimal docstring page has NO intro paragraph (because the docstring only repeats the title), a context-aware sidebarTitle ("Serialization" not "Agent Serialization" because it's under the agents section), and a description derived from the code content (uses to_dict/from_dict → serialize/deserialize description).

### No-subtitle page (quickstart/agent-with-tools.mdx):
```mdx
---
title: "Agent with Tools - Finance Agent"
sidebarTitle: "Agent with Tools"
description: "Your first Agno agent: a data-driven financial analyst that retrieves market data, computes key metrics, and delivers concise insights."
---
```python
"""
Agent with Tools - Finance Agent
=================================
Your first Agno agent: a data-driven financial analyst that retrieves
market data, computes key metrics, and delivers concise insights.
...
"""
...
```
```

Note: No intro paragraph here because the first sentence of the docstring IS the description (identical → omitted to avoid duplication).

---

## Verification Checklist

After completion, verify:
1. `docs/examples/demo/` does not exist
2. `grep -r "virual" docs/examples/` returns 0 matches
3. No `cd agno/<digit>` patterns exist (all have `cookbook/`)
4. No duplicate `sidebarTitle` in any frontmatter
5. No `---` directly followed by content (missing separator)
6. sidebarTitle is context-aware: pages under `agents/` strip "Agent " prefix
7. Overview table link text is ≤ 40 chars and doesn't start with "Example"
8. Every page in docs.json has a corresponding .mdx file
9. Every .mdx file (non-overview) has a corresponding cookbook .py file
10. No trailing periods in overview table link text
````

---

## Cookbook → Docs Directory Mapping Reference

| Cookbook Directory | Docs Directory | Sidebar Group |
|---|---|---|
| `cookbook/00_quickstart/` | `docs/examples/quickstart/` | Examples > Quickstart |
| `cookbook/02_agents/01_quickstart/` | `docs/examples/agents/quickstart/` | Primitives > Agents > Getting Started |
| `cookbook/02_agents/02_input_output/` | `docs/examples/agents/input-output/` | Primitives > Agents > Input & Output |
| `cookbook/02_agents/03_context_management/` | `docs/examples/agents/context-management/` | (merged into Agents > Hooks & Context) |
| `cookbook/02_agents/04_tools/` | `docs/examples/agents/tools/` | Primitives > Agents > Tools |
| `cookbook/02_agents/05_state_and_session/` | `docs/examples/agents/state-and-session/` | Primitives > Agents > State & Session |
| `cookbook/02_agents/06_memory_and_learning/` | `docs/examples/agents/memory-and-learning/` | (merged into Agents > Advanced) |
| `cookbook/02_agents/07_knowledge/` | `docs/examples/agents/knowledge/` | Primitives > Agents > Knowledge |
| `cookbook/02_agents/08_guardrails/` | `docs/examples/agents/guardrails/` | Primitives > Agents > Guardrails |
| `cookbook/02_agents/09_hooks/` | `docs/examples/agents/hooks/` | Primitives > Agents > Hooks & Context |
| `cookbook/02_agents/10_human_in_the_loop/` | `docs/examples/agents/human-in-the-loop/` | Primitives > Agents > Human in the Loop |
| `cookbook/02_agents/11_approvals/` | `docs/examples/agents/approvals/` | (merged into Agents > Human in the Loop) |
| `cookbook/02_agents/12_multimodal/` | `docs/examples/agents/multimodal/` | Primitives > Agents > Multimodal |
| `cookbook/02_agents/13_reasoning/` | `docs/examples/agents/reasoning/` | (merged into Agents > Advanced) |
| `cookbook/02_agents/14_advanced/` | `docs/examples/agents/advanced/` | Primitives > Agents > Advanced |
| `cookbook/02_agents/15_dependencies/` | `docs/examples/agents/dependencies/` | (merged into Agents > Tools) |
| `cookbook/02_agents/16_skills/` | `docs/examples/agents/skills/` | (merged into Agents > Advanced) |
| `cookbook/03_teams/` | `docs/examples/teams/` | Primitives > Teams |
| `cookbook/04_workflows/` | `docs/examples/workflows/` | Primitives > Workflows |
| `cookbook/05_agent_os/` | `docs/examples/agent-os/` | More > Agent OS |
| `cookbook/06_storage/` | `docs/examples/storage/` | Context > Storage |
| `cookbook/07_knowledge/` | `docs/examples/knowledge/` | Context > Knowledge |
| `cookbook/08_learning/` | `docs/examples/learning/` | Context > Learning |
| `cookbook/09_evals/` | `docs/examples/evals/` | More > Evals |
| `cookbook/10_reasoning/` | `docs/examples/reasoning/` | More > Reasoning |
| `cookbook/11_memory/` | `docs/examples/memory/` | Context > Memory |
| `cookbook/90_models/` | `docs/examples/models/` | Models |
| `cookbook/91_tools/` | `docs/examples/tools/` | Tools |
| `cookbook/92_integrations/` | `docs/examples/integrations/` | More > Integrations |
| `cookbook/93_components/` | `docs/examples/components/` | More > Components |

## Tool Categorization Reference

When placing individual tool .mdx files into sidebar groups under Tools, use this categorization:

**Search & Web**: baidusearch, bravesearch, duckduckgo, exa, firecrawl, hackernews, jinareader, linkup, newspaper, newspaper4k, reddit, scrapegraph, searxng, serpapi, serper, spider, tavily, trafilatura, web, webbrowser, websearch

**Data & Analytics**: arxiv, csv, custom-api, duckdb, file, file-generation, financial-datasets, google-bigquery, googlesheets, knowledge-tool, neo4j, openbb, pandas, postgres, pubmed, redshift, sql, wikipedia, yfinance, youtube

**Communication**: calcom, discord, email, gmail, google-drive, googlecalendar, notion, resend, slack, telegram, todoist, trello, twilio, webex, whatsapp, zendesk, zoom

**AI & Media**: brandfetch, calculator, cartesia, dalle, desi-vocal, elevenlabs, fal, giphy, lumalabs, mlx-transcribe, models-lab, moviepy-video, opencv, replicate, spotify, unsplash, visualization

**Dev & Infrastructure**: agentql, airflow, apify, aws-lambda, aws-ses, bitbucket, brightdata, browserbase, clickup, composio, confluence, crawl4ai, custom-tool-events, custom-tools, daytona, docker, e2b, evm, github, jira, linear, mcp-tools, mem0, multiple, nano-banana, openweather, oxylabs, parallel, python, python-function-as-tool, seltz, shell, shopify, sleep, tool-calls-accesing-agent, valyu, x, zep

**Other Tools**: exceptions/, models/, other/ subdirectories

New tools not in these lists should be categorized by their function. When in doubt, put them in Dev & Infrastructure.

## Model Provider Categorization Reference

**Top-level (own group)**: openai, anthropic, google

**Open Source**: groq, deepseek, mistral, together, fireworks, cohere, meta, huggingface

**Enterprise**: aws, azure, vertexai, ibm, nvidia, cerebras, xai

**Local**: ollama, vllm, lmstudio, llama-cpp

**More Providers**: everything else (aimlapi, cerebras-openai, clients, cometapi, dashscope, deepinfra, internlm, langdb, litellm, litellm-openai, moonshot, n1n, nebius, neosantara, nexus, openrouter, perplexity, portkey, requesty, sambanova, siliconflow, vercel)

New providers should be added to the appropriate category. When in doubt, put them in More Providers.
