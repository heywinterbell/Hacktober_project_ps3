# ClaimCheck

**Triage that tests the claims.** Verify bug reports, security reports, and pull requests with deterministic checks and sandboxed execution — and show maintainers the evidence.

> Built by **Heywinterbell** (Ankit Pal, Dhruv) at Hacktoberfest Hack Day — Problem 2.

## What it does

| Input | Example evidence |
|---|---|
| Bug report | `✓ Reproduced on 2.4.1` |
| Security report | `✗ parse_url_v2() does not exist` |
| Pull request | `! No test covers the change` |

ClaimCheck classifies the report, extracts the claim (symbols, versions, repro steps), runs **deterministic checks** (AST symbol lookup, version tags, sandboxed reproduction, diff × coverage), and renders a Markdown evidence comment.

**The LLM never decides a verdict.** Qwen2.5-Coder 7B (local, via Ollama) is optional and only used for claim extraction and summaries. The tool works with the model off.

## Install

Requires Python 3.10 or newer (3.11+ recommended). Docker gives strong sandbox
isolation; Ollama enables the optional open-source LLM extraction. Neither is
required to install or run the test suite.

```bash
pip install -e ".[dev]"
```

## Usage

```bash
claimcheck doctor                                  # check Docker / Ollama availability
claimcheck triage --repo PATH --report FILE        # triage a bug or security report
claimcheck pr --repo PATH --base main --head BR    # analyse a pull request (tests run in the sandbox)
claimcheck pr --repo PATH --diff-file change.patch # same, from a unified diff file ('-' = stdin)
claimcheck serve --port 8000                       # run the GitHub webhook server
python main.py                                     # terminal-styled GUI (Tkinter)
```

Add `--no-llm` to force rule-based extraction. Add `--json` for machine-readable output.
`pr` also takes `--report FILE` (PR title/body, used to check an "adds tests" claim).
Exit codes: 0 confirmed, 1 refuted, 2 warning or inconclusive, 3 usage error.
`pr` needs the sandbox image rebuilt once: `docker build -t claimcheck-sandbox:latest sandbox/`.

## Safety

Reproduction and test runs happen in a Docker sandbox with no network, no secrets, read-only filesystem, dropped capabilities, and hard resource/time limits. Without Docker, a restricted fallback is used and every report is clearly flagged `isolation: weak`.

## Limits (honest)

- Python repositories only (AST + pytest/coverage)
- Docker required for full isolation
- Heuristic matching of failure descriptions
- Kernel-level container escapes are out of scope

## Development

See [docs/PLAN.md](docs/PLAN.md) for the phased build plan and [docs/TASKS.md](docs/TASKS.md) for the PR checklist. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```bash
pytest -m "not docker"
ruff check .
```

## License

MIT — see [LICENSE](LICENSE).
