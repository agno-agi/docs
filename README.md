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

## How to generate a new API reference

1. Run an `AgentOS` cookbook with the latest version of Agno
2. Download the latest API reference files:
   ```bash
   # Download JSON format
   curl -o reference-api/openapi.json http://localhost:7777/openapi.json
   
   # Download YAML format
   curl -o reference-api/openapi.yaml http://localhost:7777/openapi.yaml
   
   # If YAML endpoint doesn't exist, convert from JSON using yq or swagger-cli
   # Option A: Using yq (if installed): yq eval -o=yaml reference-api/openapi.json > reference-api/openapi.yaml
   # Option B: Using swagger-cli: swagger-cli bundle reference-api/openapi.json --outfile reference-api/openapi.yaml --type yaml
   ```
3. Delete all files in the `reference-api/schema/` folder (the auto-generated files)
4. Run `npx @mintlify/scraping@latest openapi-file reference-api/openapi.json -o reference-api/schema` to generate the new API reference
5. Run `mint dev` to see the changes

## Troubleshooting

- Mintlify dev isn't running - Run `mint update` it'll update dependencies.
- Page loads as a 404 - Make sure you are running in a folder with `docs.json`
