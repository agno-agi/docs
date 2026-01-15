# Agno Docs

## Contributing

We welcome contributions to improve the Agno documentation! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on:

- How to set up your development environment
- Pull request and branch naming conventions
- Documentation structure and writing guidelines
- Testing and validation procedures

## Development

Install the [Mintlify CLI](https://www.npmjs.com/package/mintlify) to run documentation site locally:

```
npm i -g mint
```

Run the following command at the root of your documentation (where `docs.json` is)

```
mint dev
```

## Publishing Changes

Publish changes by pushing to the main branch

```
git add .
git commit -m "update message"
git push
```

## Generating New API Reference

**Note:**

Before generating a new API Reference, ensure that the following packages are installed in your dev environment

```bash
pip install fastapi uvicorn sqlalchemy pgvector psycopg openai ddgs yfinance a2a a2a-types a2a-sdk ag-ui-protocol slack-sdk
```

### Steps

1. In your local `agno` repo, run the `AgentOS` cookbook containing all supported interfaces, using the latest version of Agno.
   ```bash
   python cookbook/06_agent_os/all_interfaces.py
   ```

2. Download the latest API reference files:
   ```bash
   curl -o reference-api/openapi.json http://localhost:7777/openapi.json
   ```
   Using swagger-cli to create openapi.yaml counterpart:
   ```bash
   swagger-cli bundle reference-api/openapi.json --outfile reference-api/openapi.yaml --type yaml
   ```

3. Delete all files in the `reference-api/schema/` folder (the auto-generated files)
4. Run `npx @mintlify/scraping@latest openapi-file reference-api/openapi.json -o reference-api/schema` to generate the new API reference
5. Update the `docs.json` file to include any new pages.
6. Run `mint dev` to see the changes

## Troubleshooting

- Mintlify dev isn't running - Run `mint update` it'll update dependencies.
- Page loads as a 404 - Make sure you are running in a folder with `docs.json`
