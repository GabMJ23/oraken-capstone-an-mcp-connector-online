"""Certificate checker for the capstone: is your MCP connector online, and does it behave?

Usage
  python checker/check_capstone.py https://your-app.example.com/mcp
  python checker/check_capstone.py https://your-app.example.com/mcp --repo .     # also check the repository files
  python checker/check_capstone.py http://localhost:8000/mcp --allow-http         # local test, not valid for the certificate

It connects like an assistant does (the official MCP client SDK, streamable HTTP), lists the tools,
calls each one with a harmless sample input and with a blank input, and calls GET /health on the same
host. It prints PASS, FAIL, WARN or SKIP for each check, grouped by the criteria of the certificate.
Exit code 0 when nothing failed, 1 otherwise.
"""
import argparse
import asyncio
import json
import pathlib
import re
import sys
import time
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALL_TIMEOUT = 55  # seconds: assistants give up on a tool after about a minute
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
SUPERLATIVES = [
    r"\bbest\b", r"\bfastest\b", r"\bmost (reliable|accurate|complete|comprehensive|trusted|powerful|authoritative)\b",
    r"\bultimate\b", r"\bperfect\b", r"\bguaranteed?\b", r"\bunmatched\b", r"\bworld[- ]class\b",
    r"\bnumber one\b", r"#1\b", r"\bsuperior\b", r"\bbetter than\b", r"\bdefinitive\b", r"\bonly tool\b",
    r"\balways (use|call|choose|pick)\b", r"\bprefer this tool\b", r"\buse this tool first\b",
    r"\bnever use (other|another|any other)\b",
]
SAMPLES = {
    "query": "artificial intelligence", "q": "artificial intelligence", "term": "artificial intelligence",
    "keywords": "artificial intelligence", "search": "artificial intelligence", "topic": "artificial intelligence",
    "name": "Apple", "company": "Apple", "company_name": "Apple", "ticker": "AAPL",
    "place": "Springfield", "city": "Springfield", "state": "IL", "address": "1600 Pennsylvania Ave NW, Washington, DC",
}
LEAK_PATTERNS = [r"Traceback \(most recent call last\)", r'File "[^"]+\.py", line \d+']

CRITERIA = [
    ("online", "Works online over HTTPS from Claude or ChatGPT", 4),
    ("design", "Tool design", 3),
    ("reliability", "Reliability", 3),
    ("evaluation", "Evaluation", 3),
    ("container", "Container & deployment", 3),
    ("security", "Security & data", 2),
    ("docs", "Documentation", 2),
]


class Report:
    def __init__(self):
        self.rows = {key: [] for key, _, _ in CRITERIA}

    def add(self, criterion, status, check, detail=""):
        self.rows[criterion].append((status, check, detail))

    def ok(self, criterion, check, detail=""):
        self.add(criterion, "PASS", check, detail)

    def fail(self, criterion, check, detail=""):
        self.add(criterion, "FAIL", check, detail)

    def check(self, criterion, condition, check, detail_ok="", detail_fail=""):
        self.add(criterion, "PASS" if condition else "FAIL", check, detail_ok if condition else detail_fail)

    def failures(self):
        return sum(1 for rows in self.rows.values() for status, _, _ in rows if status == "FAIL")

    def print(self, url, local):
        print(f"\nCapstone checker - {url}\n")
        for key, title, points in CRITERIA:
            rows = self.rows[key]
            statuses = {s for s, _, _ in rows}
            verdict = "FAIL" if "FAIL" in statuses else ("PASS" if "PASS" in statuses else "SKIP")
            print(f"[{verdict}] {title} ({points} pts)")
            for status, check, detail in rows:
                line = f"    {status:<4}  {check}"
                if detail:
                    line += f"  ({detail})"
                print(line)
        print()
        if self.failures():
            print(f"RESULT: FAIL  ({self.failures()} check(s) failed: fix them, redeploy, run the checker again)")
        elif local:
            print("RESULT: LOCAL PASS  (every check passed over http; the certificate needs your public https URL)")
        else:
            print("RESULT: PASS  (paste this line in REPORT.md, C3)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sample_arguments(schema, blank=False):
    """Build harmless arguments from a tool's input schema: required fields only."""
    props = (schema or {}).get("properties", {}) or {}
    args = {}
    for name in (schema or {}).get("required", []) or []:
        spec = props.get(name, {}) or {}
        kind = spec.get("type")
        if "enum" in spec and spec["enum"]:
            args[name] = spec["enum"][0]
        elif kind == "integer":
            args[name] = 1
        elif kind == "number":
            args[name] = 1.0
        elif kind == "boolean":
            args[name] = False
        else:
            args[name] = "" if blank else SAMPLES.get(name.lower(), "test")
    return args


def envelope_from(result):
    """Return the envelope dict from a CallToolResult, or None."""
    data = result.structuredContent
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict) and "facts" not in data:
        data = data["result"]
    if not isinstance(data, dict):
        data = None
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    data = parsed
                    break
    return data


