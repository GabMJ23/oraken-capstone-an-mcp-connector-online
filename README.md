# Capstone: an MCP connector online, in one day

**Part 6 · Lesson 24 · one day · automatically checked + certificate checker**

## Goals

- Build a small MCP connector, **Public Records**, with two read-only tools over two free US public APIs.
- Put it online over HTTPS, in a container, and plug it into Claude and ChatGPT.
- Prove it works: an evaluation of 10 questions, a privacy page, and a green certificate checker.

Nyambot, the case study of Part 2, started the same way: a few tools over public databases, a strict response format, and a lot of care on the descriptions. The data in Nyambot is French; the engineering is the same.

## Before you start

You need Python 3.12, Git, Docker, Node.js (for the MCP Inspector) and an account on a host that runs a Docker image over HTTPS. Create your own copy of this lab (**Use this template** on GitHub), clone it, then:

```bash
python -m venv .venv
# macOS / Linux: source .venv/bin/activate      Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q          # most checks fail at first: that is expected
```

Rules for every lab: one Git repository, one commit per step, your answers in `REPORT.md`, and no secret in Git. Here, the steps are the hours of the day plan below: commit at the end of each one.

### The two sources (verified, free, no key)

| Tool | Source | Try it |
|---|---|---|
| `search_federal_register(query)` | Federal Register API, the daily journal of the US federal government | `curl -g "https://www.federalregister.gov/api/v1/documents.json?conditions[term]=artificial%20intelligence&per_page=5&order=newest"` |
| `find_company(name)` | SEC EDGAR list of public filers (about 800 KB of JSON) | `curl -H "User-Agent: Your Name you@example.com" https://www.sec.gov/files/company_tickers.json` |

Run both commands now. Three traps you will meet in your code too:

- curl needs `-g` because of the square brackets in `conditions[term]`.
- The SEC answers **403** without a descriptive `User-Agent` (a name and a contact email). Without the header, try it: you get 403.
- When nothing matches, the Federal Register answers `{"count": 0, ...}` with **no** `results` key at all.

### The day plan

| Time | Step | What you produce |
|---|---|---|
| 9 am | **Frame** | Two tools, their inputs, and the response envelope `{facts, sources, missing}` |
| 10 am | **Write the server** | `server.py`: both tools, neutral descriptions, explicit annotations |
| 11 am | **Test locally** | The MCP Inspector on `http://localhost:8000/mcp`, errors included |
| 1 pm | **Containerize** | `Dockerfile`: pinned `python:3.12-slim`, frozen dependencies, non-root user, `python server.py` |
| 2 pm | **Deploy** | A public `https://.../mcp` URL, a health check on `/health`, `PORT` read from the environment |
| 3 pm | **Plug it in** | A custom connector in Claude, a developer-mode connector in ChatGPT |
| 4 pm | **Evaluate** | `eval/questions.json`: 10 questions, direct, indirect and off-topic. Is the right tool chosen? |
| 5 pm | **Document** | Your connector's `README.md`, `PRIVACY.md`, what's left |

It is a full day. If you fall behind, keep the order: a connector online with one honest tool beats two tools that only run on your laptop.

## Part A: Frame and build (9 am to noon)

**9 am, frame.** Open `server.py`. One tool is sketched, the other is a comment. Every tool returns the same envelope:

```json
{"facts": [...], "sources": [{"name": "...", "url": "https://..."}], "missing": ["what the source does not cover, or why it failed"]}
```

`facts` holds the data as the source recorded it. `sources` lets the assistant cite. `missing` is what keeps the model honest: when nothing is found, or the source is down, `missing` says so, and the assistant has no gap to fill with an invented answer. Write your two tools, their inputs and an example envelope in `REPORT.md` (A1).

**10 am, write the server.**

1. Finish `federal_register_search`: a blank query returns an envelope without calling the API; any error from `fetch` (connection refused, timeout, HTTP 503, invalid JSON) returns a clean envelope with `missing` filled. Never let an exception reach the assistant.
2. Write `company_lookup` and the `find_company` tool, as described in the comments.
3. Rewrite the description of `search_federal_register`: it is salesy on purpose. A description says **what** the tool does, **which source** it uses and **when** to use it. No "best", no "always use this tool": directories reject them, and they push the model to call your tool when it should not.
4. Describe each input with `Annotated[str, Field(description="...")]`, with an example value.
5. Keep the four annotations explicit on both tools: `readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True`. A missing hint is read as the riskiest value.

The tool logic lives in plain functions that receive a `fetch` function, so `pytest -q` tests them offline with fake answers. Keep the function names: the checks call them.

**11 am, test locally.** Start the server with `python server.py`, then in another terminal:

```bash
npx @modelcontextprotocol/inspector
```

In the Inspector, choose the **Streamable HTTP** transport, URL `http://localhost:8000/mcp`, and connect. (If another program already uses port 8000, or `localhost` answers with something else, try `http://127.0.0.1:8000/mcp`, or start the server with `PORT=8001`.) List the tools, read your descriptions as the model will, and call each tool: a normal input, an input that finds nothing, a blank input. Read the results, not only their shape: are the documents really about your query? The sketch sorts with `order=newest`; compare with `order=relevance` in curl, and decide what your tool should do. Then break a source on purpose (change `FEDERAL_REGISTER_URL` to a host that does not exist, restart, call again) and look at the envelope. Put the URL back. Answer A2 and A3.

