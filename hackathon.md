# HACKATHON.md

**Event:** Hacktoberfest Hack Day, NST Rishihood University, Sonipat

## Team

- **Team name:** Heywinterbell
- **Members:**
  - Dhruv

## Problem Statement

**Problem 2: Triage that tests the claims**

A GitHub App / CLI that takes a bug report, a security report, or a pull request, extracts the claim it makes, and tests that claim in an isolated sandbox (no secrets, no network). It then shows maintainers the evidence: reproduced, claim invalid (e.g. a function does not exist), or no test covers the change.

## Models Used

| Model | Why we use it |
|-------|---------------|
| Qwen2.5-Coder 7B Instruct (open-weight, run locally via Ollama) | Free and open-weight. Small enough to run on a laptop and strong at code. Used only to turn free-text reports into structured claims (symbol names, versions, repro steps) and to write a readable summary of the evidence. |

**Verdicts are not decided by the model.** Reproduced, not found and uncovered-change results come from real parsing and sandboxed execution. The tool also works without a model, falling back to rule-based claim extraction.

## Notes

- All models run locally; no cloud AI APIs and no API keys or secrets in this repo.
- Started from an empty repo, under an open-source license (MIT).
- AI coding assistants used are named in each pull request.