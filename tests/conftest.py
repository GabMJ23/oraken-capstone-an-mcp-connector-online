"""Shared helpers for the capstone checks. The tests never touch the network."""
import asyncio
import json
import pathlib

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

TOOL_NAMES = ("search_federal_register", "find_company")


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


class FakeFetch:
    """Stands in for http_get_json. Returns a canned answer, or raises to simulate a broken source."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    async def __call__(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers or {}})
        if self.error is not None:
            raise self.error
        return self.answer


def http_error(status):
    request = httpx.Request("GET", "https://example.invalid/")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


SOURCE_DOWN = {
    "connection refused": httpx.ConnectError("connection refused"),
    "timeout": httpx.ReadTimeout("read timed out"),
    "HTTP 503": http_error(503),
    "invalid JSON": ValueError("Expecting value: line 1 column 1 (char 0)"),
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call made with httpx during the tests fails, so the checks stay offline."""

    async def refuse(self, request, *args, **kwargs):
        raise httpx.ConnectError(f"network disabled in tests ({request.url})")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)


def assert_envelope(result, where):
    assert isinstance(result, dict), f"{where}: a tool must return a dict (the envelope), got {type(result).__name__}."
    for key in ("facts", "sources", "missing"):
        assert key in result, f"{where}: the envelope has no '{key}' field. Return facts, sources and missing every time."
        assert isinstance(result[key], list), f"{where}: '{key}' must be a list (it can be empty)."
    for item in result["missing"]:
        assert isinstance(item, str) and item.strip(), f"{where}: each item of 'missing' must be a short sentence."