def result_text(result):
    parts = [json.dumps(result.structuredContent, default=str)] if result.structuredContent is not None else []
    parts += [getattr(b, "text", "") or "" for b in result.content or []]
    return "\n".join(parts)


def envelope_problem(data):
    if data is None:
        return "the result is not a JSON object"
    for key in ("facts", "sources", "missing"):
        if key not in data:
            return f"no '{key}' field"
        if not isinstance(data[key], list):
            return f"'{key}' is not a list"
    return None


# ---------------------------------------------------------------------------
# online checks
# ---------------------------------------------------------------------------

async def check_server(url, report, timeout):
    tools = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=timeout + 5)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await asyncio.wait_for(session.initialize(), 30)
                info = init.serverInfo
                report.ok("online", "MCP handshake (initialize) over streamable HTTP", f"server '{info.name}' {info.version}")

                listed = await asyncio.wait_for(session.list_tools(), 30)
                tools = listed.tools
                names = ", ".join(t.name for t in tools) or "none"
                report.check("online", len(tools) >= 2, "tools/list returns at least 2 tools", names, f"found: {names}")

                design_tools(tools, report)
                await call_tools(session, tools, report, timeout)
    return tools


def design_tools(tools, report):
    for t in tools:
        ann = t.annotations
        values = {h: getattr(ann, h, None) if ann else None for h in HINTS}
        not_bool = [h for h, v in values.items() if not isinstance(v, bool)]
        report.check("design", not not_bool, f"{t.name}: the 4 annotations are explicit booleans", "",
                     f"not set: {', '.join(not_bool)}")
        report.check("security", values["readOnlyHint"] is True and values["destructiveHint"] is False,
                     f"{t.name}: readOnlyHint true, destructiveHint false", "",
                     f"readOnlyHint={values['readOnlyHint']}, destructiveHint={values['destructiveHint']}")

        text = t.description or ""
        found = [m.group(0) for p in SUPERLATIVES if (m := re.search(p, text, re.IGNORECASE))]
        report.check("design", not found, f"{t.name}: description is neutral (no superlative)", "",
                     "says: " + ", ".join(repr(f) for f in found))
        report.check("design", len(text) >= 80, f"{t.name}: description says what, which source, when (80+ chars)",
                     f"{len(text)} chars", f"{len(text)} chars")
        if not re.search(r"\bwhen\b", text, re.IGNORECASE):
            report.add("design", "WARN", f"{t.name}: description does not say when to use the tool")
        props = (t.inputSchema or {}).get("properties", {}) or {}
        undescribed = [p for p, s in props.items() if not (s or {}).get("description")]
        if undescribed:
            report.add("design", "WARN", f"{t.name}: inputs without a description", ", ".join(undescribed))


async def call_one(session, tool, args, timeout):
    start = time.monotonic()
    result = await asyncio.wait_for(session.call_tool(tool.name, args), timeout)
    return result, time.monotonic() - start


async def call_tools(session, tools, report, timeout):
    leaks = []
    for t in tools:
        args = sample_arguments(t.inputSchema)
        label = f"{t.name}({json.dumps(args)})"
        try:
            result, seconds = await call_one(session, t, args, timeout)
        except asyncio.TimeoutError:
            report.fail("reliability", f"{label} answers within {timeout} s", "timed out")
            continue
        except Exception as exc:  # noqa: BLE001
            report.fail("reliability", f"{label} answers", f"{type(exc).__name__}: {exc}")
            continue
        data = envelope_from(result)
        problem = envelope_problem(data)
        if result.isError:
            problem = "the tool returned an error: " + result_text(result)[:120]
        report.check("reliability", problem is None, f"{label} returns facts/sources/missing in {seconds:.1f} s",
                     f"{len(data.get('facts', []))} fact(s)" if problem is None else "", problem or "")
        leaks.append(result_text(result))

        blank = sample_arguments(t.inputSchema, blank=True)
        if blank != args:
            try:
                result, seconds = await call_one(session, t, blank, timeout)
                data = envelope_from(result)
                problem = envelope_problem(data)
                if problem is None and not data["missing"]:
                    problem = "'missing' is empty: say what input is needed"
                if result.isError:
                    problem = "the tool returned an error instead of an envelope"
                report.check("reliability", problem is None, f"{t.name} with a blank input returns a clean envelope",
                             "", problem or "")
                leaks.append(result_text(result))
            except Exception as exc:  # noqa: BLE001
                report.fail("reliability", f"{t.name} with a blank input returns a clean envelope", f"{type(exc).__name__}")
    leaked = [p for p in LEAK_PATTERNS for text in leaks if re.search(p, text)]
    report.check("security", not leaked, "no stack trace or file path in tool outputs", "", "a Traceback reached the assistant")


