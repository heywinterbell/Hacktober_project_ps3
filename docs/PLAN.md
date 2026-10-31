# PLAN: ClaimCheck — Hacktoberfest Hack Day

Project: ClaimCheck · Problem 2: Triage that tests the claims · Team: Heywinterbell (Ankit Pal, Dhruv)

**One line:** check whether a report is true, safely, and show maintainers the evidence.

## Key deadlines

| When | What |
|---|---|
| 31 Oct, 6:30 PM | Hackathon starts |
| 31 Oct, 8:30 PM | **Repo link + init commit (`HACKATHON.md`) due**, submit on OrganizerHQ |
| Until 12 AM | Mentors available (Krishna, Neetanshu, Kushagar, Sai). Ask early |
| 2:00 AM | Midnight refreshments (ID card needed) |
| 1 Nov, 6:30 AM | **Final push. Repos frozen.** Last merge by then |
| 8:30 AM | Presentations: 8 min pitch + 4 min Q&A + 2 min buffer |
| 1:30 PM | Results and prizes |

## Scoring map (what to optimise)

| Rubric item | What we do |
|---|---|
| Functional Correctness (largest) | All three checks really work; end-to-end tests for the three slide cases |
| Open-Source AI Use (up to 15) | Qwen2.5-Coder via Ollama, really used, honestly named. Claiming an unused model = 0 and −5 overall |
| Testing & Evidence | pytest suite, ≥ 80% coverage (enforced in CI), `examples/` with real outputs |
| Open-Source Workflow (10) | PR-only after init commit, CI on every PR, PR template naming models + assistants |
| Panel: Design & Trade-offs Q&A | Know why AST + sandbox, why LLM never decides verdicts |
| Panel: Live Demo | Three cases run live from the CLI |
| Panel: Problem Understanding | Use the slide's own wording |
| Must pass | Public repo with open-source license; any member can explain the code |

## Scope control

**Must have (MVP):** symbol check, sandboxed repro, PR diff coverage, CLI, report, tests, CI, examples, README.
**Should have:** webhook server in dry-run mode, LLM extraction with fallback, version check.
**Nice to have:** posting real comments to a live repo, GitHub App manifest, multi-language symbol check (tree-sitter).
Cut from the bottom of the list if time runs out. Don't fake anything.

---

## Phases and steps

Rules that apply to every phase: branch → PR → green CI → merge. Every PR names the models used and the coding assistant. No stubs, no hardcoded results. Run `pytest` and `ruff check .` before calling anything done.

### Phase 0 — Init (6:30 – 8:30 PM) · hard deadline

**Goal:** valid submission on OrganizerHQ before 8:30 PM.

1. Create a **new, empty, public** repo with the **MIT** license (`Plan/LICENSE`). Name it after the project.
2. Commit `Plan/HACKATHON.md` **directly to `main`** — this is the one allowed direct push.
3. Submit the repo link on OrganizerHQ (Challenges → Add Submission → **Best Open-Source AI Project**; Gemma challenge is Problem 8 only).
4. Turn on branch protection for `main` (require PR + passing CI).
5. Local prep: `ollama pull qwen2.5-coder:7b`; `docker build -t claimcheck-sandbox:latest sandbox/`; `docker run --rm hello-world`.

**Exit criteria:** repo public, `HACKATHON.md` on main, submission received, Docker + Ollama verified (or risks logged).

### Phase 1 — Foundation (8:30 – 9:30 PM) · PR1 + PR2

**Goal:** installable package, CI pipeline, and claim extraction working.

**PR 1 — scaffold (`feat/scaffold`)**
1. Add staged files: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md` stub.
2. Relocate `ARCHITECTURE.md`, `PLAN.md`, `TASKS.md`, `deployment.md` → `docs/`; `ci.yml` → `.github/workflows/`; PR template → `.github/`.
3. Create `src/claimcheck/` package + Typer CLI skeleton with `doctor`.
4. `AGENTS.md` at repo root.

**PR 2 — models + extraction (`feat/extract`)**
1. `models.py`: `Claim`, `Evidence`, `Verdict`, `Report` dataclasses/enums (exact shapes in `MASTER_PROMPT.md` §5).
2. `extract.py`: `classify()` + rule-based extraction (backticked symbols, versions, `fixes #N`, fenced snippets, "adds tests").
3. Tests with many phrasings.

