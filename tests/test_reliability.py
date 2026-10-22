"""Reliability: the envelope, empty results, blank inputs and a source that is down. All offline, with fakes."""
import json

import pytest

import server
from conftest import SOURCE_DOWN, FakeFetch, assert_envelope, load_fixture, run


def logic(name):
    fn = getattr(server, name, None)
    assert fn is not None, f"server.py has no function '{name}'. Keep the tool logic in it (see the comments in server.py)."
    return fn


# --- Federal Register -------------------------------------------------------

def test_federal_register_returns_facts_and_sources():
    fake = FakeFetch(load_fixture("federal_register_rules.json"))
    result = run(logic("federal_register_search")("artificial intelligence", fetch=fake))
    assert_envelope(result, "search_federal_register")
    assert len(fake.calls) == 1, "The tool should call the Federal Register API exactly once."
    assert fake.calls[0]["url"].startswith("https://www.federalregister.gov/api/v1/documents"), (
        "Call the Federal Register documents endpoint: https://www.federalregister.gov/api/v1/documents.json"
    )
    assert 1 <= len(result["facts"]) <= 5, "Return the documents found (at most 5)."
    first = result["facts"][0]
    assert first.get("title") and first.get("publication_date"), "Each fact should keep at least the title and the publication date."
    urls = [s.get("url", "") for s in result["sources"] if isinstance(s, dict)]
    assert any(u.startswith("https://www.federalregister.gov/documents/") for u in urls), (
        "List the link of each document in 'sources', so the assistant can cite it."
    )


def test_federal_register_sends_the_query():
    fake = FakeFetch(load_fixture("federal_register_rules.json"))
    run(logic("federal_register_search")("artificial intelligence", fetch=fake))
    sent = json.dumps(fake.calls[0]["params"], default=str)
    assert "artificial intelligence" in sent and "conditions[term]" in sent, (
        "Pass the user's words as the conditions[term] parameter."
    )


def test_federal_register_nothing_found_fills_missing():
    fake = FakeFetch({"description": "Documents matching 'zzqqxx'", "count": 0})  # the real API sends no "results" key
    result = run(logic("federal_register_search")("zzqqxx", fetch=fake))
    assert_envelope(result, "search_federal_register (nothing found)")
    assert result["facts"] == [], "Nothing was found: 'facts' should be empty."
    assert result["missing"], "Nothing was found: say so in 'missing', so the assistant does not make something up."


def test_federal_register_blank_query_does_not_call_the_source():
    fake = FakeFetch(load_fixture("federal_register_rules.json"))
    result = run(logic("federal_register_search")("   ", fetch=fake))
    assert_envelope(result, "search_federal_register (blank query)")
    assert fake.calls == [], "A blank query should not call the API: return an envelope that asks for search terms."
    assert result["missing"], "A blank query: explain in 'missing' what the user should give."


@pytest.mark.parametrize("problem", list(SOURCE_DOWN))
def test_federal_register_source_down_returns_clean_envelope(problem):
    fake = FakeFetch(error=SOURCE_DOWN[problem])
    try:
        result = run(logic("federal_register_search")("artificial intelligence", fetch=fake))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"Source down ({problem}): the tool raised {type(exc).__name__}. "
            "Catch the error and return an envelope with 'missing' filled instead."
        )
    assert_envelope(result, f"search_federal_register (source down: {problem})")
    assert result["facts"] == [], f"Source down ({problem}): 'facts' should be empty."
    assert result["missing"], f"Source down ({problem}): say in 'missing' that the source could not be reached."
    assert "Traceback" not in json.dumps(result), "Never send a stack trace to the assistant."


# --- SEC EDGAR ----------------------------------------------------------------

def test_company_lookup_by_name():
    fake = FakeFetch(load_fixture("sec_company_tickers.json"))
    result = run(logic("company_lookup")("apple", fetch=fake))
    assert_envelope(result, "find_company")
    assert fake.calls and fake.calls[0]["url"] == "https://www.sec.gov/files/company_tickers.json", (
        "Download https://www.sec.gov/files/company_tickers.json"
    )
    blob = json.dumps(result["facts"])
    assert "AAPL" in blob and "320193" in blob, "Searching 'apple' should return Apple Inc. with ticker AAPL and CIK 320193."
    assert 1 <= len(result["facts"]) <= 5, "Return at most 5 companies."
    assert result["sources"], "List where the data comes from in 'sources'."


