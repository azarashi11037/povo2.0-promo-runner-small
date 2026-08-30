# Security policy

## Do not report secrets in public issues

Never attach `credentials.xml`, `device.xml`, promo codes, JWTs, dashboard credentials, `state.json`, `runtime.json`, `history.jsonl`, packet captures, or screenshots containing account data.

If a secret is committed, revoke or refresh it first, then remove it from the complete Git history. Deleting only the latest file is not sufficient.

## Supported deployment boundary

- Bind the dashboard to loopback or a trusted private network.
- Use an authenticated HTTPS reverse proxy before any remote exposure.
- Keep `POVO_ENABLE_REDEMPTION=0` during setup and diagnosis.
- Never retry an uncertain submission automatically.

This project does not accept features that bypass TLS pinning, extract another user's credentials, or conceal unauthorized access.

## GitHub Actions session state

The optional Actions workflow commits only `state/session.enc`. Its AES-256-GCM key is derived from `POVO_BUNDLE_KEY` with scrypt and must exist only as a repository secret. Plaintext session files are created only under the ephemeral runner temporary directory and are never uploaded as artifacts or caches.

Treat both the bundle key and the decrypted Android session as account credentials. If the bundle key is exposed, rotate it, revoke or replace the account session through the official app, delete the old ciphertext, and perform a fresh import.

Do not submit authentication material in workflow-dispatch inputs, issues, pull requests, Actions logs, or public test fixtures. Pull-request workflows intentionally receive no session secrets.
