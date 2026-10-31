# ARCHITECTURE

## Overview

```
 GitHub webhook / CLI input
            │
            ▼
   ┌─────────────────┐
   │ classify + extract│  rules first, optional local LLM (Qwen2.5-Coder 7B via Ollama)
   └────────┬────────┘
            ▼  Claim
   ┌──────────────────────────────────────────────┐
   │ checks (deterministic, produce Evidence)     │
   │  • symbols.py      AST: does the symbol exist│
   │  • version.py      does the version exist    │
   │  • repro.py        run snippet in sandbox    │
   │  • pr_coverage.py  diff × coverage in sandbox│
   └────────┬─────────────────────────────────────┘
            ▼  list[Evidence]
   ┌─────────────────┐
   │ report.py        │  Markdown comment (+ optional model-written summary)
   └────────┬────────┘
            ▼
   print (CLI / dry-run)  or  post comment on the issue/PR
```

Principle: **the LLM never decides a verdict.** It only turns text into a structured claim and, optionally, words a summary of evidence that code already produced.

## Verdict semantics

| Verdict | Symbol | Meaning on the slide |
|---|---|---|
| CONFIRMED | ✓ | claim held up, e.g. "Reproduced on 2.4.1" |
| REFUTED | ✗ | claim is false, e.g. "parse_url_v2() does not exist" |
| WARNING | ! | something missing, e.g. "No test covers the change" |
| INCONCLUSIVE | ? | could not decide; always states why |

Overall verdict: any REFUTED → refuted; else any WARNING → warning; else any CONFIRMED → confirmed; else inconclusive.

## Decision flow per report type

**Security report** ("RCE in parse_url_v2()")
1. Extract symbols and versions.
2. `symbols.check` → if the symbol does not exist: REFUTED, stop (no code executed).
3. If it exists: `version.check`, then `repro.reproduce` in the sandbox if a snippet is given.
4. No snippet → INCONCLUSIVE ("symbol exists, no repro steps").

**Bug report** ("Crash on long URLs")
1. Extract repro snippet and version.
2. `version.check`, then `repro.reproduce` at that version in the sandbox.
3. Crash/traceback/timeout matching the description → CONFIRMED; clean run → INCONCLUSIVE/REFUTED.

**Pull request** ("Fixes #120, adds tests")
1. Parse the diff into changed lines per file.
2. Run tests with coverage in the sandbox on the head commit.
3. Changed executable lines not covered → WARNING "No test covers the change".
4. "Adds tests" but no test files touched → WARNING. Suite fails → REFUTED.
5. `Fixes #N` refers to a real issue → check via GitHub when a token is available.

## Sandbox specification

| Control | Setting |
|---|---|
| Network | `--network none` |
| Secrets | empty environment, nothing forwarded |
| Filesystem | repo mounted read-only, `--read-only`, 64 MB tmpfs `/tmp` |
| Privileges | `--cap-drop ALL`, `no-new-privileges`, non-root user |
| Resources | memory 256 MB, 1 CPU, `--pids-limit 128` |
| Time | hard timeout (default 20 s), container killed |
| Output | truncated (about 20 KB) |
| Fallback | restricted subprocess, flagged `isolation: weak` in every report |

Dependencies are baked into the image at build time (network allowed only then), so runtime stays offline.

## Threat model

- Reports and PRs are **untrusted input**. They may contain real exploit code.
- Static checks (AST) never execute repo code.
- Webhook requests are verified with HMAC SHA-256 and `compare_digest`.
- Tokens and webhook secrets come from environment variables only and are never logged.
- Known limits (state them honestly in the README): Python repos only, Docker required for full isolation, kernel-level container escapes are out of scope.

## LLM usage

- Model: Qwen2.5-Coder 7B Instruct via Ollama (open-weight, local). Env: `CLAIMCHECK_MODEL`, `CLAIMCHECK_LLM=off` to disable.
- Used for: (1) structured claim extraction, JSON validated against schema; (2) optional human-readable summary labelled as model-written.
- Failure mode: Ollama missing, slow or returns bad JSON → silently use rule-based extraction. Tests prove this.

## Module map

| File | Responsibility |
|---|---|
| models.py | Claim, Evidence, Verdict, Report |
| extract.py | classify + rule-based extraction + LLM merge |
| llm.py | Ollama wrapper |
| checks/symbols.py | AST symbol finder, suggestions |
| checks/version.py | git tag / metadata version check |
| checks/repro.py | reproduction in sandbox |
| checks/pr_coverage.py | diff parser + coverage intersection |
| sandbox.py | Docker runner + weak fallback |
| report.py | Markdown rendering |
| github.py | REST calls, signature verification |
| server.py | FastAPI webhook |
| cli.py | Typer commands |
