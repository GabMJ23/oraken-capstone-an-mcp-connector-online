# Public Records: an MCP connector for US federal documents and public companies

TODO: one or two sentences. What does this connector let an assistant do, and for whom?

## Tools

| Tool | What it does | Source |
|---|---|---|
| `search_federal_register(query)` | TODO | Federal Register API, https://www.federalregister.gov/developers/documentation/api/v1 |
| `find_company(name)` | TODO | SEC EDGAR, https://www.sec.gov/files/company_tickers.json |

Every tool returns `{"facts": [...], "sources": [...], "missing": [...]}`. Both tools are read-only: they never change anything anywhere.

## Use it

- **Claude:** add a custom connector with the URL below.
- **ChatGPT:** in developer mode, create a connector with the URL below.

## Deployment

- Public MCP URL: TODO (https://.../mcp)
- Health check: TODO (https://.../health)
- Host: TODO
- Environment variables: `PORT` (set by the host), `SEC_USER_AGENT` (your name and contact email, required by the SEC).
- Deploy a new version: TODO (the exact steps or commands)
- Run it locally: `pip install -r requirements.txt`, then `python server.py`, then open `http://localhost:8000/mcp` in the MCP Inspector.

## Evaluation

TODO: your score (N/10), which assistant, and the change you made after the first run. The questions are in `eval/questions.json`.

## What's left

TODO: what you would do next, in order, and why. For example: caching, rate limits, more document types, OAuth, monitoring.

## Privacy

See [PRIVACY.md](PRIVACY.md).
