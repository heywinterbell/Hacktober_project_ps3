# AGENTS.md: rules for AI coding assistants

Project: ClaimCheck (Team Heywinterbell). Read `docs/ARCHITECTURE.md` and `docs/TASKS.md` before coding.

## Non-negotiable
- No API keys or secrets in the repo. Tokens come from environment variables only.
- Only open-weight local models (Qwen2.5-Coder 7B via Ollama). No cloud AI APIs. The tool must work with the model off.
- Verdicts come from real parsing and sandboxed execution, never from LLM judgement.
- Never run untrusted report code outside `sandbox.run_in_sandbox`.
- No stubs, hardcoded results, or fake example outputs.
- No direct pushes to `main` after the init commit. Branch + PR + passing CI.
- Every PR description names the product models used and the coding assistant that helped.
- CI must not require Docker, Ollama, network or secrets.

## Style
- Python 3.11+, type hints, small functions, short comments, ruff-clean.
- Add or update tests with every change. Keep coverage ≥ 80% on `src/`.
- Prefer stdlib. Add a dependency only with a clear reason, and pin a range in `pyproject.toml`.

## Before saying "done"
Run `pytest` and `ruff check .`, then report the results honestly.
