"""Evaluation: eval/questions.json holds your 10 test questions and what the assistant actually did."""
import json
import re

import pytest

from conftest import ROOT, TOOL_NAMES

QUESTIONS = ROOT / "eval" / "questions.json"
TYPES = ("direct", "indirect", "off_topic")


@pytest.fixture
def items():
    assert QUESTIONS.exists(), "eval/questions.json is missing."
    try:
        data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"eval/questions.json is not valid JSON: {exc}")
    assert isinstance(data, list), "eval/questions.json must be a list of questions."
    return data


def test_ten_questions(items):
    assert len(items) == 10, f"eval/questions.json has {len(items)} question(s). Write exactly 10."


def test_each_question_is_complete(items):
    for i, q in enumerate(items, 1):
        assert isinstance(q, dict), f"Question {i} must be an object."
        for key in ("question", "type", "expected_tool", "chosen_tool"):
            assert key in q, f"Question {i} has no '{key}' field."
        assert isinstance(q["question"], str) and len(q["question"].strip()) >= 10, f"Question {i}: write the question in full."
        assert q["type"] in TYPES, f"Question {i}: type is {q['type']!r}; use one of {', '.join(TYPES)}."
        assert q["expected_tool"] in (*TOOL_NAMES, None), (
            f"Question {i}: expected_tool is {q['expected_tool']!r}; use a tool name, or null when no tool should be called."
        )


def test_question_types_are_mixed(items):
    counts = {t: sum(1 for q in items if isinstance(q, dict) and q.get("type") == t) for t in TYPES}
    for t, n in counts.items():
        assert n >= 2, f"Only {n} '{t}' question(s). Write at least 2 of each type: {counts}."


def test_expected_tools_are_consistent(items):
    for i, q in enumerate(items, 1):
        if q.get("type") == "off_topic":
            assert q.get("expected_tool") is None, f"Question {i} is off_topic: expected_tool must be null (no tool should run)."
        else:
            assert q.get("expected_tool") in TOOL_NAMES, f"Question {i} is {q.get('type')}: name the tool you expect."
    used = {q.get("expected_tool") for q in items}
    for name in TOOL_NAMES:
        assert name in used, f"No question expects '{name}'. Test both tools."


def test_indirect_questions_do_not_name_the_tool(items):
    for i, q in enumerate(items, 1):
        if q.get("type") != "indirect":
            continue
        text = q.get("question", "")
        for word in (*TOOL_NAMES, "Federal Register", "EDGAR", "tool"):
            assert not re.search(re.escape(word), text, re.IGNORECASE), (
                f"Question {i} is 'indirect' but mentions '{word}'. An indirect question asks for the need, "
                "like a real user would, without naming the tool or the source."
            )


def test_questions_are_distinct(items):
    texts = [q.get("question", "").strip().lower() for q in items if isinstance(q, dict)]
    assert len(set(texts)) == len(texts), "Two questions are identical. Write 10 different ones."


def test_results_are_recorded(items):
    for i, q in enumerate(items, 1):
        chosen = q.get("chosen_tool")
        assert chosen != "TODO", (
            f"Question {i}: chosen_tool is still TODO. Ask the question in Claude or ChatGPT and record the tool "
            "it called (or null if it called none)."
        )
        assert chosen is None or (isinstance(chosen, str) and chosen.strip()), f"Question {i}: chosen_tool must be a tool name or null."