async def check_health(url, report):
    parts = urlparse(url)
    health = f"{parts.scheme}://{parts.netloc}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(health)
        report.check("container", response.status_code == 200, f"GET {health} answers 200",
                     "", f"got {response.status_code}")
    except Exception as exc:  # noqa: BLE001
        report.fail("container", f"GET {health} answers 200", f"{type(exc).__name__}")


# ---------------------------------------------------------------------------
# repository checks (optional, with --repo)
# ---------------------------------------------------------------------------

def check_repo(repo, report, tool_names):
    root = pathlib.Path(repo)
    questions = root / "eval" / "questions.json"
    try:
        items = json.loads(questions.read_text(encoding="utf-8"))
        types = {t: sum(1 for q in items if q.get("type") == t) for t in ("direct", "indirect", "off_topic")}
        todo = sum(1 for q in items if q.get("chosen_tool") == "TODO")
        good = len(items) == 10 and min(types.values()) >= 2 and todo == 0
        right = sum(1 for q in items if q.get("chosen_tool") == q.get("expected_tool"))
        report.check("evaluation", good, "eval/questions.json: 10 questions, direct/indirect/off_topic, results recorded",
                     f"right tool {right}/10", f"{len(items)} questions, types {types}, {todo} TODO")
        unknown = {q.get("expected_tool") for q in items} - set(tool_names) - {None}
        if unknown:
            report.add("evaluation", "WARN", "expected_tool names not served online", ", ".join(sorted(unknown)))
    except Exception as exc:  # noqa: BLE001
        report.fail("evaluation", "eval/questions.json is readable", f"{type(exc).__name__}: {exc}")

    dockerfile = root / "Dockerfile"
    if dockerfile.exists():
        lines = [l.strip() for l in dockerfile.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
        froms = [l.split()[1].lower() for l in lines if l.upper().startswith("FROM ")]
        users = [l.split()[1] for l in lines if l.upper().startswith("USER ")]
        report.check("container", bool(froms) and froms[-1].startswith("python:3.12") and "slim" in froms[-1],
                     "Dockerfile: pinned python:3.12 slim base image", froms[-1] if froms else "", froms[-1] if froms else "no FROM")
        report.check("container", bool(users) and users[-1].split(":")[0] not in ("root", "0"),
                     "Dockerfile: runs as a non-root USER")
    else:
        report.fail("container", "Dockerfile exists")

    privacy = root / "PRIVACY.md"
    report.check("security", privacy.exists() and "TODO" not in privacy.read_text(encoding="utf-8"),
                 "PRIVACY.md exists and is filled")

    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    report.check("docs", bool(re.search(r"^##\s+Deployment\s*$", text, re.M)), "README.md has a Deployment section")
    report.check("docs", bool(re.search(r"^##\s+What['’]s left\s*$", text, re.M)), "README.md has a What's left section")
    report.check("docs", privacy.exists(), "PRIVACY.md exists")


# ---------------------------------------------------------------------------

async def main_async(args):
    report = Report()
    parts = urlparse(args.url)
    local = parts.scheme == "http"
    if parts.scheme == "https":
        report.ok("online", "the URL uses HTTPS")
    elif local and args.allow_http:
        report.add("online", "SKIP", "the URL uses HTTPS", "--allow-http: local test only")
    else:
        report.fail("online", "the URL uses HTTPS", "assistants only connect to https URLs; use --allow-http for a local test")
    if not parts.path.rstrip("/").endswith("/mcp"):
        report.add("online", "WARN", "the URL ends with /mcp", parts.path or "/")

    tools = []
    if parts.scheme == "https" or (local and args.allow_http):
        try:
            tools = await check_server(args.url, report, args.timeout)
        except Exception as exc:  # noqa: BLE001
            while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
                exc = exc.exceptions[0]
            report.fail("online", "connect with the MCP client SDK", f"{type(exc).__name__}: {str(exc)[:160]}")
        await check_health(args.url, report)

    if args.repo:
        check_repo(args.repo, report, [t.name for t in tools])
    else:
        for key in ("evaluation", "docs"):
            report.add(key, "SKIP", "repository files", "checked by the autograder (pytest); add --repo . to check them here")

    report.print(args.url, local)
    return 1 if report.failures() else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Certificate checker for the MCP connector capstone.")
    parser.add_argument("url", help="the public URL of your MCP endpoint, for example https://your-app.example.com/mcp")
    parser.add_argument("--allow-http", action="store_true", help="accept an http:// URL (local test, not valid for the certificate)")
    parser.add_argument("--repo", help="path to your repository, to also check eval/, Dockerfile, README.md and PRIVACY.md")
    parser.add_argument("--timeout", type=int, default=CALL_TIMEOUT, help="seconds allowed for each tool call (default 55)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
