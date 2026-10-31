# TASKS: PR-by-PR checklist

Rules: init commit (HACKATHON.md) goes straight to `main`. Everything after is branch → PR → green CI → merge. Each PR names the models used and the coding assistant. With two members, either can merge the other's PR; if you are alone, merge your own.

## Init (before 8:30 PM)
- [x] Empty public repo with MIT license
- [x] `HACKATHON.md` committed directly to `main`
- [ ] Repo link submitted on OrganizerHQ (Best Open-Source AI Project)
- [x] Branch protection on `main`

## PR 1: scaffold and workflow  (`feat/scaffold`)
- [x] Add staged files from `Plan/`: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md` stub
- [x] Relocate plan docs: `Plan/ARCHITECTURE.md`, `Plan/PLAN.md`, `Plan/TASKS.md`, `Plan/deployment.md` → `docs/`
- [x] Relocate workflow files: `Plan/ci.yml` → `.github/workflows/ci.yml`; `Plan/pull_request_template.md` → `.github/pull_request_template.md`
- [x] `src/claimcheck/` package, Typer CLI skeleton with `doctor`
- [x] `AGENTS.md` at repo root
- [x] CI green

## PR 2: models and extraction  (`feat/extract`)
- [x] `models.py` dataclasses/enums
- [x] `extract.py`: classify, rule-based extraction (symbols, versions, issue refs, code blocks, "adds tests")
- [x] Tests with many phrasings

## PR 3: symbol and version checks  (`feat/symbols`)
- [ ] `checks/symbols.py` AST finder with qualified names, methods, "did you mean"
- [ ] `checks/version.py` git tags / metadata
- [ ] `tests/fixtures/sample_project/` created
- [ ] Tests: found, missing, typo, nested, syntax-error file skipped safely

## PR 4: sandbox and reproduction  (`feat/sandbox-repro`)
- [ ] `sandbox/Dockerfile` (from `Plan/sandbox/Dockerfile`): python:3.11-slim + pytest + coverage, non-root user
- [ ] `sandbox.py` Docker runner with exact security flags + weak fallback
- [ ] `checks/repro.py` checkout version, run snippet, decide verdict
- [ ] Tests: command construction asserts every flag; timeout; output truncation; `@pytest.mark.docker` integration test

## PR 5: PR coverage check  (`feat/pr-coverage`)
- [ ] Unified-diff parser (hunks, renames, deletions, binary)
- [ ] Coverage run in sandbox, JSON intersect changed lines
- [ ] "adds tests" claim check, failing-suite detection
- [ ] Tests with canned diffs and canned coverage JSON

## PR 6: report and CLI  (`feat/report-cli`)
- [ ] `report.py` Markdown + JSON output
- [ ] `claimcheck triage`, `claimcheck pr` wired to checks
- [ ] End-to-end tests for the three slide cases (`--no-llm`)

## PR 7: webhook server  (`feat/server`)
- [ ] `github.py` signature verify, fetch issue/PR, post/update comment
- [ ] `server.py` `/webhook`, `/health`, background processing, dry-run mode
- [ ] Tests: valid/invalid signature, payload routing, dry-run output

## PR 8: local LLM (`feat/llm`)
- [ ] `llm.py` Ollama wrapper, JSON validation, short timeout
- [ ] Merge LLM extraction into `extract.py`; model-written summary labelled
- [ ] Tests: Ollama down, bad JSON, `--no-llm`; verdict identical with and without the model
- [ ] Confirm HACKATHON.md still matches the model in code

## PR 9: examples and docs  (`docs/examples-readme`)
- [ ] `examples/` three cases with input and **real** output; `run_examples.sh`
- [ ] README: install, usage, architecture, limits, safety, models used
- [ ] Final HACKATHON.md accuracy check (via PR; main is PR-only now)

## Deploy: GitHub App wiring (manual, parallel to PR 8–9)
Follow `docs/deployment.md`. Demo may run dry-run without this.
- [ ] Create GitHub App (webhook URL + secret, Issues/PR permissions, events)
- [ ] Generate credentials; store as env vars only (`GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`)
- [ ] Install App on a demo repo; point webhook at `https://<host>/webhook` (ngrok for local)
- [ ] Smoke-test: valid signature accepted, invalid → 401, dry-run prints comment
- [ ] README "Deployment" section links to `docs/deployment.md`

## Final checks (stop at 6:15 AM)
- [ ] Clean machine test: `pip install -e ".[dev]" && pytest` passes without Docker/Ollama
- [ ] CI green on latest `main`
- [ ] `git log -p | grep -iE "token|secret|api_key"` shows nothing sensitive
- [ ] Models named in HACKATHON.md = models used in code
- [ ] Every PR names models + assistants
- [ ] All members can explain every module
- [ ] Final merge before **6:30 AM**
- [ ] Optional: blog post for the blog challenge (2 × Rs 1,000), and claim partner perks via the "Happy Hacktoberfest" QR
