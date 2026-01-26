# CLAUDE.md - Agno Documentation Style Guide

## Philosophy

Agno docs are direct, concrete, and professional. No marketing fluff. No AI-sounding prose. Every sentence earns its place.

We cover a massive surface area. Analogies and commentary add cognitive load without adding understanding. Be direct.

## Before Writing Any Page

Define these four things before you write:

1. **What is this page about?** (one sentence)
2. **What does the user need to do?** (the code)
3. **What decisions might they face?** (tables)
4. **Where do they go next?** (links)

If you can't answer these clearly, the page will ramble.

## Page Structure

Every page should follow this pattern:

1. **One-line description** - What this page covers (in frontmatter and opening line)
2. **Code first** - Show the pattern immediately
3. **Explain after** - Brief context only if needed
4. **Tables for decisions** - "When to use X vs Y" belongs in a table, not prose
5. **Links at bottom** - "Next steps" or "Developer Resources"
````
❌ Long explanation of what agents are, their history, why they matter...
   then eventually some code.

✅ Code example showing the pattern.
   Brief explanation of what it does.
   Table of options/decisions.
   Links to related pages.
````

## Context Hygiene

**Start fresh for each section.** Don't let one domain bleed into another. If you're writing Tools docs, don't bring patterns or terminology from Learning Machine docs. Each section should be self-contained.

## Core Rules

### 1. Lead with code

Show the pattern first, explain after. Users are scanning for how to do something.
````
❌ "To create an agent with structured output, you need to define a Pydantic
   model that represents the schema you want. Then you pass this to the
   output_schema parameter. Here's how:"
   [code]

✅ [code]
   "The agent returns a `StockAnalysis` object instead of free-form text."
````

### 2. One concept per section

Don't bundle unrelated ideas. If you're explaining structured output, don't also explain tools in the same section.

### 3. Tables over prose for comparisons
````
❌ "You might want to use structured input when you need validation, but
   string input is fine for prototyping. If you're building a production
   system, structured input gives you type safety..."

✅ | Use Case | Input Type |
   |----------|------------|
   | Prototyping, chat | String |
   | Production, validation needed | Pydantic model |
````

### 4. Descriptions must be specific

Every page's `description` field should describe what the page covers, not say "Learn how to..."
````
❌ "Learn how to run your Agents and process their output."
✅ "Execute agents with Agent.run() and process their output."

❌ "Learn how to build Agents with Agno."
✅ "Start simple: a model, tools, and instructions."

❌ "Learn about Agno Agents and how they work."
✅ "AI programs where a language model controls the flow of execution."
````

### 5. No em dashes

Em dashes (—) are an AI tell. Use periods or rewrite.
````
❌ "No data leaves your environment—ideal for security-conscious teams."
✅ "No data leaves your environment. Ideal for security-conscious teams."

❌ "Each Agent maintains its own history—switching users won't mix context."
✅ "Each Agent maintains its own history. Switching users won't mix context."
````

### 6. No comma splices

Two independent clauses joined by a comma need a period or semicolon.
````
❌ "Run it on your own machine, don't take these numbers at face value."
✅ "Run it on your own machine. Don't take these numbers at face value."

❌ "Stateless, horizontal scalability isn't optional, it's the baseline."
✅ "Stateless, horizontal scalability isn't optional. It's the baseline."
````

### 7. Cut the commentary

Analogies and editorializing waste space.
````
❌ "Unstructured I/O is like shouting instructions and getting a rough
   answer back that must be further worked upon. It works, but it's messy."

✅ "String input works for prototyping and chat. Add structure when you
   need validation."
````

### 8. Specific over generic
````
❌ "Use a better model for improved results."
✅ "Use Claude Opus 4.5 for better prose quality."

❌ "You can customize various settings."
✅ "Set `temperature=0` for deterministic output."
````

### 9. Tighten wordy phrases

| Before | After |
|--------|-------|
| "Here's how they work:" | "The execution flow:" |
| "For more information see the X documentation." | "See X." |
| "You can also run the agent asynchronously" | "Run asynchronously with `arun()`" |
| "The `input` parameter is the input to send to the agent. It can be..." | "The `input` parameter accepts:" |
| "If this is your first time using Agno, you can start here" | "New to Agno? Start with the quickstart." |
| "After getting familiarized with" | "After getting familiar with" |
| "This example shows how to..." | [Remove - let the code speak] |
| "Here's how it looks:" | [Remove - show the visual] |
| "It's important to note that" | [Remove - just state it] |
| "Basically" / "Essentially" | [Remove] |

