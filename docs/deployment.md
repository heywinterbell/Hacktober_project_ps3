# Deployment: GitHub App + webhook

How ClaimCheck attaches to a real repository. The demo can run in **dry-run mode** without any of this; this doc is for the full wiring and for judge questions.

## 1. Create the GitHub App

1. GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**
2. **Name:** `claimcheck-bot` (or similar)
3. **Webhook URL:** `https://<your-host>/webhook`
   - Local demo: expose with `ngrok http 8000` (or similar) and paste the https URL
4. **Webhook secret:** generate a strong random value; store as `GITHUB_WEBHOOK_SECRET`
5. **Repository permissions:**
   - Issues: Read & write (post triage comments)
   - Pull requests: Read & write (post PR analysis comments)
   - Metadata: Read-only
6. **Subscribe to events:** `Issues`, `Pull request`, `Issue comment`
7. **Generate a private key** and download the `.pem`
8. Install the app on your demo repository

## 2. Credentials (environment variables only — never commit)

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | Token used to read issues/PRs and post comments (App installation token or a PAT with the same scopes) |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for `X-Hub-Signature-256` verification |
| `CLAIMCHECK_DRY_RUN` | `1` = print comments instead of posting (default when no token) |
| `CLAIMCHECK_LLM` | `off` disables the model; unset/`on` allows Ollama |
| `CLAIMCHECK_MODEL` | Model name, default `qwen2.5-coder:7b` |

## 3. Run the server

```bash
export GITHUB_TOKEN=...              # from App private-key exchange or PAT
export GITHUB_WEBHOOK_SECRET=...
export CLAIMCHECK_DRY_RUN=0          # set 1 to print-only

claimcheck serve --port 8000
```

Health check: `GET /health`. Webhook endpoint: `POST /webhook` (HMAC-verified; invalid signature → 401).

## 4. Dry-run fallback (demo default)

If no token or secret is configured, the server still starts: it verifies nothing (or rejects unsigned requests if a secret *is* set) and **prints** the comment Markdown to the log instead of posting. This is the expected mode for the live demo unless the App is fully wired — state it honestly.

## 5. What judges may ask

- *How is the secret handled?* Environment only; HMAC SHA-256 with `hmac.compare_digest`; never logged.
- *What if the host is unreachable?* Dry-run mode + local CLI cover the demo; deployment is documented, not faked.
- *Does it spam issues?* One comment per issue/PR; re-runs update the existing bot comment.