**Exit criteria:** `pip install -e ".[dev]"` works; CI green on PR1; extraction unit tests pass; `claimcheck doctor` runs.

### Phase 2 — Static verification (9:30 – 11:30 PM) · PR3

**Goal:** the security-report case (`✗ parse_url_v2() does not exist`) works without executing any repo code.

1. `checks/symbols.py`: AST walker — functions, classes, methods (`Class.method`), qualified names; `difflib` "did you mean" on miss.
2. `checks/version.py`: claimed version exists as git tag or package metadata.
3. Create `tests/fixtures/sample_project/` (tiny package with `parse_url()`, tests, a vulnerable function).
4. Tests: found / missing / typo / nested / syntax-error file skipped safely.
5. **Ask a mentor before midnight** if anything is unclear (slot in schedule).

**Exit criteria:** security case returns `REFUTED` with suggestion on the fixture; zero repo code executed by static checks; CI green.

### Phase 3 — Safe execution (11:30 PM – 2:00 AM) · PR4

**Goal:** the bug-report case (`✓ Reproduced on 2.4.1`) runs real code without touching the host.

1. `sandbox/Dockerfile` (from `Plan/sandbox/Dockerfile`): python:3.11-slim + pytest + coverage, non-root.
2. `sandbox.py`: `run_in_sandbox()` with **every** flag — `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, `--pids-limit 128`, `--memory 256m`, `--cpus 1`, `--tmpfs /tmp:rw,size=64m`, repo ro-mount, empty env, hard timeout, ~20 KB output truncation.
3. Weak fallback (restricted subprocess) clearly flagged `isolation: weak`.
4. `checks/repro.py`: checkout claimed version into temp copy, run snippet via sandbox, decide verdict from exit/traceback/timeout vs clean run.
5. Tests: command-construction asserts every flag; timeout; truncation; `@pytest.mark.docker` integration test.

**Exit criteria:** sandbox command tests pass in CI (no Docker needed); with Docker locally, fixture bug reproduces → `CONFIRMED`; without Docker → `weak` flag visible. **Midnight refreshments at 2:00 AM.**

### Phase 4 — PR analysis (2:00 – 3:30 AM) · PR5

**Goal:** the PR case (`! No test covers the change`) works via diff × coverage.

1. `checks/pr_coverage.py`: own unified-diff parser (hunks, renames, deletions, binary) — unit-tested edge cases.
2. Run suite with coverage in sandbox on PR head; intersect coverage JSON with changed lines (exclude tests/non-code).
3. "Adds tests" claim check; failing-suite → `REFUTED`.
4. Tests with canned diffs and canned coverage JSON (CI-safe, no Docker).

**Exit criteria:** all three slide cases now have deterministic check paths; canned-data tests green; coverage gate (`--cov-fail-under=80`) holds.

### Phase 5 — Interface (3:30 – 4:30 AM) · PR6

**Goal:** one command produces the slide evidence for all three cases.

1. `report.py`: Markdown with ✓/✗/!, collapsible `<details>` logs, sandbox status line, optional model-written summary.
2. Wire `claimcheck triage` and `claimcheck pr` to the checks.
3. **End-to-end tests for the three slide cases** using the fixture + `--no-llm`.

**Exit criteria:** `pytest` e2e suite reproduces all three slide outputs from the CLI; `--json` emits the `Report` shape.

### Phase 6 — Integration (4:30 – 5:30 AM) · PR7 + PR8

**Goal:** webhook server dry-runs safely; LLM path proven to never change verdicts.

**PR 7 — server (`feat/server`)**
1. `github.py`: HMAC SHA-256 verify (`compare_digest`), fetch issue/PR, post/update one comment.
2. `server.py`: `POST /webhook`, `GET /health`, background processing, dry-run default.
3. Tests: valid/invalid signature, payload routing, dry-run output.
4. (Manual, parallel) GitHub App wiring per `docs/deployment.md` — see TASKS "Deploy" section.

**PR 8 — local LLM (`feat/llm`)**
1. `llm.py`: Ollama wrapper, JSON schema validation, short timeout, `--no-llm` / `CLAIMCHECK_LLM=off`.
2. Merge into `extract.py`; summaries labelled "Model-written summary (qwen2.5-coder:7b)".
3. Tests: Ollama down, bad JSON, verdict **identical** with and without model.
4. Confirm `HACKATHON.md` still matches the model in code.

**Exit criteria:** invalid webhook signature → 401; dry-run prints comment; LLM-off tests pass without Ollama; verdict invariance test green.

### Phase 7 — Ship (5:30 – 6:15 AM) · PR9 + freeze

**Goal:** honest examples, complete docs, clean machine passes, merge before freeze.

1. `examples/` — three cases, input + **real** tool output (regenerate via `run_examples.sh`; never hand-write outputs).
2. README complete: install, usage, architecture, limits, safety, models used; link `docs/deployment.md`.
3. Final `HACKATHON.md` accuracy check (via PR; main is PR-only).
4. Clean-machine test: `pip install -e ".[dev]" && pytest` with no Docker/Ollama/network.
5. Secret scan: `git log -p | grep -iE "token|secret|api_key"` clean.
6. CI green on latest `main`. **Stop at 6:15 AM — no merges after unless CI is already green.**

**Exit criteria:** Definition of done (below) met; final merge before **6:30 AM**.

### Phase 8 — Demo prep (6:30 – 8:30 AM)

**Goal:** 8-minute pitch that survives a Docker/Ollama hiccup.

1. Rehearse the demo script (below) twice; time it.
2. Record fallback video/screenshots of the three cases.
3. Both members re-read every module — judges can ask anyone anything.
4. Sleep if possible.

---

## Demo script (8 minutes)

1. (0:30) The problem: maintainers waste time on reports that are false, unsafe to try, or untested.
2. (1:00) Architecture in one slide: extract claim → deterministic checks → evidence. The LLM never decides.
3. (1:30) **Case 1**: bug report "Crash on long URLs" → `✓ Reproduced on 2.4.1` (sandbox flags shown).
4. (1:30) **Case 2**: security report "RCE in parse_url_v2()" → `✗ parse_url_v2() does not exist`, with a "did you mean" suggestion. No code was executed.
5. (1:30) **Case 3**: PR "Fixes #120, adds tests" → `! No test covers the change`, listing file:lines.
6. (1:00) Safety: no network, no secrets, read-only, resource limits; webhook signature verification.
7. (0:30) Open-source AI use: Qwen2.5-Coder via Ollama for extraction and summaries; tool works without it.
8. (0:30) Workflow: PR history, CI, tests, what we learned, what's next.

Prepare a pre-recorded fallback video/screenshots in case the live demo fails (Docker/Ollama hiccups).

## Likely judge questions

- *Why is the LLM not deciding verdicts?* Models hallucinate; maintainers need evidence they can verify, so verdicts come from parsing and execution.
- *How do you keep a malicious report from harming the host?* Sandbox controls table; static checks never run code; weak-isolation fallback is clearly flagged.
- *What if the report has no repro steps?* INCONCLUSIVE with the reason, never a guess.
- *How do you find the changed lines in a PR?* Our own unified-diff parser, intersected with coverage JSON.
- *What are the limits?* Python only, Docker needed for full isolation, heuristic matching of the failure description.
- *Which models, and why?* Qwen2.5-Coder 7B: open-weight, runs on a laptop, strong at code, used only for extraction and summaries.
- *How does it attach to a repo?* GitHub App webhook with HMAC verification — see `docs/deployment.md`; demo runs dry-run.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Docker not working on the laptop | `claimcheck doctor`, weak fallback flagged honestly, test Docker early (Phase 0) |
| Ollama slow or crashes | Rule-based fallback, short timeout, `--no-llm` |
| CI fails on last commit | Don't merge after 6:15 AM unless CI is green; keep CI independent of Docker/Ollama |
| Time runs out | Cut scope from "nice to have" up; never ship stubs |
| Secret committed | `.gitignore`, env vars only, run a quick `git log -p` grep before final push |
| GitHub App not ready by demo | Dry-run mode is the documented default; `deployment.md` proves the full path exists |

## Definition of done

- `pip install -e ".[dev]" && pytest` passes on a clean machine, no Docker, no Ollama, no network.
- `claimcheck triage` and `claimcheck pr` produce correct evidence for all three slide cases (sandbox when Docker is present).
- Webhook server verifies signatures and runs in dry-run mode locally.
- CI green on the last commit (including `--cov-fail-under=80`); PR history shows models + assistants named; PR template present.
- `examples/`, README, LICENSE (MIT), `HACKATHON.md` present; no secrets anywhere.
- Repo layout matches `MASTER_PROMPT.md` §4 (including `sandbox/Dockerfile` and `docs/deployment.md`).