### 10. Link lists: no "View the..." pattern
````markdown
❌ Developer Resources
- View the [Agent reference](/reference/agents/agent)
- View the [RunOutput schema](/reference/agents/run-response)

✅ Developer Resources
- [Agent reference](/reference/agents/agent)
- [RunOutput schema](/reference/agents/run-response)
````

### 11. Q&A lists → Tables
````markdown
❌ Common questions:
- **How do I run my agent?** -> See [running agents](/path).
- **How do I debug my agent?** -> See [debugging agents](/path).

✅ | Task | Guide |
   |------|-------|
   | Run agents | [Running agents](/path) |
   | Debug agents | [Debugging agents](/path) |
````

### 12. Card descriptions: vary them
````
❌ "Learn how to build your first agent."
❌ "Learn how to run your agents."
❌ "Learn how to debug your agents."

✅ "Create your first agent with tools and instructions."
✅ "Execute agents and handle responses."
✅ "Troubleshoot and inspect agent behavior."
````

## Words and Phrases to Avoid

| Word/Phrase | Why | Use Instead |
|-------------|-----|-------------|
| "Learn how to..." | Generic, passive | Specific action statement |
| "Seamlessly" | AI tell, meaningless | Describe actual behavior |
| "Let's explore" | Filler | [Remove, just explain] |
| "It's worth noting" | Filler | [Remove, just state it] |
| "Basically" / "Essentially" | Filler | [Remove] |
| "Beautiful" / "Elegant" | Subjective | Describe function |
| "Incredible" / "Powerful" | Hyperbolic | State facts |
| "Leading framework" | Unsubstantiated | State facts |
| "Happy building!" | Unnecessary | End with links |
| "Here's how it looks:" | Filler | [Remove] |
| Em dashes (—) | AI tell | Periods or rewrite |

## Capitalization & Terminology

| Wrong | Right |
|-------|-------|
| id | ID |
| pydantic | Pydantic |
| vector db | vector database |
| 3rd party | third-party |
| Hackernews | HackerNews |
| higher level (adjective) | higher-level |
| multi turn | multi-turn |
| back-and-forth conversations | multi-turn conversations |

## The Three Pillars

Use consistently when describing Agno:

| Layer | Verb | Description |
|-------|------|-------------|
| **SDK** | Build | Agents, teams, and workflows with memory, knowledge, guardrails, and 100+ integrations |
| **Runtime** | Run | Your system in production with a stateless, secure FastAPI backend |
| **Control Plane** | Manage | Monitor your system using the AgentOS UI |

## Code Examples

- No verbose comment blocks (`# ************* Create Agent *************`)
- Minimal inline comments - code should be self-explanatory
- Keep examples consistent across related pages
- Show the minimal working example first, then variations

## Page Templates

### Overview Page
````markdown
---
title: What are X?
description: "One sentence defining X concretely."
---

**Bold one-liner expanding on the definition.**

[Code example - the simplest working version]

## Key Concepts

| Concept | Description |
|---------|-------------|
| A | What A does |
| B | What B does |

## Learn How To

<CardGroup cols={3}>
  <Card title="Build X" href="/x/building">
    Create your first X with [specifics]
  </Card>
  ...
</CardGroup>

## Developer Resources

- [X reference](/reference/x)
- [X examples](/cookbook/x)
````

### Tutorial/Guide Page
````markdown
---
title: Building X
description: "What you'll build and the key pattern."
---

[Code example - complete working version]

## How It Works

1. Step one
2. Step two
3. Step three

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `foo` | `true` | What foo does |

## Next Steps

| Task | Guide |
|------|-------|
| Do Y | [Y guide](/y) |
````

### Usage/Example Page
````markdown
---
title: X with Y
description: "What this combination achieves."
---

<Steps>
  <Step title="Create file">
```python
    [code]
```
  </Step>
  <Step title="Install deps">
```bash
    uv pip install ...
```
  </Step>
  <Step title="Run">
```bash
    python file.py
```
  </Step>
</Steps>
````

## Validation Commands
````bash
# Check for broken links
mintlify broken-links

# Preview locally
mintlify dev
````