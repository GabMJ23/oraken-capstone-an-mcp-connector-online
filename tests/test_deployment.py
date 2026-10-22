"""Container and deployment: PORT, /health, the Dockerfile, and no secret in the repository."""
import asyncio
import importlib
import re

import pytest

import server
from conftest import ROOT

DOCKERFILE = ROOT / "Dockerfile"
SECRET_PATTERNS = {
    "an OpenAI-style key": r"sk-[A-Za-z0-9_-]{20,}",
    "an Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "a GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "an AWS access key": r"AKIA[0-9A-Z]{16}",
    "a private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}


@pytest.fixture
def reloaded(monkeypatch):
    """Re-import server.py with a given environment, then restore it."""

    def _load(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(server)

    yield _load
    monkeypatch.undo()
    importlib.reload(server)


def test_port_is_read_from_the_environment(reloaded):
    srv = reloaded(PORT="9123")
    assert srv.mcp.settings.port == 9123, (
        "The server ignores the PORT environment variable. Hosts choose the port: "
        "read it with int(os.environ.get('PORT', '8000')) and pass it to FastMCP."
    )


def test_port_defaults_to_8000(reloaded, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    srv = importlib.reload(server)
    assert srv.mcp.settings.port == 8000, "Without PORT in the environment, listen on 8000."


def test_listens_on_all_interfaces():
    assert server.mcp.settings.host == "0.0.0.0", (
        "Inside a container, listen on 0.0.0.0. With 127.0.0.1, nothing outside the container can reach the server."
    )


def test_mcp_endpoint_path():
    assert server.mcp.settings.streamable_http_path == "/mcp", "Serve MCP on /mcp: that is the URL you give to Claude and ChatGPT."


def asgi_get(app, path):
    """Send one GET request straight to the ASGI app (no network, no server). Returns the status code."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"host", b"localhost:8000")], "client": ("127.0.0.1", 5000), "server": ("localhost", 8000),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


def test_health_endpoint():
    status = asgi_get(server.mcp.streamable_http_app(), "/health")
    assert status == 200, f"GET /health answered {status}. Add @mcp.custom_route('/health', methods=['GET']) returning 200."


# --- Dockerfile -----------------------------------------------------------------

def dockerfile_lines():
    assert DOCKERFILE.exists(), "There is no Dockerfile at the root of the repository."
    lines = []
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def instructions(keyword):
    return [l for l in dockerfile_lines() if l.split()[0].upper() == keyword]


def test_dockerfile_base_image_is_pinned_slim():
    froms = instructions("FROM")
    assert froms, "The Dockerfile has no FROM line. Start from python:3.12-slim."
    image = froms[-1].split()[1].lower()
    assert image.startswith("python:3.12") and "slim" in image, (
        f"The base image is '{image}'. Use a pinned slim Python 3.12 image, for example python:3.12-slim "
        "(never 'latest': the image would change under your feet)."
    )


def test_dockerfile_installs_pinned_requirements():
    runs = " ".join(instructions("RUN"))
    assert re.search(r"pip install[^&;]*-r\s+requirements\.txt", runs), (
        "Install the dependencies from requirements.txt (pip install --no-cache-dir -r requirements.txt)."
    )
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            assert "==" in line, f"requirements.txt: '{line}' is not pinned. Use an exact version (package==1.2.3)."


def test_dockerfile_runs_as_non_root():
    lines = dockerfile_lines()
    users = [i for i, l in enumerate(lines) if l.split()[0].upper() == "USER"]
    assert users, "The container runs as root. Create a user (useradd) and switch to it with a USER line."
    last_user = lines[users[-1]].split()[1].split(":")[0]
    assert last_user not in ("root", "0"), "The last USER line switches back to root. Run as an unprivileged user."
    cmds = [i for i, l in enumerate(lines) if l.split()[0].upper() in ("CMD", "ENTRYPOINT")]
    assert cmds and users[-1] < cmds[-1], "Put the USER line before CMD, so the server itself runs as that user."


def test_dockerfile_starts_the_server():
    cmds = instructions("CMD") + instructions("ENTRYPOINT")
    assert cmds, "The Dockerfile has no CMD. End it with: CMD [\"python\", \"server.py\"]"
    assert "server.py" in cmds[-1], f"The CMD is '{cmds[-1]}'. Start the server: CMD [\"python\", \"server.py\"]"


def test_dockerfile_has_no_secret():
    for line in dockerfile_lines():
        word = line.split()[0].upper()
        if word in ("ENV", "ARG") and re.search(r"(KEY|TOKEN|SECRET|PASSWORD)\w*\s*=?\s*\S", line, re.IGNORECASE):
            pytest.fail(f"The Dockerfile sets a secret: '{line}'. Secrets go in the host's environment settings, never in the image.")
        if word in ("COPY", "ADD") and ".env" in line.split()[1:-1]:
            pytest.fail("The Dockerfile copies .env into the image. Remove it.")
    dockerignore = ROOT / ".dockerignore"
    assert dockerignore.exists() and ".env" in dockerignore.read_text(encoding="utf-8"), (
        "Add a .dockerignore that lists .env (and .venv), so no secret ends up in the image by accident."
    )


def test_no_secret_in_the_repository():
    gitignore = ROOT / ".gitignore"
    assert gitignore.exists() and ".env" in gitignore.read_text(encoding="utf-8"), ".gitignore must list .env."
    for path in ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.relative_to(ROOT).parts) or path.name == ".env":
            continue
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".zip"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            assert not re.search(pattern, text), f"{path.relative_to(ROOT)} seems to contain {label}. Remove it and revoke it."