def test_company_lookup_by_ticker():
    fake = FakeFetch(load_fixture("sec_company_tickers.json"))
    result = run(logic("company_lookup")("MSFT", fetch=fake))
    assert_envelope(result, "find_company")
    assert "789019" in json.dumps(result["facts"]), "Searching the ticker 'MSFT' should return Microsoft (CIK 789019)."


def test_company_lookup_sends_a_descriptive_user_agent():
    fake = FakeFetch(load_fixture("sec_company_tickers.json"))
    run(logic("company_lookup")("apple", fetch=fake))
    headers = {k.lower(): v for k, v in (fake.calls[0]["headers"] or {}).items()}
    ua = headers.get("user-agent", "")
    assert "@" in ua, (
        "The SEC answers 403 without a descriptive User-Agent. Send headers={'User-Agent': 'Your Name you@example.com'}."
    )


def test_company_lookup_nothing_found_fills_missing():
    fake = FakeFetch(load_fixture("sec_company_tickers.json"))
    result = run(logic("company_lookup")("Zzqqxx Holdings", fetch=fake))
    assert_envelope(result, "find_company (nothing found)")
    assert result["facts"] == [], "Nothing matches: 'facts' should be empty."
    assert result["missing"], "Nothing matches: say so in 'missing'."


def test_company_lookup_blank_name_does_not_call_the_source():
    fake = FakeFetch(load_fixture("sec_company_tickers.json"))
    result = run(logic("company_lookup")("", fetch=fake))
    assert_envelope(result, "find_company (blank name)")
    assert fake.calls == [], "A blank name should not download the SEC file."
    assert result["missing"], "A blank name: explain in 'missing' what is needed."


@pytest.mark.parametrize("problem", list(SOURCE_DOWN))
def test_company_lookup_source_down_returns_clean_envelope(problem):
    fake = FakeFetch(error=SOURCE_DOWN[problem])
    try:
        result = run(logic("company_lookup")("apple", fetch=fake))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Source down ({problem}): the tool raised {type(exc).__name__}. Return an envelope instead.")
    assert_envelope(result, f"find_company (source down: {problem})")
    assert result["facts"] == [], f"Source down ({problem}): 'facts' should be empty."
    assert result["missing"], f"Source down ({problem}): say in 'missing' that SEC EDGAR could not be reached."


# --- The network layer ----------------------------------------------------------

def test_http_calls_have_a_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class RecordingClient:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(server.httpx, "AsyncClient", RecordingClient)
    run(server.http_get_json("https://example.invalid/"))
    timeout = captured.get("timeout")
    assert timeout is not None, "Create the httpx.AsyncClient with a timeout, for example httpx.AsyncClient(timeout=10)."
    seconds = timeout if isinstance(timeout, (int, float)) else getattr(timeout, "read", None)
    assert seconds is not None and 0 < seconds <= 30, (
        f"The timeout is {seconds!r}. Use a few seconds (30 at most): assistants give up on a tool after about a minute."
    )


@pytest.mark.parametrize("tool,args", [("search_federal_register", {"query": "artificial intelligence"}),
                                       ("find_company", {"name": "apple"})])
def test_tool_over_mcp_survives_source_down(monkeypatch, tool, args):
    async def down(url, params=None, headers=None):
        raise SOURCE_DOWN["connection refused"]

    monkeypatch.setattr(server, "http_get_json", down)
    names = [t.name for t in run(server.mcp.list_tools())]
    assert tool in names, f"Tool '{tool}' is missing."
    try:
        out = run(server.mcp.call_tool(tool, args))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Calling '{tool}' over MCP with the source down raised {type(exc).__name__}: {exc}")
    structured = out[1] if isinstance(out, tuple) else None
    if not isinstance(structured, dict):
        blocks = out[0] if isinstance(out, tuple) else out
        structured = json.loads(blocks[0].text)
    assert_envelope(structured, f"{tool} over MCP (source down)")
    assert structured["missing"], f"{tool} over MCP: with the source down, 'missing' must explain it."
