"""Tool design: names, annotations, descriptions and inputs, as an assistant sees them in tools/list."""
import re

import pytest

import server
from conftest import TOOL_NAMES, run

# Words that sell instead of describe. Directories reject them, and they bias the model's choice.
SUPERLATIVES = [
    r"\bbest\b", r"\bfastest\b", r"\bmost (reliable|accurate|complete|comprehensive|trusted|powerful|authoritative)\b",
    r"\bultimate\b", r"\bperfect\b", r"\bguaranteed?\b", r"\bunmatched\b", r"\bworld[- ]class\b",
    r"\bnumber one\b", r"#1\b", r"\bsuperior\b", r"\bbetter than\b", r"\bdefinitive\b", r"\bonly tool\b",
    r"\balways (use|call|choose|pick)\b", r"\bprefer this tool\b", r"\buse this tool first\b",
    r"\bnever use (other|another|any other)\b",
]
SOURCE_WORDS = {"search_federal_register": ("Federal Register",), "find_company": ("SEC", "EDGAR")}
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
EXPECTED = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


def listed_tools():
    return {t.name: t for t in run(server.mcp.list_tools())}


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_tool_exists(name):
    tools = listed_tools()
    assert name in tools, f"No MCP tool named '{name}'. Found: {sorted(tools) or 'none'}. Register it with @mcp.tool."


def test_at_least_two_tools():
    tools = listed_tools()
    assert len(tools) >= 2, "The connector needs two tools: search_federal_register and find_company."


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_annotations_are_explicit_booleans(name):
    tool = listed_tools().get(name)
    assert tool is not None, f"Tool '{name}' is missing."
    ann = tool.annotations
    assert ann is not None, f"'{name}' has no annotations. Pass annotations=ToolAnnotations(...) to @mcp.tool."
    for hint in HINTS:
        value = getattr(ann, hint, None)
        assert isinstance(value, bool), (
            f"'{name}': {hint} is {value!r}. Set all four hints explicitly to True or False: "
            "an assistant treats a missing hint as the riskiest value."
        )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_annotations_say_read_only(name):
    tool = listed_tools().get(name)
    assert tool is not None and tool.annotations is not None, f"Tool '{name}' or its annotations are missing."
    for hint, expected in EXPECTED.items():
        value = getattr(tool.annotations, hint, None)
        assert value is expected, (
            f"'{name}': {hint} should be {expected} (the tool only reads public data from an external API), got {value!r}."
        )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_description_is_neutral(name):
    tool = listed_tools().get(name)
    assert tool is not None, f"Tool '{name}' is missing."
    text = tool.description or ""
    for pattern in SUPERLATIVES:
        found = re.search(pattern, text, re.IGNORECASE)
        assert not found, (
            f"'{name}': the description says '{found.group(0)}'. Describe, do not sell: "
            "say what the tool does, which source it uses and when to use it."
        )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_description_says_what_source_and_when(name):
    tool = listed_tools().get(name)
    assert tool is not None, f"Tool '{name}' is missing."
    text = tool.description or ""
    assert len(text) >= 80, f"'{name}': the description is {len(text)} characters. Say what it does, which source and when (80+ characters)."
    assert any(w.lower() in text.lower() for w in SOURCE_WORDS[name]), (
        f"'{name}': the description should name its source ({' or '.join(SOURCE_WORDS[name])})."
    )
    assert re.search(r"\bwhen\b", text, re.IGNORECASE), (
        f"'{name}': the description should say when to use it, for example 'Use when the user asks about ...'."
    )


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_inputs_are_described(name):
    tool = listed_tools().get(name)
    assert tool is not None, f"Tool '{name}' is missing."
    props = (tool.inputSchema or {}).get("properties", {})
    assert props, f"'{name}' takes no input. It needs one (a query or a company name)."
    for prop, schema in props.items():
        assert schema.get("description"), (
            f"'{name}': the input '{prop}' has no description. Use Annotated[str, Field(description='...')] "
            "and give an example value: the model reads it to fill the argument."
        )
