# CLAUDE.md — Agno Docs

Instructions for Claude Code when working on this documentation site.

---

## Repository Structure

```
agno-docs/
├── *.mdx                    # Documentation pages (Mintlify format)
├── get-started/             # Getting started guides
├── basics/                  # Core concepts documentation
├── examples/                # Example documentation
├── reference-api/           # API reference (auto-generated)
├── _snippets/               # Reusable content snippets
├── agno/                    # Symlinked Agno framework repo (gitignored)
│   ├── cookbook/            # Code examples and patterns
│   ├── libs/agno/agno/      # Framework source code
│   └── README.md            # Framework overview
├── specs/                   # Symlinked design documents (gitignored)
└── docs.json                # Mintlify configuration
```

---

## Symlinked Resources

Two directories are symlinked from external repos and gitignored. They are available locally for reference:

| Directory | Purpose |
|-----------|---------|
| `agno/` | The Agno framework codebase. Use `agno/cookbook/` for code examples. Read `agno/README.md` for framework overview. |
| `specs/` | Design documents for upcoming features. Follow spec-first development when documenting new features. |

---

## Working Memory

Maintain continuity across sessions using these files in `specs/docs/`:

| File | Purpose |
|------|---------|
| `claude_memory.md` | Persistent thoughts, patterns, learnings. Write new discoveries here. |
| `prompts.md` | Reusable prompts for documentation tasks. Add new useful prompts here. |

**Self-instructions:**
- When you discover something new about the codebase or style, add it to `claude_memory.md`
- When you create a useful prompt, add it to `prompts.md`
- Review these files at the start of documentation sessions

---

## Writing Style

**Reference files:** `introduction.mdx` and `get-started/` pages are the style guide.

### Tone

- **Lead with what it is, not what users want.** "Agno is a framework..." not "Companies want to build..."
- **State facts, not claims.** "529× faster" not "the leading framework"
- **Be direct, not defensive.** "Build an Agent that..." not "Instead of a toy demo..."
- **Concrete over vague.** "Runs entirely in your cloud" not "incredible performance"
- **Respect competitors.** Show benchmarks neutrally, let readers decide.

### Formatting

- Keep prose concise and direct
- Avoid em-dashes. Use hyphens sparingly if needed
- No emojis
- Use tables for comparisons
- Use code blocks with language hints (`python`, `bash`, etc.)
- Use Mintlify components (`<Steps>`, `<Tip>`, `<Check>`, `<Frame>`, `<CodeGroup>`) appropriately
- Descriptions under 160 characters, factual, not promotional

**Frontmatter format:**
```yaml
---
title: Page Title
description: "Brief description of the page content."
keywords: [keyword1, keyword2]
mode: "wide"
---
```

---

## Key Terminology

**Privacy is Agno's main differentiator.** Always mention prominently:
- "Runs entirely in your cloud"
- "No data leaves your environment"
- "Private by design"

**The Three Pillars** - use this consistent terminology:

| Layer | Description |
|-------|-------------|
| **Framework** | Build agents, teams, and workflows with memory, knowledge, guardrails, and 100+ integrations |
| **AgentOS Runtime** | Serve your system in production with a stateless, secure FastAPI backend |
| **Control Plane** | Test, monitor, and manage your system using the AgentOS UI |

---

## Code Examples

Keep code minimal and clean:
```python
# Good
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

agent = Agent(
    name="Support Agent",
    db=SqliteDb(db_file="agno.db"),
    add_history_to_context=True,
)

agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()
```

Avoid verbose comments and visual noise like `# ******** Section ********`.

---

## Running Locally

```bash
# Install Mintlify CLI
npm i -g mint

# Run the dev server
mint dev

# Update dependencies if issues occur
mint update
```

The site runs at `http://localhost:3333`.

---

## Finding Code Examples

Look in `agno/cookbook/` for code examples organized by topic:
- `00_getting_started/` — Basic examples
- `03_agents/` — Agent patterns
- `04_teams/` — Team patterns
- `05_workflows/` — Workflow patterns
- `15_learning/` — Learning system examples (golden standard)

When documenting features, check if cookbook examples exist first.

---

## Documenting New Features

1. **Check specs/** for design documents if documenting an upcoming feature
2. **Find cookbook examples** in `agno/cookbook/` to include working code
3. **Follow existing patterns** in similar documentation pages
4. **Update docs.json** if adding new pages to the navigation

---

## API Reference

The `reference-api/` folder contains auto-generated OpenAPI documentation. See `README.md` for instructions on regenerating it from a running AgentOS instance.

---

## Pull Requests

Keep PRs small and reviewable in 5-10 minutes:
- Maximum 3-4 pages per PR, or one section at a time
- Focus on a single logical change
- Don't bundle unrelated updates

---

## Words and Phrases to Avoid

| Avoid | Use Instead |
|-------|-------------|
| em-dashes (—) | hyphens sparingly |
| "beautiful" / "elegant" | describe function instead |
| "incredible" / "extreme" | concrete metrics |
| "leading framework" | state facts |
| "Happy building!" | end with actionable next steps |
| "Head over to..." | "Post on" / "Visit" |
| "Checkout" (verb) | "Check out" (two words) |
| KiB variants (Kib, kib) | KiB (consistent units) |

---

## Don't

- Don't use emojis in documentation
- Don't create documentation for features without checking for code examples first
- Don't add pages without updating `docs.json`
- Don't describe the same component twice on a page
- Don't repeat links that are already in the header
