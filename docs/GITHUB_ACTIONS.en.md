# GitHub Actions guide

[简体中文](GITHUB_ACTIONS.md) | [繁體中文](GITHUB_ACTIONS.zh-Hant.md) | [日本語](GITHUB_ACTIONS.ja.md) | English

This mode is suitable for a public fork. The repository stores only authenticated ciphertext in `state/login.enc` or `state/session.enc`. Email addresses, OTPs, promo codes, and plaintext sessions are never committed to Git or uploaded as artifacts or caches.

## Prerequisites

1. Fork the repository and enable Actions.
2. Open **Settings → Actions → General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Open **Settings → Secrets and variables → Actions**.

## Web UI: initialize with email OTP

### 1. Send the OTP

Create two repository secrets:

- `POVO_BUNDLE_KEY`: at least 20 characters; a random 32-byte value is recommended and should be retained.
- `POVO_LOGIN_EMAIL`: your povo2.0 login email address.

Run **Actions → Start povo2.0 email login → Run workflow**. A successful run sends the email and commits encrypted `state/login.enc`.

### 2. Finish login

Use only the newest email and immediately create:

- `POVO_LOGIN_OTP`: the six-digit OTP.
- `POVO_PROMO_CODE`: the promo code to use on schedule.

Run **Actions → Finish povo2.0 login and redeem once → Run workflow**. Running this explicitly named workflow confirms one first-redemption submission.

The OTP challenge is valid for 15 minutes. If Start is run again, the old email must not be reused because a new challenge has been created.

After the first redemption is confirmed successful, `next_due_at` is automatically set to 7 days and 1 minute after its success minute. No initial date entry is required. `state/login.enc` is then replaced by `state/session.enc`. Delete `POVO_LOGIN_EMAIL`, `POVO_LOGIN_OTP`, and `POVO_PROMO_CODE`; keep only `POVO_BUNDLE_KEY`.

The account check after login currently has no verified, reliable promo-expiration field. JWT expiry is only the short-lived login-token expiry. This project neither treats it as the plan expiry nor guesses the lifetime of an existing promo.

## GitHub CLI

`gh secret set` securely prompts for a value. Do not put secrets directly in command arguments.

```bash
openssl rand -base64 32 | gh secret set POVO_BUNDLE_KEY
gh secret set POVO_LOGIN_EMAIL
gh workflow run login-start.yml
```

After receiving the newest email:

```bash
gh secret set POVO_LOGIN_OTP
gh secret set POVO_PROMO_CODE
gh workflow run login-finish.yml
```

After a successful run:

```bash
gh secret delete POVO_LOGIN_EMAIL
gh secret delete POVO_LOGIN_OTP
gh secret delete POVO_PROMO_CODE
```

Use `gh run list` and `gh run watch` to inspect run status. Logs should contain only sanitized results.

## Scheduled operation

**povo2.0 session keeper** checks hourly at minute 32 UTC, away from the top-of-hour load spike:

1. decrypt state in the ephemeral runner without calling the povo API;
2. exit immediately when `next_due_at` is more than 65 minutes away, without refreshing or committing;
3. when the target enters the 65-minute window, refresh and wait inside the runner;
4. after the target minute arrives, use the single-submit path and refresh again immediately before submission;
5. re-encrypt and commit only when credentials or schedule state actually changed; and
6. if one hourly entry is delayed or dropped, the next entry performs a late fallback.

For example, when the target minute is `:42`, the hourly `:32` entry prepares about 10 minutes early. As the 7-day-and-1-minute rule shifts the target minute, the lead time varies from 0 to 60 minutes, while submission still waits for the target minute. Every entry checks `next_due_at`, pause state, and submission state, preventing duplicates. GitHub cron may still queue, run late, or be dropped and cannot guarantee second-level timing. An uncertain result changes the state to `unknown` and blocks automatic retries.

## Stored data

- `POVO_BUNDLE_KEY`: the long-lived repository secret.
- `state/login.enc`: short-lived encrypted challenge between the two login stages.
- `state/session.enc`: AES-256-GCM ciphertext containing the minimum session, device, promo-code, and schedule state.

The encryption key is derived from `POVO_BUNDLE_KEY` using scrypt with random salt and nonce.

## Fallback import and recovery

If the email API changes, **Import encrypted povo2.0 session** can import an existing authorized Android session. Temporarily set `POVO_CREDENTIALS_B64`, `POVO_DEVICE_B64`, and `POVO_PROMO_CODE`, then delete them after success.

- Invalid OTP: confirm it came from the newest email after the last Start run.
- Expired `state/login.enc`: run Start once again; the old OTP is invalid.
- Lost `POVO_BUNDLE_KEY`: the ciphertext cannot be recovered; log in again.
- Exposed key: delete ciphertext, rotate the secret, and update the account session in the official app.
- Bot cannot push: check workflow permissions and branch protection.
- `MULTIPLE_ADDONS_FOUND`: unresolved; do not rerun repeatedly.

Never place authentication material in workflow inputs, issues, pull requests, Actions logs, or public test data.
