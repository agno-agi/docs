# Agno Docs

Agno documentation site built with Mintlify.

## Quickstart

1. Install the Mintlify CLI: `npm i -g mint`
2. From the repo root (the folder with `docs.json`), run `mint dev`
3. Open the local site at `http://localhost:3000`

## Contributing

We welcome contributions to improve the Agno documentation! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on:

- How to set up your development environment
- Pull request and branch naming conventions
- Documentation structure and writing guidelines
- Testing and validation procedures

## Development

Install the [Mintlify CLI](https://www.npmjs.com/package/mintlify) to run the documentation site locally:

```
npm i -g mint
```

Run the following command at the root of your documentation (where `docs.json` is)

```
mint dev
```

## Publishing Changes

Publish changes by pushing to the main branch via a PR.

```
git add .
git commit -m "update message"
git push
```

## How to generate a new API reference

Use the source-pinned offline generator documented in
[`scripts/README.md`](scripts/README.md#release-time-flow). Review every route
and schema change before updating the tracked JSON and YAML specifications.
Preserve curated schema pages and add navigation entries for new endpoints.

## Troubleshooting

- Mintlify dev isn't running - Run `mint update` it'll update dependencies.
- Page loads as a 404 - Make sure you are running in a folder with `docs.json`

## AI Powered Development

First, symlink the `agno` repo (gitignored):

```
ln -s ~/code/agno agno
```

For agno engineers, also symlink the `specs` repo:

```
ln -s ~/code/specs specs
```
