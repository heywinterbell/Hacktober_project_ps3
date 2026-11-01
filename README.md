# ClaimCheck

**Triage that tests the claims.** Verify bug reports, security reports, and pull requests with deterministic checks and sandboxed execution — and show maintainers the evidence.

> Built by **Heywinterbell** (Dhruv) at Hacktoberfest Hack Day — [Problem 2](HACKATHON.md).
> Repo: [heywinterbell/Hacktober_project_ps3](https://github.com/heywinterbell/Hacktober_project_ps3)

## What it does

| Input | Example evidence |
|---|---|
| Bug report | `✓ Reproduced on 2.4.1` |
| Security report | `✗ parse_url_v2() does not exist` |
| Pull request | `! No test covers the change` |

ClaimCheck classifies the report, extracts the claim (symbols, versions, repro steps), runs **deterministic checks** (AST symbol lookup, version tags, sandboxed reproduction, diff × coverage intersection, and a `hunt` mode that fires five AI hunter agents), and renders a Markdown evidence comment.

**The LLM never decides a verdict.** Qwen2.5-Coder 7B (open-weight, local via Ollama) is optional and only used for claim extraction and optional summaries. Every verdict (`CONFIRMED` / `REFUTED` / `WARNING`) comes from real parsing and sandboxed execution. The tool works with the model off.

## Prerequisites

| Requirement | Needed for | Install |
|---|---|---|
| **Python 3.10+** (3.11+ recommended) | Core | [python.org](https://www.python.org/downloads/) |
| **Docker** *(optional)* | Strong sandbox isolation for repro / PR test runs | [Docker Desktop](https://docs.docker.com/get-docker/) |
| **Ollama** *(optional)* | Open-weight LLM claim extraction | [ollama.com](https://ollama.com) + `ollama pull qwen2.5-coder:7b` |

Docker and Ollama are **not required** to install the package or run the test suite — without them the tool falls back to weak isolation and rule-based extraction, and flags it clearly in every report.

### Install

The steps below work on both **macOS** and **Windows** (PowerShell / cmd). On Windows, open the folder in **PowerShell** and use the `python` / `pip` commands as shown.

```bash
# 1. Clone the repo
git clone https://github.com/heywinterbell/Hacktober_project_ps3.git
cd Hacktober_project_ps3        # Windows: cd "C:\...\Hacktober_project_ps3"

# 2. (Recommended) create a virtualenv
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows (PowerShell / cmd)

# 3. Install in development mode (pulls typer, fastapi, uvicorn, httpx + dev tools)
pip install -e ".[dev]"

# 4. Optional — Docker sandbox image (for strong-isolation PR checks)
docker build -t claimcheck-sandbox:latest sandbox/

# 5. Optional — local LLM
ollama pull qwen2.5-coder:7b
ollama run qwen2.5-coder:7b     # warm the model once
```

## Usage

### A. The terminal-styled GUI (`main.py`)

`main.py` is a Tkinter app styled like a terminal. Run it and pick a page from the menu:

```bash
python main.py
```

- **Triage Claim** — type a natural-language claim about the repo (e.g. `parse_url() exists in this repo`); the LLM extracts the symbol/snippet and the deterministic checks return the verdict.
- **Doctor (Docker/Ollama)** — shows whether Docker and Ollama are reachable.
- **Help** — in-app usage guide.

> The GUI's claim-extraction helper calls Ollama's `llama3.2:3b` by default. If you only pulled `qwen2.5-coder:7b`, use the CLI below (which defaults to that model).

### B. The installed CLI (`claimcheck`)

After `pip install -e ".[dev]"`, the `claimcheck` command is on your PATH.

```bash
# Check Docker / Ollama availability
claimcheck doctor

# Triage a bug or security report against a local repo
claimcheck triage --repo "C:\path\to\target\repo" --report report.md
claimcheck triage --repo ./my-repo -r report.md --no-llm      # rule-based only
cat report.md | claimcheck triage --repo ./my-repo -r - --json # stdin + JSON output

# Inspect a pull request
claimcheck pr --repo ./my-repo --diff-file change.patch
claimcheck pr --repo ./my-repo --base main --head feature-x    # tests run on the head commit
```

`triage` / `pr` options:

- `--repo PATH` — repo to check (default: current directory)
- `--report FILE` / `-r` — report or PR description text (`-` reads stdin)
- `--diff-file FILE` — unified diff for `pr` (`-` reads stdin); or `--base` + `--head` to run `git diff base...head`
- `--no-llm` — force rule-based extraction
- `--json` — machine-readable output
- `CLAIMCHECK_LLM=off` (env var) — disable the model entirely

**Exit codes:** `0` confirmed · `1` refuted · `2` warning or inconclusive · `3` usage error.

### C. Security `hunt` mode

```bash
claimcheck hunt "The function parse_url_v2() has a SQL injection vulnerability in user input."
```

Runs five hunter agents (SQL injection, command injection, path traversal, XSS, RCE). Each generates a payload with Ollama and executes it in the sandbox; the verdict always comes from the deterministic execution, never the model.

### D. Webhook server (GitHub App)

A GitHub App webhook backend is the intended deployment target — see [docs/deployment.md](docs/deployment.md). The `serve` command is tracked for a future release; right now you can start the FastAPI app directly:

```bash
uvicorn claimcheck.webhook:app --port 8000   # once webhook.py lands
```

## Project structure

```
.
├── main.py                     # Tkinter terminal-styled GUI (python main.py)
├── pyproject.toml              # Build config + deps (typer, fastapi, uvicorn, httpx, dev tools)
├── HACKATHON.md                # Hackathon problem statement
├── docs/
│   ├── ARCHITECTURE.md         # System design, flows & verdict semantics
│   ├── PLAN.md                 # Phased build plan
│   ├── TASKS.md                # PR / task checklist
│   └── deployment.md           # GitHub App + webhook setup
├── sandbox/
│   └── Dockerfile              # Hardened container for untrusted repro code
├── src/claimcheck/
│   ├── cli.py                  # Typer CLI (doctor, triage, pr, hunt)
│   ├── pipeline.py             # Orchestrates triage / pr checks
│   ├── extract.py              # Rule-based + LLM claim extraction
│   ├── llm.py                  # Local Ollama client (qwen2.5-coder:7b)
│   ├── models.py               # Claim, Evidence, Report, Verdict
│   ├── report.py               # Markdown report renderer
│   ├── sandbox.py              # Docker executor + restricted local fallback
│   ├── diffparse.py            # Unified diff parser (changed-line calculation)
│   ├── hunters.py              # Five AI security hunter agents
│   └── checks/
│       ├── symbols.py          # Python AST symbol discovery
│       ├── repro.py           # Sandboxed script reproduction check
│       ├── version.py         # Git tag / package version check
│       └── pr_coverage.py     # Diff line × test-coverage intersection
└── tests/                      # 178 unit & integration tests
```

## Safety

- Reproduction and PR test runs execute **only inside `sandbox.run_in_sandbox`** — a Docker container with `--network none`, read-only filesystem, `--cap-drop ALL`, no env/secret passthrough, and hard resource + time limits.
- Static checks (AST) never run repo code.
- Webhook payloads are verified with HMAC SHA-256.
- Without Docker, a restricted local fallback is used and **every report is flagged `isolation: weak`**.

## Limitations (honest)

- Python repositories only (AST + pytest/coverage).
- Docker required for full isolation (weak-isolation fallback otherwise).
- Failure-description matching is heuristic.
- Kernel-level container escapes are out of scope.

## Development

See [docs/PLAN.md](docs/PLAN.md) for the build plan and [docs/TASKS.md](docs/TASKS.md) for the checklist. CI runs on every PR **without** Docker, Ollama, network, or secrets.

```bash
pytest -m "not docker"          # full suite except Docker-daemon tests
ruff check .
```

Coverage target: ≥ 80% on `src/claimcheck`.

## License

[MIT](LICENSE).
