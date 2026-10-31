# HACKATHON.md

## Project

**ClaimCheck** — Triage that tests the claims

- **Team:** Heywinterbell — Ankit Pal, Dhruv
- **Event:** Hacktoberfest Hack Day, NST Rishihood University, Sonipat
- **Challenge:** Problem 2 — "Triage that tests the claims"
- **Category submission:** Best Open-Source AI Project

## The problem

Maintainers receive three kinds of input and waste time on reports that are false, unsafe to try, or untested:

- **Bug reports** — "Crash on long URLs"
- **Security reports** — "RCE in parse_url_v2()"
- **Pull requests** — "Fixes #120, adds tests"

## Our approach

ClaimCheck is a GitHub App backend + CLI that **tests the claim** in an **isolated sandbox (no secrets, no network)** and shows maintainers the **evidence**:

| Input | Evidence |
|---|---|
| Bug report | `✓ Reproduced on 2.4.1` |
| Security report | `✗ parse_url_v2() does not exist` |
| Pull request | `! No test covers the change` |

Verdicts come from **real parsing and sandboxed execution** (AST symbol lookup, version tags, reproduction runs, diff × coverage intersection) — **never from the LLM's opinion**.

## Models used

- **Qwen2.5-Coder 7B Instruct** (`qwen2.5-coder:7b`), open-weight, local via **Ollama**
- Used only for: (1) structured claim extraction from free text, (2) optional human-readable summaries of already-computed evidence (clearly labelled as model-written)
- **Not used for verdicts** — verdicts are deterministic
- The tool **works with the model disabled** (`--no-llm` / `CLAIMCHECK_LLM=off`) via rule-based fallback, so it runs on machines with no Ollama and no keys

No cloud AI APIs are called. No API keys are required to run the tool.

## Safety

- Reports and PRs are untrusted input; reproduction runs only inside a Docker sandbox (`--network none`, read-only, `--cap-drop ALL`, no env passthrough, resource + time limits)
- Static checks (AST) never execute repo code
- Webhook requests verified with HMAC SHA-256
- Weak-isolation fallback (no Docker) is clearly flagged in every report

## License

MIT — see [LICENSE](LICENSE).
