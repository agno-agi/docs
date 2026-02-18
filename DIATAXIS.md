# DIATAXIS.md - Documentation Type Framework

Documentation fails when it tries to serve multiple user needs on one page. Every page should serve one primary need. This file defines the four documentation types, how to classify pages, and how to prevent blur between types.

Based on the [Diataxis framework](https://diataxis.fr/) by Daniele Procida.

## The Four Types

### Tutorials (Learning-oriented)

A guided lesson where the learner acquires skills by doing.

**The contract:** "I (the author) will take you by the hand. You will succeed."

The author owns the outcome, not the reader.

**Rules:**

1. Don't try to teach through explanation. Let the user learn by doing.
2. Show the destination upfront: "In this tutorial, we will build a research agent with memory and tools."
3. Deliver visible results at every step. Each action should produce output the reader can see and verify.
4. Minimize explanation ruthlessly. A tutorial is not the place for "why." Link to explanation pages instead.
5. Eliminate choices and alternatives. One path. No "you could also use..." digressions.
6. Use concrete examples, not abstractions. Specific values, specific outputs, specific file names.
7. Aspire to perfect reliability. Every step must work, every time. A failed step destroys trust in the tutorial, the author, and the reader's own abilities.
8. Enable and encourage repetition. Structure steps so they can be re-run for reinforcement.
9. Point out what the reader should notice: "Notice that the agent now responds with structured output instead of plain text."
10. Maintain a narrative of expectations: "The output should look something like..." followed by actual example output.

**Language patterns:**

- "We will..." (first-person plural affirms the tutor-learner relationship)
- "First, do x. Now, do y. Now that you have done y, do z."
- "The output should look something like..."
- "Notice that..." / "Let's check..."
- "You have built a [describe what they built]."

**Anti-patterns:**

- Explaining concepts mid-tutorial ("Agents use an event-driven architecture because...")
- Offering alternative approaches ("You could also use GPT-4 instead of Claude...")
- Assuming the reader knows the tools ("Configure your vector database" without showing how)
- Presenting choices ("Choose either Postgres or SQLite for storage")

**Agno examples:** First Agent, First Multi-Agent System

**Deep dive:** https://diataxis.fr/tutorials/

---

### How-to Guides (Task-oriented)

Goal-oriented directions for a competent user solving a real problem.

**The contract:** "You know what you want to do. Here's how."

The reader owns the outcome.

**Rules:**

1. Write from the user's perspective, not the machinery's. Address real problems ("How to add memory to an agent") not tool operations ("How to call `agent.memory.add()`").
2. Assume competence and familiarity with basics. Don't re-teach what the tutorial covered.
3. Omit the unnecessary. Practical usability beats completeness. Start and end where the user needs, not at the beginning of the universe.
4. Describe a logical sequence with clear flow. Anticipate what the user needs next. Avoid context-switching.
5. Title precisely: "How to integrate PgVector with an agent's knowledge base" not "Knowledge" or "Using knowledge."
6. Allow for real-world branching: "If you're using Docker, run... If you're using a local install, run..."
7. Link to reference for full parameter lists. Show only the parameters needed for this specific task.

**Language patterns:**

- "This guide shows you how to..."
- "If you want x, do y." (conditional imperatives)
- "Refer to the [Contributing Guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md) for details."

**Anti-patterns:**

- Teaching basics in a how-to ("First, let's understand what agents are...")
- Including exhaustive reference tables (link to reference instead)
- Explaining "why" at length (link to explanation instead)
- Open-ended scope ("How to build a web application" is too broad)

**Agno examples:** Provider setup pages, usage examples under agents/usage/, tools/ provider pages, knowledge/ provider pages

**Deep dive:** https://diataxis.fr/how-to-guides/

---

### Reference (Information-oriented)

Austere, factual technical description of the machinery.

**The contract:** "Here is the truth about how this works."

Users consult reference while actively working. It must be reliable, complete, and fast to scan.

**Rules:**

1. Describe and only describe. No instruction, no explanation, no opinion. Link to those instead.
2. Mirror the structure of the code/product. If the code has `Agent`, `Team`, `Workflow` classes, reference should have corresponding sections in that order.
3. Use consistent, standard patterns across all reference pages. Every API reference page should have the same sections in the same order.
4. Provide examples that illustrate without teaching. A short code snippet showing usage, not a guided walkthrough.
5. Be complete. Every parameter, every option, every return type, every exception.

**Language patterns:**

- State facts: "X accepts Y. Returns Z. Raises W if..."
- List commands, options, flags, limitations, error messages.
- Include warnings: "You must do X before Y. Never do Z without W."

**Anti-patterns:**

- Explaining design decisions in reference ("We chose this approach because...")
- Including tutorials inside reference ("Let's walk through building an agent...")
- Inconsistent formatting between reference pages (some have tables, some have lists, some have neither)
- Incomplete coverage (documenting 8 of 12 parameters)

**Agno examples:** /reference/ section (API schemas, parameter tables)

**Deep dive:** https://diataxis.fr/reference/

---

### Explanation (Understanding-oriented)

Discursive treatment of a subject that deepens understanding.

**The contract:** "Here's why things are the way they are."

This is the only documentation type meant to be read away from the keyboard.

**Rules:**

1. Make connections to related concepts. Link agents to teams, teams to workflows, memory to sessions.
2. Provide context: design decisions, constraints, trade-offs. Why does Agno use stateless agents? Why is knowledge separate from memory?
3. Scope with "About X" framing. Each explanation page covers one bounded topic.
4. Admit perspective and opinion where appropriate. "Session-based memory works well for chatbots but adds overhead for batch processing."
5. Keep instruction and technical description out. No step-by-step guides, no parameter tables.

**Language patterns:**

- "The reason for x is..."
- "W is better than Z because..."
- "An x in Agno is analogous to a w in [other system]. However..."
- "Some users prefer w (because z). This works well when..."

**Anti-patterns:**

- Embedding step-by-step instructions ("First, install... Then, configure...")
- Including API parameter tables
- Trying to be both reference and explanation on the same page

**Agno examples:** "What are Agents?", "What are Teams?", overview/concept pages

**Deep dive:** https://diataxis.fr/explanation/

---

## Writing Style (All Types)

These rules apply across all four documentation types:

- **No em dashes.** Use periods or rewrite.
- **No contrastive negation.** Don't define things by what they aren't ("It's not X, it's Y" / "X isn't just Y"). State what they are directly.
- **No "Learn how to..."** Use specific action statements.
- **Lead with code** in tutorials, how-to guides, and reference. Explanation is the only type where prose-first is acceptable.

See [CLAUDE.md](./CLAUDE.md) for the complete style guide.

---

## The Compass (Quick Classification)

Two questions to classify any piece of content:

1. **Action or Cognition?** Is the reader trying to DO something, or UNDERSTAND something?
2. **Acquisition or Application?** Is the reader LEARNING, or WORKING?

|                          | Acquisition (learning) | Application (working) |
| ------------------------ | ---------------------- | --------------------- |
| **Action** (doing)       | Tutorial               | How-to Guide          |
| **Cognition** (thinking) | Explanation            | Reference             |

Apply this at any scale: a whole page, a section, or a single paragraph that feels wrong.

**Source:** https://diataxis.fr/compass/

---

## The Blur Problem

Documentation degrades when types bleed into each other. This is the most common cause of bad documentation.

### Common Failures in SDK Docs

| Blur                      | What happens                                                    | Fix                                                                |
| ------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------ |
| Tutorial + Explanation    | Tutorial stops to explain concepts for 3 paragraphs             | Move explanation to a linked "What are X?" page                    |
| How-to + Tutorial         | How-to guide teaches basics before getting to the task          | Assume competence. Link to the tutorial.                           |
| Reference + Explanation   | API reference includes paragraphs about design decisions        | Move "why" content to an explanation page. Keep reference austere. |
| How-to + Reference        | How-to guide includes complete parameter tables                 | Link to reference. Show only the parameters needed for this task.  |
| Explanation + Instruction | Concept page includes "First, install... Then configure..."     | Move instructions to a how-to guide. Keep explanation discursive.  |
| Tutorial + How-to         | Tutorial offers choices ("you could also use Pinecone instead") | Tutorials follow one path. Move alternatives to how-to guides.     |

### The Test

Ask: "Would someone consult this while actively working on a task, or only after stepping away to reflect?"

- While working → Reference (if looking up facts) or How-to (if following steps)
- Stepped away → Explanation (if understanding) or Tutorial (if learning)

**Source:** https://diataxis.fr/tutorials-how-to/ and https://diataxis.fr/reference-explanation/

---

## Before Writing or Revising Any Page

1. **What type is this page?** Use the compass above.
2. **Does any content on this page belong to a different type?** Check for blur.
3. **If blur exists:** Extract the foreign content into the correct page type and link to it.

When the type is clear, follow the rules for that type. When in doubt, the compass resolves it.

---

## Page Type Decision Tree

- User is brand new, needs to get something working → **Tutorial**
- User knows what they want to do, needs directions → **How-to Guide**
- User needs to look up a parameter, method, or config → **Reference**
- User wants to understand why something works the way it does → **Explanation**

---

## Complex Documentation

For large documentation sets with multiple user types or deployment contexts:

- Documentation should be as complex as it needs to be. Don't oversimplify.
- Keep navigation lists to ~7 items. Subdivide if longer.
- Landing pages should function as overviews with context, not bare link lists.
- When user types diverge (developers vs. end users), organize by user type first, then by Diataxis type within each.
- Diataxis is an approach to user needs, not a rigid four-folder structure. Let structure emerge from improved content.

**Source:** https://diataxis.fr/complex-hierarchies/

---

## Further Reading

- [Full framework](https://diataxis.fr/)
- [Tutorials deep dive](https://diataxis.fr/tutorials/)
- [How-to guides deep dive](https://diataxis.fr/how-to-guides/)
- [Reference deep dive](https://diataxis.fr/reference/)
- [Explanation deep dive](https://diataxis.fr/explanation/)
- [The compass](https://diataxis.fr/compass/)
- [Tutorial vs How-to](https://diataxis.fr/tutorials-how-to/) (the most common confusion)
- [Reference vs Explanation](https://diataxis.fr/reference-explanation/)
- [Complex hierarchies](https://diataxis.fr/complex-hierarchies/)
- [Quality theory](https://diataxis.fr/quality/)
- [Workflow guidance](https://diataxis.fr/how-to-use-diataxis/)
