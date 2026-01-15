# TODO: basics/agents/usage (Recipes)

Improvements for the agent recipes section.

---

## Completed: 2025-01-13

### docs.json
- [x] Changed `"group": "Usage"` to `"group": "Recipes"`

### Missing Descriptions - All Added
- [x] run-response-events.mdx
- [x] intermediate-steps.mdx
- [x] agent-run-metadata.mdx
- [x] cancel-a-run.mdx
- [x] debug-level.mdx
- [x] scenario-testing.mdx
- [x] tool-call-limit.mdx

### Model IDs - Standardized
- [x] OpenAI files: `gpt-5-mini` → `gpt-5.2`
- [x] Claude files: older IDs → `claude-sonnet-4-5`

### Code Cleanup
- [x] scenario-testing.mdx: Fixed install command (`scenario` → `langwatch-scenario`)
- [x] tool-call-limit.mdx: Removed "cookbook" docstring
- [x] debug-level.mdx: Removed redundant docstring, fixed imports
- [x] agent-with-memory.mdx: Fixed import path

---

## Remaining (Deferred)

### Low Priority
- [ ] Mac and Windows "Run Agent" steps are identical - consider consolidating
- [ ] instructions.mdx has emojis in example instructions (intentional demo)
- [ ] agent-with-storage.mdx and agent-with-knowledge.mdx have emojis (part of recipe demo)
- [ ] cancel-a-run.mdx has emojis in print statements (visual feedback demo)

### Structural Considerations
- [ ] agent-with-storage.mdx and agent-with-knowledge.mdx are nearly identical (both Thai recipe) - consider differentiating
- [ ] Consider whether some "Other" recipes belong in different categories
