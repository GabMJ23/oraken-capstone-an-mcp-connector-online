# Capstone hints

Read one hint at a time.

<details>
<summary>Hint 1: where do most checks fail?</summary>

Run `pytest -q` and read the first failure of each file: the messages say what to fix. They come in the order of the day:

- `test_tool_design.py` (10 am): the second tool is missing, and the first one's description sells instead of describing.
- `test_reliability.py` (10 to 11 am): a source that is down makes the tool raise. A tool must always return the envelope.
- `test_deployment.py` (1 to 2 pm): `PORT`, `/health`, and the Dockerfile.
- `test_evaluation.py` and `test_documentation.py` (4 to 5 pm): your evaluation, README, privacy page and report.

To run one file only: `pytest -q tests/test_reliability.py`.

</details>

<details>
<summary>Hint 2: the shape of a tool that never crashes</summary>

Three exits, always the same envelope:

```python
async def company_lookup(name, fetch=http_get_json):
    name = (name or "").strip()
    if not name:
        return envelope(missing=["No company name or ticker was given."])
    try:
        data = await fetch(SEC_TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT})
    except Exception:
        return envelope(missing=["SEC EDGAR could not be reached. Try again later."])
    # ... search `data`, build facts and sources ...
    if not facts:
        return envelope(missing=[f"No company matching '{name}' in SEC EDGAR."])
    return envelope(facts, sources)
```

The SEC file is a dict of rows like `{"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}`: loop over `data.values()`. A CIK is written with 10 digits: `str(cik).zfill(10)`. Read the User-Agent from the environment: `os.environ.get("SEC_USER_AGENT", "PublicRecordsMCP/1.0 contact@example.com")`.

The message in `missing` is for the model: short, plain, no stack trace, no internal detail.

</details>

<details>
<summary>Hint 3: almost the answer (descriptions, PORT, health, Dockerfile)</summary>

A description that passes, and that a reviewer accepts:

```python
description=(
    "Looks up a US public company in the SEC EDGAR list of filers by name or ticker. "
    "Returns up to 5 matches with company name, ticker, CIK number and a link to its filings. "
    "Use when the user needs the official identifier or filings page of a company listed in the US."
)
```

An input with a description: `name: Annotated[str, Field(description="A company name or a ticker, for example 'Apple' or 'AAPL'.")]` (imports: `from typing import Annotated` and `from pydantic import Field`).

`PORT = int(os.environ.get("PORT", "8000"))`, then pass `port=PORT` to `FastMCP(...)`. Keep `host="0.0.0.0"`: with `127.0.0.1` nothing outside the container reaches the server, and the SDK also turns on a protection that rejects requests whose `Host` header is not localhost.

```python
from starlette.requests import Request
from starlette.responses import JSONResponse

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})
```

Dockerfile, in order: `FROM python:3.12-slim`, `WORKDIR /app`, `COPY requirements.txt .`, `RUN pip install --no-cache-dir -r requirements.txt`, `COPY server.py .`, `RUN useradd --create-home app`, `USER app`, `EXPOSE 8000`, `CMD ["python", "server.py"]`.

</details>