## Part B: Ship (1 pm to 3 pm)

**1 pm, containerize.** The `Dockerfile` works, but it would not pass a review: `latest` image, everything copied, the server running as root, shell-form `CMD`. Fix it as its comments say. Then:

```bash
docker build -t public-records .
docker run --rm -p 8000:8000 -e PORT=8000 public-records
curl http://localhost:8000/health        # {"status":"ok"}
docker run --rm public-records whoami    # not root
```

**2 pm, deploy.** Read `PORT` from the environment in `server.py` (the host decides the port), and add the `/health` route. Then deploy the image to a host that gives you HTTPS: for example Render, Railway, Fly.io or Google Cloud Run. Set the health check path to `/health`. Set `SEC_USER_AGENT` (your name and email) in the host's environment settings, not in the code. Your MCP URL is `https://<your-app>/mcp`. Free plans that sleep when idle make the first call slow: call `/health` once to wake the server before you test.

**3 pm, plug it in.**

- **Claude:** in the settings, add a **custom connector** with your `https://.../mcp` URL.
- **ChatGPT:** turn on **developer mode** in the settings, then create a connector with the same URL.

The menu names change often; look for "connectors". Then ask a question that does **not** name the tool, such as *"Find recent federal rules about artificial intelligence."* Did the assistant call `search_federal_register`? Did its answer cite the links from `sources`? Answer B1 to B3.

## Part C: Evaluate and document (4 pm to 5 pm)

**4 pm, evaluate.** Complete `eval/questions.json` to 10 questions, at least 2 of each type:

- `direct`: names the source ("Search the Federal Register for ...").
- `indirect`: states the need like a real user, without naming the tool or the source ("Who regulates drones these days?").
- `off_topic`: no tool should run ("Write a poem about the fall"); `expected_tool` is `null`.

Ask each question in a new conversation, in Claude or ChatGPT, and record in `chosen_tool` the tool it called (`null` if none). Count the right choices: that is your score (C1). If a choice is wrong, change a description, not the question, and ask again (C2).

**5 pm, document.** Your repository becomes the public home of your connector, so it needs its own README:

1. Move these instructions out of the way: `git mv README.md INSTRUCTIONS.md`.
2. Copy `templates/README.md` to `README.md` and `templates/PRIVACY.md` to `PRIVACY.md`, and fill them. The README needs a **Deployment** section (with your `https://.../mcp` URL) and a **What's left** section: what you would do next, honestly.
   Before you write the privacy page, call a tool and read your server's logs (`docker logs`, or the host's log page). Write down what is really there, not what you think is there: by default, httpx logs every URL it calls, query string and search words included.
3. Run the certificate checker against your public URL and paste its last line in C3:

```bash
python checker/check_capstone.py https://<your-app>/mcp --repo .
```

To try the checker before you deploy, run it on your laptop: `python checker/check_capstone.py http://localhost:8000/mcp --allow-http`. A local pass does not count for the certificate.

## Deliverable and success criteria

- A public HTTPS MCP endpoint, the repository (`server.py`, `Dockerfile`, `eval/questions.json`, `README.md`, `PRIVACY.md`), and `REPORT.md` completed.
- **Success:** `pytest -q` is all green (GitHub runs it on each push, see the **Actions** tab) **and** the checker prints `RESULT: PASS` against your HTTPS URL.

### Certificate criteria (20 points)

| Criterion | Points | What is looked at | Checked by |
|---|---|---|---|
| Works online | 4 | HTTPS URL, MCP handshake, 2 tools listed, works from Claude or ChatGPT | checker |
| Tool design | 3 | Explicit boolean annotations, neutral descriptions (what, which source, when), described inputs | tests + checker |
| Reliability | 3 | Envelope on every call, `missing` filled when nothing is found or the source is down, timeouts, answer within 55 s | tests + checker |
| Evaluation | 3 | 10 questions (direct, indirect, off-topic), the tool actually chosen, a score and one fix | tests + REPORT C1, C2 |
| Container & deployment | 3 | Pinned slim image, frozen dependencies, non-root user, `PORT` from the environment, `/health` answers 200 | tests + checker |
| Security & data | 2 | Read-only tools, no secret in Git or in the image, no stack trace sent to the assistant, a privacy page | tests + checker |
| Documentation | 2 | README with Deployment and What's left, `PRIVACY.md`, report completed | tests |

**Bonus (up to 2 points):** working OAuth on your connector, or a RAG tool evaluated with recall@5. Describe it in the Going further section of `REPORT.md`.

**Pass = all automated checks green + checker PASS.** The checker is in your repository so you can run it as often as you like; the certificate is issued from a run of the course's own copy against your URL.

**Going further:** cache the SEC file in memory for a few hours instead of downloading 800 KB on every call; add a third tool over another public API, for example the US Census geocoder (free, no key: `curl "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=1600+Pennsylvania+Ave+NW,+Washington,+DC&benchmark=Public_AR_Current&format=json"`), and add it to your evaluation; or protect the connector with OAuth and claim the bonus.

Stuck? Open `HINTS.md`: three hints, from gentle to almost the answer.
