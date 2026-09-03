## Description

Describe key changes, mention related issues or motivation for the changes.

**Note:** Your PR title must follow conventional commit format (e.g., `docs: add auth guide`, `fix: correct broken links`, `style: update formatting`). See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

## Type of Change

- [ ] Bug fix (errors, broken links, outdated info)
- [ ] New content
- [ ] Content improvement
- [ ] Other: \_\_\_\_

## Related Issues/PRs (if applicable)

<!-- Link any related issues or PRs -->

- Closes #\_\_\_\_
- Related SDK PR: agno-agi/agno#\_\_\_\_

## Checklist

- [ ] Content is accurate and up-to-date
- [ ] All links tested and working
- [ ] Code examples verified (if applicable)
- [ ] Deterministic scripts pass for the affected examples, imports, installs, and references
- [ ] OpenAPI JSON and YAML were updated together and `scripts/make_openapi.py --check` passes (if applicable)
- [ ] `mint broken-links -t false` and `mint validate -t false` pass
- [ ] Spelling and grammar checked
- [ ] Screenshots updated (if applicable)
