# CLAUDE.md - Agno Documentation Style Guide

## Voice

Agno docs are direct, concrete, and professional. No marketing fluff. No AI-sounding prose.

## Core Rules

### 1. Descriptions must be specific
Every page's `description` field should describe what the page covers, not say "Learn how to..."
```
❌ "Learn how to run your Agents and process their output."
✅ "Execute agents with Agent.run() and process their output."

❌ "Learn how to build Agents with Agno."
✅ "Start simple: a model, tools, and instructions."

❌ "Learn about Agno Agents and how they work."
✅ "AI programs where a language model controls the flow of execution."
```

### 2. No em dashes
Em dashes (—) are an AI tell. Use periods or rewrite.
```
❌ "No data leaves your environment—ideal for security-conscious teams."
✅ "No data leaves your environment. Ideal for security-conscious teams."

❌ "Each Agent maintains its own history—switching users won't mix context."
✅ "Each Agent maintains its own history. Switching users won't mix context."
```

### 3. No comma splices
Two independent clauses joined by a comma need a period.
```
❌ "Run it on your own machine, don't take these numbers at face value."
✅ "Run it on your own machine. Don't take these numbers at face value."

❌ "Stateless, horizontal scalability isn't optional, it's the baseline."
✅ "Stateless, horizontal scalability isn't optional. It's the baseline."
```

### 4. Tighten wordy phrases

| Before | After |
|--------|-------|
| "Here's how they work:" | "The execution flow:" |
| "For more information see the X documentation." | "See X for more details." |
| "You can also run the agent asynchronously" | "Run the agent asynchronously" |
| "The `input` parameter is the input to send to the agent. It can be..." | "The `input` parameter can be..." |
| "If this is your first time using Agno, you can start here" | "New to Agno? Start with the quickstart." |
| "After getting familiarized with" | "After getting familiar with" |
| "View the X" / "View X" | Just link: "X" |
| "This example shows how to..." | Remove or tighten |
| "Here's how it looks:" | Remove (let the visual speak) |

### 5. Link lists: no "View the..." pattern
```markdown
❌ Developer Resources
- View the [Agent reference](/reference/agents/agent)
- View the [RunOutput schema](/reference/agents/run-response)

✅ Developer Resources
- [Agent reference](/reference/agents/agent)
- [RunOutput schema](/reference/agents/run-response)
```

### 6. Q&A lists → Tables
```markdown
❌ Common questions:
- **How do I run my agent?** -> See [running agents](/path).
- **How do I debug my agent?** -> See [debugging agents](/path).

✅ | Task | Guide |
   |------|-------|
   | Run agents | [Running agents](/path) |
   | Debug agents | [Debugging agents](/path) |
```

### 7. Card descriptions: vary them
```
❌ "Learn how to build your first agent."
❌ "Learn how to run your agents."
❌ "Learn how to debug your agents."

✅ "Create your first agent with tools and instructions."
✅ "Execute agents and handle responses."
✅ "Troubleshoot and inspect agent behavior."
```

### 8. Section intros: get to the point
```
❌ "The `Agent.run()` function runs the agent and returns the output as a `RunOutput` object, or as a stream of `RunOutputEvent` objects when `stream=True`. For example:"

✅ "`Agent.run()` returns a `RunOutput` object, or a stream of `RunOutputEvent` objects when `stream=True`:"
```

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

## Words to Avoid

| Word/Phrase | Why | Use Instead |
|-------------|-----|-------------|
| "Agent Engineering" | Not a recognized term | "multi-agent systems" |
| "beautiful" / "elegant" | Subjective | Describe function |
| "incredible" / "extreme" / "powerful" | Hyperbolic | Concrete facts |
| "leading framework" | Unsubstantiated claim | State facts |
| "Happy building!" | Unnecessary | End with links |
| "Learn how to..." (descriptions) | Generic | Specific statement |
| "Here's how it looks:" | Filler | Remove |
| "For more information see..." | Wordy | "See X for details." |

## The Three Pillars (use consistently)

| Layer | Description |
|-------|-------------|
| **Framework** | **Build** agents, teams, and workflows with memory, knowledge, guardrails, and 100+ integrations |
| **AgentOS Runtime** | **Run** your system in production with a stateless, secure FastAPI backend |
| **Control Plane** | **Manage** and monitor your system using the AgentOS UI |

## Code Examples

- No verbose comment blocks (`# ************* Create Agent *************`)
- Minimal inline comments
- Keep examples consistent across pages (intro, quickstart, README should match)

## Page Structure Patterns

### Overview pages
1. Bold one-liner defining the concept
2. Bullet list of key components
3. Tip for newcomers
4. Cards linking to guides
5. "Developer Resources" links

### Usage/Example pages
1. One-sentence intro
2. `<Steps>` with code
3. Optional "Key Concepts" or "How It Works" section

### Reference pages
1. Brief intro (1-2 sentences)
2. Code example
3. Tables for parameters/events
4. Links to related docs
```
