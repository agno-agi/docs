# TODO: basics/agents

Improvements for the agents documentation section.

---

## overview.mdx

- [ ] Fix card description for "Building Agents" - currently says "Learn how to run your agents" (copy/paste error from Running Agents card)

---

## building-agents.mdx

- [ ] Remove verbose section comments in code examples (`################ STREAM RESPONSE #################`) - violates clean code guidelines
- [ ] Consider whether "Run your Agent" section duplicates content from running-agents.mdx - may need consolidation or removal
- [ ] The second code block shows the same agent definition as the first, just with different run methods - consider simplifying to show only the new concepts
- [ ] "start simple -- just a model" - consider rephrasing to avoid double hyphen

---

## debugging-agents.mdx

- [ ] Remove subjective language: "exceptionally well-built debug mode" - just describe what it does
- [ ] Fix grammar: "a exceptionally" should be "an exceptionally" (or better, remove the claim entirely)
- [ ] Lead with what debug mode does, not a claim about its quality

**Suggested rewrite for opening:**
```
Current:
"Agno comes with a exceptionally well-built debug mode that helps you understand..."

Better:
"Debug mode helps you understand the flow of execution and intermediate steps:"
```

---

## running-agents.mdx

- [ ] Generally well-structured, lower priority for changes
- [ ] Consider consolidating the many event type tables into fewer, more scannable sections
- [ ] The agent definition is repeated in nearly every code example - could reference a single definition and show only the new concepts in subsequent examples

---

## General Notes

- All files use consistent frontmatter format
- Code examples use correct language hints
- Consider whether building-agents.mdx and running-agents.mdx have overlapping content that could be deduplicated
