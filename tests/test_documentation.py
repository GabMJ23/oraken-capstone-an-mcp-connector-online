"""Documentation: your connector's README, its privacy page, and REPORT.md."""
import re

from conftest import ROOT

README = ROOT / "README.md"
PRIVACY = ROOT / "PRIVACY.md"
REPORT = ROOT / "REPORT.md"


def heading_section(text, pattern):
    """Return the text under a '## ...' heading matching pattern, up to the next '## ' heading."""
    match = re.search(rf"^##\s+{pattern}\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    rest = text[match.end():]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def section(text, start, end=None):
    i = text.index(start)
    j = text.index(end, i) if end else len(text)
    return text[i:j]


def test_readme_has_deployment_section():
    text = README.read_text(encoding="utf-8")
    deployment = heading_section(text, "Deployment")
    assert deployment is not None, (
        "README.md has no '## Deployment' section. At 5 pm, move these instructions to INSTRUCTIONS.md and "
        "write your connector's own README from templates/README.md."
    )
    assert re.search(r"https://\S+/mcp\b", deployment), "README, Deployment: give the public URL of your server, ending in /mcp."


def test_readme_has_whats_left_section():
    text = README.read_text(encoding="utf-8")
    left = heading_section(text, "What['’]s left")
    assert left is not None, "README.md has no '## What's left' section: list what you would do next, honestly."
    assert len(re.findall(r"\w+", left)) >= 15, "README, What's left: write at least a few real items (15 words or more)."


def test_readme_is_filled():
    text = README.read_text(encoding="utf-8")
    left = text.count("TODO")
    assert left == 0, f"README.md still has {left} TODO."


def test_privacy_page():
    assert PRIVACY.exists(), "PRIVACY.md is missing. Every public connector needs a privacy page (start from templates/PRIVACY.md)."
    text = PRIVACY.read_text(encoding="utf-8")
    assert "TODO" not in text, "PRIVACY.md still has TODO."
    assert len(re.findall(r"\w+", text)) >= 60, "PRIVACY.md is too short: say what is received, what is logged, for how long, and who to contact."


def test_report_required_answers_filled():
    text = REPORT.read_text(encoding="utf-8")
    required = section(text, "## Part A", "**Going further")
    left = required.count("TODO")
    assert left == 0, f"{left} required answer(s) still say TODO in REPORT.md (Parts A to C)."


def test_report_gives_the_evaluation_score():
    text = REPORT.read_text(encoding="utf-8")
    c1 = section(text, "**C1.**", "**C2.**")
    assert re.search(r"\b\d{1,2}\s*/\s*10\b", c1), "C1: give your score as N/10 (right tool choices out of 10)."


def test_report_has_checker_result():
    text = REPORT.read_text(encoding="utf-8")
    c3 = section(text, "**C3.**", "**Going further")
    assert "PASS" in c3, "C3: paste the summary line of the checker (run it against your https URL until it says PASS)."
