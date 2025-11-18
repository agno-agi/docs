# Contributing to Agno Documentation

Agno is an open-source project and we welcome contributions to our documentation.

## 🚀 Quick Start for Contributors

1. Fork the repository and clone it locally
2. Install Mintlify CLI: `npm i -g mintlify`
3. Run the docs locally: `mint dev` (from the root directory where `docs.json` is)
4. Create a new branch: `git checkout -b [type]/short-description` (e.g., `docs/add-auth-guide`)
5. Make your changes and test with `mint dev`
6. Run `mint build` to check for errors
7. Commit and push your changes
8. Open a pull request with the proper title format (see below)

## 👩‍💻 How to contribute

Please follow the [fork and pull request](https://docs.github.com/en/get-started/quickstart/contributing-to-projects) workflow:

- Fork the repository.
- Create a new branch for your feature.
  - **Branch Naming:** Use the format `[type]/short-description` (e.g., `docs/add-quickstart-guide`, `fix/broken-links`, `style/format-code-examples`)
  - Add your documentation improvements or new content.
  - **Ensure your Pull Request follows our guidelines (see below).**
  - Send a pull request.
  - We appreciate your support & input!

## Pull Request Guidelines

To maintain a clear and organized project history, please adhere to the following guidelines when submitting Pull Requests:

1.  **Title Format:** Your PR title must follow conventional commit format with a type, followed by a colon and a concise subject.
    - Example: `docs: add authentication guide`
    - Common types for documentation:
      - `docs:` - Documentation content changes (new pages, updates, improvements)
      - `fix:` - Fixes to documentation (broken links, typos, incorrect information)
      - `style:` - Formatting changes (no content changes)
    - Other valid types: `feat:`, `test:`, `refactor:`, `build:`, `ci:`, `chore:`, `perf:`, `revert:`.
2.  **Link to Issue:** The PR description should ideally reference the issue it addresses using keywords like `fixes #<issue_number>`, `closes #<issue_number>`, or `resolves #<issue_number>`.
    - Example: `This PR fixes #42 by adding documentation for the new feature.`

## Documentation Structure

The documentation is organized into the following main sections:

- **introduction/** - Getting started guides and overview
- **tutorials/** - Step-by-step tutorials
- **how-to/** - Task-oriented guides
- **basics/** - Conceptual explanations
- **integrations/** - Guides for external integrations
- **reference/** - Reference documentation
- **reference-api/** - API reference (auto-generated)
- **examples/** - Example code and use cases
- **templates/** - Our code templates and how to use them
- **agent-os/** - AgentOS-specific documentation
- **deploy/** - Introduction to deploying Agno agents/agentOS
- **evals/** - Evaluation documentation
- **faq/** - Frequently asked questions
- **videos/** - Video assets for the docs
- **_snippets/** - Reusable code snippets

## Writing Guidelines

1. **Use clear, concise language** - Write for developers who may be new to the framework.
2. **Include code examples** - Show, don't just tell. Use code snippets to illustrate concepts.
3. **Follow MDX format** - All documentation uses MDX (Markdown with JSX support).
4. **Use consistent formatting** - Follow the existing style in the documentation.
5. **Test your changes** - Always run `mint dev` to preview your changes before submitting.
6. **Link to related content** - Help users navigate by linking to related documentation.

### Code Examples

Use standard markdown code blocks with language tags:

```python
from agno.agent import Agent

agent = Agent(name="MyAgent")
agent.print_response("Hello, world!")
```

For runnable code snippets, you can reference them with filename:

```python hackernews_agent.py
from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools

agent = Agent(tools=[HackerNewsTools()])
```

For multi-platform code examples, use the `<CodeGroup>` component with separate code blocks for each platform:

- Wrap multiple code blocks in `<CodeGroup>` tags
- Each code block should specify the platform (e.g., `bash Mac`, `bash Windows`)
- Include a blank line between code blocks

The `_snippets/` directory contains reusable MDX components (like common setup steps) that can be referenced across multiple documentation pages for consistency.

### Adding New Pages

1. Create a new `.mdx` file in the appropriate directory.
2. Add frontmatter at the top of the file:
   ```mdx
   ---
   title: "Your Page Title"
   description: "Brief description of the page content"
   ---
   ```
3. Update `docs.json` to include the new page in the navigation structure.
4. Test the page appears correctly in local preview.

## Updating API Reference

The API reference in `reference-api/` is auto-generated from the AgentOS OpenAPI schema. For instructions on how to update it, see the [README.md](README.md#how-to-generate-a-new-api-reference).

## Local Testing

Before submitting a pull request, test your changes locally:

1. Run `mint dev` in the root directory.
2. Navigate through your changes in the browser.
3. Run `mint build` to catch any build errors before submitting.
4. Verify all pages load correctly, code examples are properly formatted, links work as expected, and images display correctly.

## Formatting and Validation

Ensure your documentation meets our quality standards:

- Check for broken links and review all internal and external links.
- Validate code examples and make sure all code snippets are syntactically correct.
- Run `mint build` to catch any build errors.
- Preview your changes locally to ensure proper formatting.

Message us on [Discord](https://discord.gg/4MtYHHrgA8) or post on [Discourse](https://community.agno.com/) if you have any questions or need help with your contribution.

## 📚 Resources

- <a href="https://docs.agno.com/introduction" target="_blank" rel="noopener noreferrer">Documentation</a>
- <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">Discord</a>
- <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">Discourse</a>
