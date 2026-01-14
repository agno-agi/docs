# Teams Section TODO

Issues found in `basics/teams/` documentation.

---

## Phase 1: Core Docs

### overview.mdx
- [ ] Line 69-70: "When should you use Teams?" repeated as header and first sentence - remove duplicate
- [ ] Line 73: Typo "becaues" → "because"
- [ ] Line 76: `## Guides` → `## Next`

### building-teams.mdx
- [ ] Line 16: `OpenAIChat` → `OpenAIResponses`
- [ ] Line 37, 77, 87, 114: Standardize model IDs to `gpt-5.2`
- [ ] Line 95: Remove verbose comment `################ STREAM RESPONSE #################`
- [ ] Line 100: Remove verbose comment `# ################ STREAM AND PRETTY PRINT #################`
- [ ] Line 105: "what is show" → "what is shown"

### running-teams.mdx
- [ ] Lines 50-65, 108, 177: `OpenAIChat` → `OpenAIResponses`, standardize model IDs

### debugging-teams.mdx
- [ ] Line 8: "an debug mode" → "a debug mode"
- [ ] Lines 34, 65: `OpenAIChat` → `OpenAIResponses`, standardize model IDs

### delegation.mdx
- [ ] Throughout: `OpenAIChat` → `OpenAIResponses` where appropriate
- [ ] Line 90: `gpt-4.5-preview` → standardize model ID
- [ ] Standardize all model IDs to `gpt-5.2` or `claude-sonnet-4-5`

---

## Phase 2: Examples (14 files)

### All examples need:
- [ ] Remove `touch filename.py` steps
- [ ] `pip install` → `uv pip install`
- [ ] "Install libraries" → "Install dependencies"
- [ ] `OpenAIChat` → `OpenAIResponses` for gpt models
- [ ] Standardize model IDs: `claude-sonnet-4-5` or `gpt-5.2`

### basic-flows/basic-team.mdx
- [ ] Remove touch step (line 21-24)
- [ ] Line 33, 50, 57, 65: `OpenAIChat` → `OpenAIResponses`, `gpt-5-mini` → `gpt-5.2`
- [ ] Line 90-93: `pip install` → `uv pip install`, "Install libraries" → "Install dependencies"

### basic-flows/basic-streaming.mdx
- [ ] Remove touch step
- [ ] Standardize models
- [ ] Fix install step

### basic-flows/stream-events.mdx
- [ ] Remove touch step
- [ ] Line 22-23: Fix imports - `from agno.agent.agent import Agent` → `from agno.agent import Agent`
- [ ] Line 23: `from agno.models.anthropic.claude import Claude` → `from agno.models.anthropic import Claude`
- [ ] Line 58: `claude-3-7-sonnet-latest` → `claude-sonnet-4-5`
- [ ] Standardize models, fix install step

### basic-flows/response-as-variable.mdx
- [ ] Remove touch step
- [ ] Lines 19-25: Remove verbose docstring
- [ ] Standardize models, fix install step

### basic-flows/respond-directly.mdx
- [ ] Remove touch step
- [ ] `o3-mini` → `gpt-5.2`
- [ ] Fix install step

### basic-flows/delegate-to-all-members.mdx
- [ ] Remove touch step
- [ ] `o3-mini` → `gpt-5.2`
- [ ] Fix install step

### async-flows/basic-team.mdx
- [ ] Remove touch step
- [ ] `gpt-5-mini` and `o3` → `gpt-5.2`
- [ ] Fix install step

### async-flows/basic-streaming.mdx
- [ ] Remove touch step
- [ ] Lines 18-24: Remove verbose docstring
- [ ] `gpt-5-mini` → `gpt-5.2`
- [ ] Fix install step

### async-flows/stream-events.mdx
- [ ] Remove touch step
- [ ] Lines 18-23: Remove verbose docstring
- [ ] Fix imports (same as basic-flows/stream-events.mdx)
- [ ] `claude-3-7-sonnet-latest` → `claude-sonnet-4-5`
- [ ] Lines 103-121: Remove emojis from code
- [ ] Fix install step

### async-flows/respond-directly.mdx
- [ ] Remove touch step
- [ ] Lines 17-30: Remove verbose docstring
- [ ] Standardize models (remove DeepSeek, use claude-sonnet-4-5 or gpt-5.2)
- [ ] Fix install step

### async-flows/delegate-to-all-members.mdx
- [ ] Remove touch step
- [ ] Lines 18-38: Remove verbose docstring
- [ ] `gpt-5-mini` → `gpt-5.2`
- [ ] Fix install step

### other/run-as-cli.mdx
- [ ] Remove touch step
- [ ] Lines 19-24: Remove verbose docstring with emojis
- [ ] Lines 145-146: Remove emojis from print statements
- [ ] Lines 155-157: Remove verbose `###########` comments
- [ ] `gpt-5-mini` → `gpt-5.2`
- [ ] Fix install step

### other/team-exponential-backoff.mdx
- [ ] Remove touch step
- [ ] Fix install step

### other/model-inheritance.mdx
- [ ] Remove touch step
- [ ] Line 48: `gpt-4o-mini` → keep as-is (demonstrates different model)
- [ ] Line 60: `gpt-5-mini` → `gpt-5.2`
- [ ] Line 66: `gpt-4o` → keep as-is (demonstrates inheritance)
- [ ] Fix install step

---

## Phase 3: Sidebar (docs.json)

- [ ] Rename "Usage" → "Examples"
- [ ] Flatten hierarchy - remove nested groups (Basic Flows, Async Flows, Other)
- [ ] List all examples at the same level

---

## Summary

| Category | Files | Issues |
|----------|-------|--------|
| Core Docs | 5 | ~15 |
| Examples | 14 | ~70 |
| Sidebar | 1 | 3 |
